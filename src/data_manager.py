import threading
import time
import concurrent.futures
from datetime import datetime
from src.utils import is_market_open
from src.theme_engine import analyze_popular_themes

class DataManager:
    def __init__(self, api, strategy):
        self.api = api
        self.strategy = strategy
        
        # --- 전역 상태 및 데이터 캐시 ---
        self.status_msg = ""
        self.status_time = 0
        self.last_log_msg = ""
        self.last_log_time = 0
        self.trading_logs = [] # 최근 10개 거래 로그
        self.cached_holdings = []
        self.cached_asset = {"total_asset":0, "total_principal":0, "stock_eval":0, "stock_principal":0, "cash":0, "pnl":0, "deposit":0}
        self.cached_stock_info = {} # 종목별 추가 정보 캐시 (TP/SL, 볼륨 스파이크 등)
        self.cached_hot_raw = []
        self.cached_vol_raw = []
        self.cached_recommendations = [] 
        self.cached_market_data = {}
        self.cached_vibe = "Neutral"
        self.cached_panic = False
        self.last_update_time = ""
        self.ranking_filter = "ALL"
        self.is_kr_market_active = False
        self.last_size = (0, 0)
        
        # --- 글로벌 진행 표시기 상태 ---
        self.global_busy_msg = None
        self.busy_anim_step = 0
        
        self.data_lock = threading.Lock()
        self.ui_lock = threading.Lock()
        
        # 개별 갱신 시각 관리
        self.last_times = {"index": 0, "asset": 0, "ranking": 0}

    def set_busy(self, msg):
        self.global_busy_msg = msg

    def clear_busy(self):
        self.global_busy_msg = None

    def show_status(self, msg, is_error=False):
        import os
        color = "\033[91m" if is_error else "\033[92m"
        # 터미널 너비 초과 방지 (ANSI 코드 제외 실제 표시 길이 기준 잘라냄)
        try:
            max_len = os.get_terminal_size().columns - 12  # [STATUS] + 여백
        except: max_len = 100
        if len(msg) > max_len:
            msg = msg[:max_len - 2] + ".." 
        self.status_msg = f"{color}[STATUS] {msg}\033[0m"
        self.status_time = time.time()

    def add_log(self, msg):
        self.last_log_msg = f"\033[96m[LOG] {msg}\033[0m"
        self.last_log_time = time.time()

    def add_trading_log(self, msg):
        t_str = datetime.now().strftime('%H:%M:%S')
        self.trading_logs.append(f"\033[95m[TRADING] [{t_str}] {msg}\033[0m")
        if len(self.trading_logs) > 10:
            self.trading_logs.pop(0)
        from src.logger import log_trade
        log_trade(msg)

    # --- 데이터 업데이트 함수 (강제 갱신용) ---
    def update_all_data(self, is_virtual, force=False):
        self.set_busy("데이터 동기화")
        try:
            curr_t = time.time()
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                future_trend = executor.submit(self.strategy.determine_market_trend)
                future_hot = executor.submit(self.api.get_naver_hot_stocks)
                future_vol = executor.submit(self.api.get_naver_volume_stocks)
                future_balance = executor.submit(self.api.get_full_balance, force=True)
                
                future_trend.result()
                self.cached_market_data = self.strategy.current_market_data
                self.cached_vibe = self.strategy.current_market_vibe
                self.cached_panic = self.strategy.global_panic
                self.last_times["index"] = curr_t
                
                h_raw = future_hot.result(); v_raw = future_vol.result()
                self.cached_hot_raw = h_raw; self.cached_vol_raw = v_raw
                themes = analyze_popular_themes(h_raw, v_raw)
                self.last_times["ranking"] = curr_t
                
                h, a = future_balance.result()
                self.cached_holdings = h; self.cached_asset = a
                self.last_times["asset"] = curr_t

            for stock in h:
                code = stock.get('pdno')
                p_data = self.api.get_inquire_price(code)
                tp, sl, spike = self.strategy.get_dynamic_thresholds(code, self.cached_vibe.lower(), p_data)
                
                # 시세 API에서 가져온 전일 대비 데이터를 캐시에 저장
                day_val = p_data.get('vrss', 0) if p_data else 0
                day_rate = p_data.get('ctrt', 0) if p_data else 0
                
                self.cached_stock_info[code] = {
                    "tp": tp, "sl": sl, "spike": spike,
                    "day_val": day_val, "day_rate": day_rate
                }
            
            self.last_update_time = datetime.now().strftime('%H:%M:%S')
            self.add_log("데이터 동기화 완료")
            return True
        except Exception as e:
            from src.logger import log_error
            log_error(f"Update Error: {e}")
            return False
        finally:
            self.clear_busy()

    # --- 데이터 업데이트 스레드 (지수 및 네이버 랭킹 전담: Naver/Yahoo) ---
    def index_update_worker(self):
        while True:
            try:
                curr_t = time.time()
                self.strategy.determine_market_trend()
                h_raw = self.api.get_naver_hot_stocks(); v_raw = self.api.get_naver_volume_stocks()
                themes = analyze_popular_themes(h_raw, v_raw)
                self.strategy.update_ai_recommendations(themes, h_raw, v_raw, progress_cb=None)
                self.strategy.refresh_yesterday_recs_performance(h_raw, v_raw)
                with self.data_lock:
                    self.cached_market_data = self.strategy.current_market_data
                    self.cached_vibe = self.strategy.current_market_vibe
                    self.cached_panic = self.strategy.global_panic
                    self.cached_hot_raw = h_raw; self.cached_vol_raw = v_raw
                self.last_times["index"] = curr_t; self.last_times["ranking"] = curr_t
                kospi_info = self.cached_market_data.get("KOSPI")
                self.is_kr_market_active = kospi_info.get("status") == "02" if (kospi_info and "status" in kospi_info) else is_market_open()
            except Exception as e:
                from src.logger import log_error
                log_error(f"Index/Ranking Update Error: {e}")
            time.sleep(5)

    # --- 데이터 업데이트 스레드 (KIS API: 잔고/주문) ---
    def data_update_worker(self, is_virtual):
        import math
        self.update_all_data(is_virtual, force=True)
        
        while True:
            try:
                curr_t = time.time()
                h, a = self.api.get_full_balance(force=True)
                if h or a.get('total_asset', 0) > 0:
                    with self.data_lock:
                        self.cached_holdings = h; self.cached_asset = a
                        for stock in h:
                            code = stock.get('pdno')
                            p_data = self.api.get_inquire_price(code)
                            tp, sl, spike = self.strategy.get_dynamic_thresholds(code, self.cached_vibe.lower(), p_data)
                            
                            # 시세 API에서 가져온 전일 대비 데이터를 캐시에 저장
                            day_val = p_data.get('vrss', 0) if p_data else 0
                            day_rate = p_data.get('ctrt', 0) if p_data else 0
                            
                            self.cached_stock_info[code] = {
                                "tp": tp, "sl": sl, "spike": spike,
                                "day_val": day_val, "day_rate": day_rate
                            }
                    self.last_times["asset"] = curr_t
                    self.add_log(f"잔고 업데이트 완료 (Cash: {a['cash']:,}원)")

                vibe = self.cached_vibe
                self.cached_recommendations = self.strategy.get_buy_recommendations(market_trend=vibe.lower())
                
                if self.is_kr_market_active and not self.cached_panic:
                    auto_res = self.strategy.run_cycle(market_trend=vibe.lower(), skip_trade=False)
                    if auto_res:
                        for r in auto_res: self.add_trading_log(f"🤖 자동: {r}")
                    
                    if self.strategy.bear_config.get("auto_mode", False) and self.cached_recommendations:
                        r = self.cached_recommendations[0]
                        p = self.api.get_inquire_price(r['code'])
                        if p:
                            qty = math.floor(r['suggested_amt'] / p['price'])
                            if qty > 0:
                                success, msg = self.api.order_market(r['code'], qty, True)
                                if success:
                                    msg_txt = f"자동{r['type']}: {r['name']} {qty}주"
                                    self.strategy.last_avg_down_msg = f"[{datetime.now().strftime('%H:%M')}] {msg_txt}"
                                    self.strategy.record_buy(r['code'], p['price'])
                                    self.add_trading_log(f"🤖 {msg_txt}")
                                    self.update_all_data(is_virtual, force=True)

                    if self.strategy.auto_ai_trade and self.strategy.ai_recommendations:
                        top_ai = self.strategy.ai_recommendations[0]
                        
                        # [개편] 평시 장세(Bull/Neutral)에서 인버스 상품 추천 시 자동 매수 제외
                        skip_auto_buy = False
                        if top_ai.get('is_inverse', False) and "defensive" not in vibe.lower() and "bear" not in vibe.lower():
                            skip_auto_buy = True
                            self.add_log(f"보류: {top_ai['name']} (인버스 상품은 하락 방어장에서만 자동 매수)")
                        
                        is_held = any(holding['pdno'] == top_ai['code'] for holding in self.cached_holdings)
                        if not is_held and not skip_auto_buy:
                            p = self.api.get_inquire_price(top_ai['code'])
                            if p:
                                a_cfg = self.strategy.ai_config
                                amt = a_cfg.get("amount_per_trade", 500000)
                                qty = math.floor(amt / p['price'])
                                if qty > 0:
                                    success, msg = self.api.order_market(top_ai['code'], qty, True)
                                    if success:
                                        self.add_trading_log(f"✨ AI자율매수: {top_ai['name']} {qty}주 선점")
                                        # 자동 매수 성공 → 프리셋 전략 자동 할당
                                        preset_result = self.strategy.auto_assign_preset(top_ai['code'], top_ai['name'])
                                        if preset_result:
                                            self.add_trading_log(f"📋 전략 자동적용: [{preset_result['preset_name']}] TP:{preset_result['tp']:+.1f}% SL:{preset_result['sl']:.1f}%")
                                        self.update_all_data(is_virtual, force=True)
                                    else:
                                        if "잔고가 부족" in msg: self.strategy.auto_ai_trade = False
                                        self.add_log(f"AI매수 실패: {msg}")

                self.last_update_time = datetime.now().strftime('%H:%M:%S')
            except Exception as e:
                from src.logger import log_error
                log_error(f"Data Update Error: {e}")
            time.sleep(5)

    def start_workers(self, is_virtual):
        threading.Thread(target=self.index_update_worker, daemon=True).start()
        threading.Thread(target=self.data_update_worker, args=(is_virtual,), daemon=True).start()
