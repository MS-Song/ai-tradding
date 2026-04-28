import threading
import time
import concurrent.futures
import queue
from datetime import datetime
from src.utils import is_market_open, is_ai_enabled_time
from src.theme_engine import analyze_popular_themes
from src.logger import log_error, log_trade, trading_log, cleanup_text_log
from src.utils.notifier import TelegramNotifier

class DataManager:
    def __init__(self, api, strategy):
        self.api = api
        self.strategy = strategy
        self.is_running = True # [추가] 실행 상태 플래그
        
        # --- 알림 엔진 초기화 ---
        self.notifier = TelegramNotifier(dm=self)
        
        # --- 전역 상태 및 데이터 캐시 ---
        self.status_msg = ""
        self.status_time = 0
        self.last_log_msg = ""
        self.last_log_time = 0
        self.trading_logs = [] # 최근 10개 거래 로그
        self.cached_holdings = []
        self.cached_asset = {"total_asset": 0, "total_principal": 0, "cash": 0, "pnl": 0, "stock_eval": 0, "stock_principal": 0, "daily_pnl_rate": 0.0}
        self.cached_chart_data = {"code": "", "name": "", "candles": []} # [Phase 3 추가]
        self.cached_stock_info = {} # 종목별 추가 정보 캐시 (TP/SL, 볼륨 스파이크 등)
        self.cached_hot_raw = []
        self.cached_vol_raw = []
        self.cached_recommendations = [] 
        self.cached_market_data = {}
        self.cached_vibe = "Neutral"
        self.cached_panic = False
        self.cached_dema_info = {} # [추가] 지수 DEMA 정보 캐시
        self.cached_ai_costs = {"gemini": 0, "groq": 0} # [수정] 모델별 분리
        self.last_update_time = ""
        self.ranking_filter = "ALL"
        self.is_kr_market_active = False
        self.cached_holdings_fetched = False # [추가] 최초 잔고 수집 여부 플래그
        self.last_size = (0, 0)
        
        # --- 알림 상태 관리 ---
        self.last_notified_vibe = "Neutral"
        self.last_notified_halted = False
        self.notified_dates = {"market_start": "", "market_end": ""}
        
        # --- 업데이트 정보 ---
        self.update_info = {"has_update": False, "latest_version": "", "download_url": "", "is_downloading": False, "progress": 0}
        
        # --- 시황 및 AI 분석 상태 (Task 추가) ---
        self.market_info_status = "대기"  # 정상, 실패, 대기
        self.worker_results = {}          # {worker_name: result_msg}
        self.worker_last_tasks = {}       # {worker_name: last_task_name}
        self._sync_queue = queue.Queue()   # [추가] 동기화 요청 큐
        
        # --- 입력 상태 관리 (Task 4) ---
        self.is_input_active = False
        self.input_prompt = ""
        self.input_buffer = ""
        self.current_prompt_mode = None  # [추가] 현재 입력 프롬프트의 모드 (예: STRATEGY)
        self.is_full_screen_active = False
        
        # --- 글로벌 진행 표시기 상태 ---
        self._worker_statuses = {} # {worker_name: status_msg}
        self._global_busy_msg = None
        self.busy_anim_step = 0
        
        self.data_lock = threading.Lock()
        self.ui_lock = threading.Lock()
        
        # 개별 갱신 시각 관리
        self.last_times = {"index": 0, "asset": 0, "ranking": 0}
        self.worker_names = {}             # [추가] 워커 키에 대응하는 표시 이름 (예: STOCK_005930 -> 005930_삼성전자)
        self.ma_20_cache = {} # 종목별 최근 20분봉 이동평균선 캐시
        
        # --- 텔레그램 알림 추적 ---
        with trading_log.lock:
            trades = trading_log.data.get("trades", [])
            # 시작 시점의 최신 거래 시각을 기록하여 과거 알림 재전송 방지
            self.last_notified_trade_time = trades[0]['time'] if trades else ""
        
        # [추가] 시스템 시작 알림
        self.notifier.notify_alert("시스템 시작", "🚀 KIS-Vibe-Trader 트레이딩 엔진이 가동되었습니다.")

    def set_busy(self, msg, worker="GLOBAL", friendly_name=None):
        with self.data_lock:
            self._worker_statuses[worker] = msg
            self.last_times[worker.lower()] = time.time() # [추가] 갱신 시각 기록
            self.worker_last_tasks[worker] = msg         # [추가] 마지막 작업 기록
            if friendly_name:
                self.worker_names[worker] = friendly_name

    def update_worker_status(self, worker, result=None, last_task=None, friendly_name=None):
        """워커의 상태(결과, 마지막 작업)를 기록합니다. set_busy와 달리 '작업 중' 상태로 만들지 않습니다."""
        with self.data_lock:
            if result is not None:
                self.worker_results[worker] = result
            if last_task is not None:
                self.worker_last_tasks[worker] = last_task
            if friendly_name:
                self.worker_names[worker] = friendly_name
            self.last_times[worker.lower()] = time.time()

    def is_busy(self):
        """UI 표시용: 하나라도 작업 중이면 True"""
        with self.data_lock:
            return any(v != "대기중" for v in self._worker_statuses.values())

    def is_blocking_busy(self):
        """매매 차단용: GLOBAL 작업(파일 저장, 로그 정리 등) 중인 경우에만 True. 
        INDEX/DATA 등 백그라운드 분석 중에는 매매를 차단하지 않습니다.
        """
        with self.data_lock:
            # GLOBAL 워커가 대기중이 아니면 매매 차단
            return self._worker_statuses.get("GLOBAL", "대기중") != "대기중"

    def clear_busy(self, worker="GLOBAL"):
        with self.data_lock:
            self._worker_statuses.pop(worker, None)

    @property
    def global_busy_msg(self):
        with self.data_lock:
            # Aggregate statuses
            statuses = []
            
            # 1. GLOBAL이 최우선 (사용자 요청 작업)
            if "GLOBAL" in self._worker_statuses:
                statuses.append(self._worker_statuses["GLOBAL"])
            
            # 2. Strategy의 실시간 액션 (매매 등) - 대기중 제외
            if hasattr(self.strategy, 'current_action') and self.strategy.current_action and self.strategy.current_action != "대기중":
                statuses.append(self.strategy.current_action)

            # 3. Market 분석 상태 추가 (분석 중인 경우에만 중복 체크하며 추가)
            if hasattr(self.strategy, 'is_analyzing') and self.strategy.is_analyzing:
                if "시장분석" not in statuses:
                    statuses.append("시장분석")

            # [추가] 4. Telegram 알림 엔진 상태 추가
            if hasattr(self, 'notifier') and self.notifier.status_msg and self.notifier.status_msg != "대기중":
                statuses.append(f"텔레그램:{self.notifier.status_msg}")

            # 4. 기타 워커들 (INDEX, DATA 등)
            other_statuses = [v for k, v in self._worker_statuses.items() if k != "GLOBAL"]
            if other_statuses:
                # 중복된 메시지 제거 및 정렬
                for s in sorted(list(set(other_statuses))):
                    # 공백 제거 후 비교하여 유사 메시지 중복 방지
                    clean_s = s.replace(" ", "")
                    # 이미 리스트에 비슷한 의미의 메시지가 있으면 스킵
                    if not any(clean_s in (exist.replace(" ", "")) for exist in statuses):
                        statuses.append(s)
            
            if not statuses:
                return None
            
            # [수정] 공간이 충분하므로 인위적인 글자수 제한(60자) 제거
            return " | ".join(statuses)

    def show_status(self, msg, is_error=False):
        import os
        color = "\033[91m" if is_error else "\033[92m"
        # 터미널 너비 초과 방지 (ANSI 코드 제외 실제 표시 길이 기준 잘라냄)
        try:
            max_len = os.get_terminal_size().columns - 12  # [STATUS] + 여백
        except: max_len = 100
        if len(msg) > max_len:
            msg = msg[:max_len - 2] + ".." 
        prefix = "[ERROR]" if is_error else "[STATUS]"
        self.status_msg = f"{color}{prefix} {msg}\033[0m"
        self.status_time = time.time()
        
    def _update_daily_metrics(self, a):
        """총자산 정보를 바탕으로 당일 수익금 및 수익률을 계산하여 딕셔너리에 주입"""
        if not a or a.get('total_asset', 0) <= 0: return
        
        today_str = datetime.now().strftime('%Y-%m-%d')
        
        # 1. KIS API에서 제공하는 전일 평가 금액(prev_day_asset)을 우선적으로 기준점으로 사용
        # 장 중간에 앱을 재시작하더라도 당일 전체의 수익률을 정확히 계산하기 위함
        p_asset = a.get('prev_day_asset', 0)
        if p_asset > 0:
            self.strategy.start_day_asset = p_asset
            self.strategy.last_asset_date = today_str
        else:
            # 2. 전일 자산 데이터가 없을 경우에만 기존처럼 앱 시작 시점 자산 사용 (Fallback)
            if self.strategy.start_day_asset == 0 or self.strategy.last_asset_date != today_str:
                self.strategy.start_day_asset = a['total_asset']
                self.strategy.last_asset_date = today_str
                self.strategy._save_all_states()
                self.add_log(f"📅 기준 자산 설정(Fallback): {self.strategy.start_day_asset:,.0f}원")

        if self.strategy.start_day_asset > 0:
            a['daily_pnl_rate'] = (a['total_asset'] / self.strategy.start_day_asset - 1) * 100
            a['daily_pnl_amt'] = a['total_asset'] - self.strategy.start_day_asset
        else:
            a['daily_pnl_rate'] = 0.0
            a['daily_pnl_amt'] = 0.0


    def notify_latest_trades(self):
        """아직 알림을 보내지 않은 최신 거래 내역을 탐색하여 텔레그램으로 전송합니다."""
        with trading_log.lock:
            trades = trading_log.data.get("trades", [])
            if not trades: return
            
            new_trades = []
            for t in trades:
                # 이미 보낸 시점보다 이후인 것만 수집
                if self.last_notified_trade_time and t['time'] <= self.last_notified_trade_time:
                    break
                new_trades.append(t)
            
            if new_trades:
                # 오래된 거래부터 순차 전송
                for t in reversed(new_trades):
                    self.notifier.notify_trade(
                        t['type'], t['code'], t['name'], t['price'], t['qty'], 
                        t.get('memo', ''), t.get('profit', 0), t.get('model_id', '')
                    )
                # 마지막 알림 시각 갱신
                self.last_notified_trade_time = trades[0]['time']

    def add_log(self, msg):
        self.last_log_msg = f"\033[96m[LOG] {msg}\033[0m"
        self.last_log_time = time.time()

    def add_trading_log(self, msg):
        t_str = datetime.now().strftime('%H:%M:%S')
        self.trading_logs.append(f"\033[95m[TRADING] [{t_str}] {msg}\033[0m")
        if len(self.trading_logs) > 10:
            self.trading_logs.pop(0)
        # JSON 로그 시스템(TradingLogManager)에도 CONFIG 타입으로 영구 저장
        trading_log.log_config(msg)

    def shutdown(self, reason="사용자 종료"):
        """시스템 종료를 수행하고 알림을 보냅니다."""
        self.notifier.notify_alert("시스템 종료", f"🛑 트레이딩 엔진이 종료되었습니다. (사유: {reason})")
        self.is_running = False
        time.sleep(1) # 알림 전송 대기

    def update_all_data(self, is_virtual, force=False, lite=False):
        """전체 데이터를 동기화합니다. lite=True일 경우 지수/랭킹 수집을 건너뛰고 잔고와 보유종목 시세만 빠르게 갱신합니다."""
        self.set_busy("데이터 동기화" + (" (LITE)" if lite else ""))
        try:
            curr_t = time.time()
            
            # 1. 자산/잔고 패치 (가장 먼저 시작하여 UI 즉시 노출 유도)
            h, a = self.api.get_full_balance(force=True)
            self._update_daily_metrics(a)
            with self.data_lock:
                self.cached_holdings = h
                self.cached_asset = a
                self.worker_results["ASSET"] = "성공"
                self.worker_last_tasks["ASSET"] = "잔고 및 자산 수집"
            self.last_times["asset"] = curr_t

            if not lite:
                # 2. 시장 트렌드 및 지수 패치
                try:
                    self.strategy.determine_market_trend()
                    with self.data_lock:
                        self.cached_market_data = self.strategy.current_market_data
                        self.cached_vibe = self.strategy.current_market_vibe
                        self.cached_panic = self.strategy.global_panic
                    self.last_times["index"] = curr_t
                except: pass

                # 3. 인기/랭킹 종목
                try:
                    h_raw = self.api.get_naver_hot_stocks()
                    v_raw = self.api.get_naver_volume_stocks()
                    self.cached_hot_raw = h_raw; self.cached_vol_raw = v_raw
                    analyze_popular_themes(h_raw, v_raw)
                    self.last_times["ranking"] = curr_t
                except: pass

            # 4. 보유 종목 + 당일 매매 종목 전체에 대해 상세 정보 및 MA 수집 (병렬화)
            today_codes = set()
            with trading_log.lock:
                today_str = datetime.now().strftime('%Y-%m-%d')
                for t in trading_log.data.get("trades", []):
                    if t["time"].startswith(today_str):
                        today_codes.add(t["code"])
            
            all_relevant_codes = list(set([stock.get('pdno') for stock in h]) | today_codes)
            
            # [핵심 개선] 네이버 벌크 API를 사용하여 모든 종목의 시세를 한 번에 가져옴
            bulk_data = self.api.get_naver_stocks_realtime(all_relevant_codes)
            temp_stock_info = {}

            def fetch_single_stock_info(code):
                n_data = bulk_data.get(code)
                p_data = None
                if force or code not in self.cached_stock_info:
                    p_data = self.api.get_inquire_price(code)
                
                if n_data:
                    curr_p, day_rate, day_val = n_data['price'], n_data['rate'], n_data['cv']
                    p_data_fallback = {
                        "price": curr_p, "vrss": day_val, "ctrt": day_rate,
                        "vol": n_data['aq'], "high": n_data['hv'], "low": n_data['lv'],
                        "prev_vol": p_data.get("prev_vol", 0) if p_data else self.cached_stock_info.get(code, {}).get("prev_vol", 0)
                    }
                    tp, sl, spike = self.strategy.get_dynamic_thresholds(code, self.cached_vibe.lower(), p_data_fallback)
                    p_vol = p_data_fallback["prev_vol"]
                else:
                    tp, sl, spike = self.strategy.get_dynamic_thresholds(code, self.cached_vibe.lower(), p_data)
                    curr_p = p_data.get('price', 0) if p_data else 0
                    day_val = p_data.get('vrss', 0) if p_data else 0
                    day_rate = p_data.get('ctrt', 0) if p_data else 0
                    p_vol = p_data.get('prev_vol', 0) if p_data else 0
                
                ma_20 = self.ma_20_cache.get(code, 0.0)
                if (ma_20 == 0 or force) and not lite: # lite 모드에서는 MA 수집 스킵
                    try:
                        m_candles = self.api.get_minute_chart_price(code)
                        if m_candles:
                            closes = [float(str(c.get('stck_prpr') or c.get('stck_clpr')).strip()) for c in m_candles if (c.get('stck_prpr') or c.get('stck_clpr'))]
                            ma_vals = self.strategy.indicator_eng.calculate_sma(closes, [20])
                            ma_20 = ma_vals.get("sma_20", 0.0)
                    except: pass

                return code, {
                    "tp": tp, "sl": sl, "spike": spike,
                    "day_val": day_val, "day_rate": day_rate,
                    "ma_20": ma_20, "price": curr_p, "prev_vol": p_vol
                }, ma_20

            # [병렬화 실행] 개별 종목 정보 수집
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                future_to_code = {executor.submit(fetch_single_stock_info, c): c for c in all_relevant_codes}
                for future in concurrent.futures.as_completed(future_to_code):
                    code, info, ma = future.result()
                    temp_stock_info[code] = info
                    if ma > 0: self.ma_20_cache[code] = ma

            with self.data_lock:
                self.cached_stock_info.update(temp_stock_info)
                self.last_update_time = datetime.now().strftime('%H:%M:%S')

            self.add_log(f"데이터 동기화 완료" + (" (LITE)" if lite else ""))
            return True
        except Exception as e:
            log_error(f"Update Error: {e}")
            return False
        finally:
            self.clear_busy()

    # --- 데이터 업데이트 스레드 (지수 및 네이버 랭킹 전담: Naver/Yahoo) ---
    def index_update_worker(self):
        while self.is_running:
            curr_t = time.time()

            # 1) 시장 트렌드 분석 (실패해도 나머지 진행)
            try:
                self.set_busy("시장분석", "INDEX")
                self.strategy.determine_market_trend()
                with self.data_lock:
                    self.cached_market_data = self.strategy.current_market_data
                    self.cached_vibe = self.strategy.current_market_vibe
                    self.cached_panic = self.strategy.global_panic
                    self.cached_dema_info = getattr(self.strategy.analyzer, 'dema_info', {})
                    self.market_info_status = "정상"
                    self.worker_results["INDEX"] = "성공"
                    self.worker_last_tasks["INDEX"] = "시장 지수 및 VIBE 분석"
                self.last_times["index"] = curr_t
                kospi_info = self.cached_market_data.get("KOSPI")
                self.is_kr_market_active = kospi_info.get("status") == "02" if (kospi_info and "status" in kospi_info) else is_market_open()
            except RuntimeError: break # 종료 시 즉시 중단
            except Exception as e:
                log_error(f"Market Trend Update Error: {e}")
                with self.data_lock:
                    self.market_info_status = "실패"
                    self.worker_results["INDEX"] = "실패"
                
            # [추가] VIBE 변화 및 장 개시 알림
            with self.data_lock:
                curr_vibe = self.cached_vibe
                curr_time_str = datetime.now().strftime('%H:%M')
                today_str = datetime.now().strftime('%Y-%m-%d')
                
                # 1. VIBE 변화 알림
                if curr_vibe != self.last_notified_vibe:
                    self.notifier.notify_alert("시장 VIBE 변화", f"🔄 `{self.last_notified_vibe}` → `{curr_vibe}`")
                    self.last_notified_vibe = curr_vibe
                
                # 2. 장 개시 알림 (09:00 ~ 09:05 사이 1회)
                if "09:00" <= curr_time_str <= "09:05" and self.notified_dates["market_start"] != today_str:
                    if self.is_kr_market_active:
                        self.notifier.notify_market_start(curr_vibe)
                        self.notified_dates["market_start"] = today_str

            # 2) 네이버 인기/거래량 종목 수집 (실패해도 나머지 진행)
            try:
                self.set_busy("종목 수집", "INDEX")
                h_raw = self.api.get_naver_hot_stocks()
                v_raw = self.api.get_naver_volume_stocks()
                themes = analyze_popular_themes(h_raw, v_raw)
                
                # [개선] 인기/거래량 종목에서 수집된 시세를 전역 캐시(cached_stock_info)에 즉시 공유
                # 이로 인해 보유 종목 중 인기 종목에 포함된 경우 별도 API 호출 없이도 즉시 가격이 업데이트됨
                shared_info = {}
                for item in h_raw + v_raw:
                    code = item.get('code')
                    if code:
                        price = float(str(item.get('price', 0)).replace(',', ''))
                        rate = float(item.get('rate', 0.0))
                        prev_close = price / (1 + rate / 100) if rate != -100 else price
                        cv = price - prev_close
                        
                        shared_info[code] = {
                            "price": price,
                            "day_rate": rate,
                            "day_val": cv,
                            "name": item.get('name', code)
                        }
                
                with self.data_lock:
                    self.cached_hot_raw = h_raw
                    self.cached_vol_raw = v_raw
                    
                    # 기존 캐시에 병합 (기존 TP/SL 등은 유지하면서 가격 정보만 업데이트)
                    for c, info in shared_info.items():
                        if c in self.cached_stock_info:
                            self.cached_stock_info[c].update(info)
                        else:
                            # 신규 종목의 경우 기본 구조로 생성 (나중에 상세 분석에서 채워짐)
                            base = {"tp": 0, "sl": 0, "spike": False, "ma_20": 0, "prev_vol": 0, "day_val": 0, "day_rate": 0, "price": 0}
                            base.update(info)
                            self.cached_stock_info[c] = base
                            
                    self.worker_results["RANKING"] = "성공"
                    self.worker_last_tasks["RANKING"] = "실시간 인기/거래량 종목 수집"
                self.last_times["ranking"] = curr_t
            except RuntimeError: break
            except Exception as e:
                log_error(f"Hot/Vol Ranking Update Error: {e}")
                h_raw, v_raw, themes = self.cached_hot_raw, self.cached_vol_raw, []

            # 3) AI 추천 갱신 (실패해도 루프 계속)
            try:
                # [추가] AI 실행 가능 시간 체크 (디버그 모드 제외)
                if is_ai_enabled_time() or getattr(self.strategy, "debug_mode", False):
                    def rec_prog_cb(c, t, msg=""):
                        self.set_busy(f"AI분석({c}/{t})", "INDEX")
                    self.strategy.update_ai_recommendations(themes, h_raw, v_raw, progress_cb=rec_prog_cb)
                else:
                    # [수정] 장 마감 후 자동 갱신은 하지 않지만, 수동 분석 결과('8:시황')가 지워지는 것을 방지하기 위해 
                    # ai_recommendations = [] 초기화 로직을 제거함 (깜빡임 문제 해결)
                    pass
                
                self.strategy.refresh_yesterday_recs_performance(h_raw, v_raw)
                
                # 4) AI 비용 갱신 (5초 주기)
                if curr_t - self.last_times.get("billing", 0) > 5:
                    try:
                        costs = self.strategy.get_ai_costs()
                        with self.data_lock:
                            self.cached_ai_costs = costs
                            self.worker_results["BILLING"] = "성공"
                            self.worker_last_tasks["BILLING"] = "AI API 사용료 집계"
                        self.last_times["billing"] = curr_t
                    except Exception as e:
                        log_error(f"Billing Update Error: {e}")
            except RuntimeError: break
            except Exception as e:
                log_error(f"AI Rec Update Error: {e}")
            finally:
                self.clear_busy("INDEX")

            time.sleep(5)

    def _update_market_data(self):
        self.strategy.determine_market_trend()
        with self.data_lock:
            self.cached_vibe = self.strategy.current_market_vibe
            self.cached_market_data = self.strategy.current_market_data
            self.cached_panic = self.strategy.global_panic

    def _update_featured_chart(self):
        """대시보드에 표시할 상위 종목의 차트 데이터를 업데이트합니다."""
        target_h = self.cached_holdings[0] if self.cached_holdings else None
        if not target_h: 
            with self.data_lock: self.cached_chart_data = {"code": "", "name": "", "candles": []}
            return
            
        code, name = target_h['pdno'], target_h['prdt_name']
        # 이미 최신 데이터를 가지고 있다면 스킵 (5분 캐시 정책 따름)
        if self.cached_chart_data["code"] == code and self.cached_chart_data.get("time", 0) > time.time() - 60:
            return
            
        candles = self.api.get_minute_chart_price(code)
        if candles:
            with self.data_lock:
                self.cached_chart_data = {
                    "code": code,
                    "name": name,
                    "candles": candles,
                    "time": time.time()
                }

    # --- 데이터 동기화 워커 (KIS API: 잔고/시세 수집 전용) ---
    def data_sync_worker(self, is_virtual):
        import math
        self.update_all_data(is_virtual, force=True)
        
        # [추가] 프로그램을 켜자마자 TP/SL로 매도되지 않도록 최초 AI/시황 분석 시도를 대기함 (최대 15초)
        start_wait = time.time()
        while not getattr(self.strategy, "first_analysis_attempted", False) and time.time() - start_wait < 15:
            self.set_busy(f"초기 분석 대기 ({int(time.time()-start_wait)}s)", "DATA")
            time.sleep(1)
        self.clear_busy("DATA")

        last_lite_sync = 0
        last_heavy_sync = 0

        while self.is_running:
            try:
                # [핵심 개선] 큐 대기 방식 도입 (최대 3초 대기하며 즉각적 반응성 확보)
                try:
                    req_type = self._sync_queue.get(timeout=3.0)
                except queue.Empty:
                    req_type = "AUTO"

                curr_t = time.time()
                # [유저 요청] 1초 스로틀링: 너무 빈번한 API 호출 방지
                if curr_t - last_lite_sync < 1.0:
                    continue

                self.set_busy("잔고 동기화", "DATA")
                h, a = self.api.get_full_balance(force=True)

                if h or a.get('total_asset', 0) > 0:
                    # 1. 락 밖에서 필요한 데이터 미리 수집 (병렬화)
                    recent_codes = set()
                    with trading_log.lock:
                        now_dt = datetime.now()
                        for t in trading_log.data.get("trades", []):
                            try:
                                # 최근 10분 이내 거래된 종목만 모니터링 유지 (매도 후 잔상 표시 및 동기화 보장용)
                                t_dt = datetime.strptime(t["time"], '%Y-%m-%d %H:%M:%S')
                                if (now_dt - t_dt).total_seconds() < 600: # 10분
                                    recent_codes.add(t["code"])
                                else:
                                    # trading_log는 최신순이므로 10분을 넘어가면 중단 가능
                                    break
                            except: continue
                    
                    all_relevant_codes = list(set([stock.get('pdno') for stock in h]) | recent_codes)
                    bulk_data = self.api.get_naver_stocks_realtime(all_relevant_codes)
                    temp_stock_info = {}

                    def fetch_stock_task(code):
                        n_data = bulk_data.get(code)
                        task_id = f"STOCK_{code}"
                        
                        # 종목명 찾기 및 캐시 업데이트
                        s_name = next((s.get('prdt_name') for s in h if s.get('pdno')==code), code)
                        if s_name == code: s_name = self.cached_stock_info.get(code, {}).get('name', code)
                        if s_name == code and n_data: s_name = n_data.get('name', code)
                        
                        # 상세 데이터 수집 (60초 주기 또는 강제 동기화 시)
                        is_heavy_cycle = (curr_t - last_heavy_sync > 60)
                        p_data = None
                        if is_heavy_cycle or code not in self.cached_stock_info:
                            p_data = self.api.get_inquire_price(code)
                            with self.data_lock: 
                                self.worker_results[task_id] = "성공" if p_data else "실패"
                                self.worker_last_tasks[task_id] = "실시간 시세 및 지표 수집"
                        
                        if n_data:
                            curr_p, day_rate, day_val = n_data['price'], n_data['rate'], n_data['cv']
                            old_info = self.cached_stock_info.get(code, {})
                            p_data_fallback = {
                                "price": curr_p, "vrss": day_val, "ctrt": day_rate,
                                "vol": n_data['aq'], "high": n_data['hv'], "low": n_data['lv'],
                                "prev_vol": p_data.get("prev_vol", 0) if p_data else old_info.get("prev_vol", 0)
                            }
                            tp, sl, spike = self.strategy.get_dynamic_thresholds(code, self.cached_vibe.lower(), p_data_fallback)
                            p_vol = p_data_fallback["prev_vol"]
                        else:
                            if not p_data: p_data = self.api.get_inquire_price(code)
                            tp, sl, spike = self.strategy.get_dynamic_thresholds(code, self.cached_vibe.lower(), p_data)
                            curr_p = p_data.get('price', 0) if p_data else 0
                            day_val = p_data.get('vrss', 0) if p_data else 0
                            day_rate = p_data.get('ctrt', 0) if p_data else 0
                            p_vol = p_data.get('prev_vol', 0) if p_data else 0
                        
                        ma_20 = self.ma_20_cache.get(code, 0.0)
                        if ma_20 == 0 or (curr_t - self.last_times.get(f"ma_{code}", 0) > 60):
                            try:
                                m_candles = self.api.get_minute_chart_price(code)
                                if m_candles:
                                    closes = [float(str(c.get('stck_prpr') or c.get('stck_clpr')).strip()) for c in m_candles if (c.get('stck_prpr') or c.get('stck_clpr'))]
                                    ma_vals = self.strategy.indicator_eng.calculate_sma(closes, [20])
                                    ma_20 = ma_vals.get("sma_20", 0.0)
                            except: pass
                        
                        return code, {
                            "tp": tp, "sl": sl, "spike": spike, "day_val": day_val, "day_rate": day_rate,
                            "ma_20": ma_20, "price": curr_p, "prev_vol": p_vol, "name": s_name
                        }, task_id, ma_20

                    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                        futures = [executor.submit(fetch_stock_task, c) for c in all_relevant_codes]
                        for f in concurrent.futures.as_completed(futures):
                            c, info, tid, ma = f.result()
                            temp_stock_info[c] = info
                            if info.get('name'):
                                with self.data_lock:
                                    if c not in self.cached_stock_info: self.cached_stock_info[c] = {}
                                    self.cached_stock_info[c]['name'] = info['name']
                                    # [수정] TUI 모니터링 화면용 표시 이름 등록
                                    self.worker_names[tid] = f"{c}_{info['name']}"
                            if ma > 0: 
                                self.ma_20_cache[c] = ma
                                self.last_times[f"ma_{c}"] = curr_t
                            if curr_t - self.last_times.get(tid.lower(), 0) > 60:
                                self.last_times[tid.lower()] = curr_t

                    # 2. 락 안에서는 캐시 업데이트만 수행
                    self._update_daily_metrics(a)
                    with self.data_lock:
                        self.cached_holdings = h
                        self.cached_asset = a
                        self.cached_holdings_fetched = True # [추가] 데이터 준비 완료
                        if a.get('total_asset', 0) > 0:
                            self.strategy.last_known_asset = float(a['total_asset'])
                        self.cached_stock_info.update(temp_stock_info)
                    
                    self.last_times["asset"] = curr_t
                    last_lite_sync = curr_t
                    if curr_t - last_heavy_sync > 60:
                        last_heavy_sync = curr_t
                        
                    self.worker_results["DATA"] = "성공"
                    self.worker_last_tasks["DATA"] = "전체 잔고 데이터 동기화 완료"
                    self.clear_busy("DATA")

                    # [추가] 유효하지 않은(보유/당일매매 아님) 종목의 작업 데이터 정리
                    with self.data_lock:
                        stale_keys = []
                        for k in self.last_times.keys():
                            if k.startswith("stock_"):
                                code = k.replace("stock_", "")
                                if code not in all_relevant_codes:
                                    stale_keys.append(k)
                        
                        for k in stale_keys:
                            self.last_times.pop(k, None)
                            self.worker_names.pop(k.upper(), None)
                            self.worker_results.pop(k.upper(), None)
                            self.worker_last_tasks.pop(k.upper(), None)
                            code_only = k.replace("stock_", "")
                            self.ma_20_cache.pop(code_only, None)
                            self.last_times.pop(f"slow_{code_only}", None) # 구버전 호환용 키 삭제
                            self.last_times.pop(f"ma_{code_only}", None)
            except Exception as e:
                log_error(f"Data Sync Worker Error: {e}")
                self.worker_results["DATA"] = "실패"
            finally:
                self.clear_busy("DATA")

    # --- 매매 집행 워커 (전략 실행 전용) ---
    def trading_worker(self, is_virtual):
        import math
        while self.is_running:
            try:
                # 전략 엔진 및 기본 데이터 수집 확인
                if not hasattr(self.strategy, 'analyzer') or not self.cached_holdings_fetched:
                    time.sleep(2)
                    continue

                curr_t = time.time()
                vibe = self.cached_vibe
                a = self.cached_asset
                h = self.cached_holdings
                
                # 1. AI 추천 및 성과 트래킹 갱신 (5분 주기)
                if curr_t - self.last_times.get("recommendation", 0) > 300:
                    self.set_busy("AI 추천 갱신", "TRADE")
                    self.cached_recommendations = self.strategy.get_buy_recommendations(market_trend=vibe.lower())
                    self.last_times["recommendation"] = curr_t
                    self.clear_busy("TRADE")

                # 2. 매매 사이클 실행 (장중)
                if self.is_kr_market_active and not self.cached_panic:
                    self.set_busy("매매 사이클", "TRADE")
                    try:
                        # (A) 기본 매매 엔진 실행 (TP/SL 등)
                        auto_res = self.strategy.run_cycle(
                            market_trend=vibe.lower(), 
                            skip_trade=False,
                            holdings=h,
                            asset_info=a
                        )
                        if auto_res:
                            for r in auto_res: self.add_trading_log(f"🤖 자동: {r}")
                            self.add_log("🔄 매매 발생: 즉시 동기화 요청")
                            self._sync_queue.put("LITE")
                        
                        # (B) 서킷 브레이커 감시 및 알림
                        if self.strategy.risk_mgr.is_halted:
                            if not self.last_notified_halted:
                                self.notifier.notify_alert("서킷 브레이커 발동", "🚨 계좌 손실 임계치 도달로 인해 모든 자동 매수가 중단되었습니다.", is_critical=True)
                                self.last_notified_halted = True
                        elif self.last_notified_halted:
                            self.notifier.notify_alert("서킷 브레이커 해제", "✅ 리스크가 완화되어 자동 매수가 다시 활성화되었습니다.")
                            self.last_notified_halted = False
                        
                        # (C) 장 마감 알림 (15:30)
                        today_str = datetime.now().strftime('%Y-%m-%d')
                        curr_time_str = datetime.now().strftime('%H:%M')
                        if "15:30" <= curr_time_str <= "15:35" and self.notified_dates.get("market_end") != today_str:
                            self.notifier.notify_market_end(a)
                            self.notified_dates["market_end"] = today_str
                        
                        # (D) 물타기/불타기 및 AI 자율 매수 실행
                        # (모든 매매 로직은 run_cycle 내에서 통합 처리됨)
                        
                        self.worker_results["TRADE"] = "성공"
                        self.worker_last_tasks["TRADE"] = "매매 사이클 실행 완료"
                    finally:
                        self.clear_busy("TRADE")
                    
                    self.notify_latest_trades()
                else:
                    self.worker_results["TRADE"] = "대기 (장외)"

            except Exception as e:
                log_error(f"Trading Worker Error: {e}")
                self.worker_results["TRADE"] = "실패"
            finally:
                self.clear_busy("TRADE")
            
            time.sleep(5)



    def theme_update_worker(self):
        """테마 데이터를 주기적으로 크롤링하여 파일로 저장 (Naver Finance)"""
        while self.is_running:
            try:
                from src.theme_engine import save_theme_data
                self.set_busy("테마 데이터 수집", "THEME")
                theme_map = self.api.get_naver_theme_data()
                if theme_map:
                    save_theme_data(theme_map)
                    self.add_trading_log("✨ 테마 데이터베이스 갱신 완료")
            except Exception as e:
                try:
                    log_error(f"Theme Update Error: {e}")
                except: pass
            finally:
                with self.data_lock:
                    self.worker_results["THEME"] = "성공"
                self.clear_busy("THEME")
            
            # 테마 데이터는 6시간마다 갱신
            time.sleep(6 * 3600)

    def log_cleanup_worker(self):
        """로그 파일을 주기적으로 정리 (1시간 주기, 영업일 기준 2일치 유지)"""
        while self.is_running:
            try:
                self.set_busy("로그 정리 중", "CLEANUP")
                self.add_log("로그 파일 정리를 시작합니다...")
                
                # 1. trading_logs.json 정리
                j_cleaned = trading_log.cleanup(days_to_keep=2)
                
                # 2. error.log 정리
                e_cleaned = cleanup_text_log("error.log", days_to_keep=2)
                
                # 3. trading.log 정리
                t_cleaned = cleanup_text_log("trading.log", days_to_keep=2)
                
                # 4. telegram.log 정리
                tel_cleaned = cleanup_text_log("telegram.log", days_to_keep=2)
                
                if j_cleaned or e_cleaned or t_cleaned or tel_cleaned:
                    self.add_log("오래된 로그 파일 정리를 완료했습니다.")
                else:
                    self.add_log("로그 파일이 이미 최신 상태입니다.")
                
                with self.data_lock:
                    self.worker_results["CLEANUP"] = "성공"
                    
            except Exception as e:
                log_error(f"Log Cleanup Worker Error: {e}")
            finally:
                self.clear_busy("CLEANUP")
            
            # 1시간 대기
            time.sleep(3600)

    def retrospective_worker(self):
        """투자 적중 복기 워커 (장 마감 후 30분 주기)
        - 매일 16:00 이후 당일 복기 리포트 자동 생성
        - 이미 생성된 경우 30분마다 사후 분석 업데이트
        - 주말/공휴일에는 실행하지 않음
        """
        from datetime import time as dtime
        
        while self.is_running:
            try:
                now = datetime.now()
                
                # 주말 제외
                if now.weekday() >= 5:
                    time.sleep(1800)
                    continue
                
                # 16:00 이전이면 대기
                if now.time() < dtime(16, 0):
                    time.sleep(60)
                    continue
                
                # 22:00 이후에는 더 이상 분석하지 않음 (야간 API 절약)
                if now.time() > dtime(22, 0):
                    time.sleep(1800)
                    continue
                
                retro = getattr(self.strategy, 'retrospective', None)
                if not retro:
                    time.sleep(1800)
                    continue
                
                today_str = now.strftime('%Y-%m-%d')
                vibe = self.cached_vibe or "Neutral"
                
                if not retro.has_daily_report(today_str):
                    # 당일 리포트 최초 생성
                    self.set_busy("복기 리포트 생성", "RETRO")
                    self.add_log("📝 당일 투자 적중 복기 분석을 시작합니다...")
                    report = retro.generate_daily_report(today_str, vibe)
                    if report:
                        self.add_trading_log("📊 투자 적중 복기 리포트가 생성되었습니다 (P:성과 → 4번 탭)")
                        self.add_log("✅ 투자 적중 복기 리포트 생성 완료")
                        
                        # [추가] 텔레그램 리포트 전송
                        summary = report.get("ai_analysis", {}).get("overall_lesson", "당일 매매 복기가 완료되었습니다.")
                        self.notifier.notify_alert("📊 투자 적중 복기 리포트", summary)
                    else:
                        self.add_log("ℹ️ 당일 매매 기록이 없어 복기 리포트를 생성하지 않았습니다")
                else:
                    # 기존 리포트 사후 분석 업데이트 (최대 3회까지만)
                    existing = retro.get_report(today_str)
                    if existing and existing.get("update_count", 1) < 4:
                        self.set_busy("복기 사후분석", "RETRO")
                        self.add_log("🔄 투자 적중 사후 분석을 업데이트합니다...")
                        retro.update_post_market_analysis(today_str, vibe)
                        self.add_log(f"✅ 투자 적중 사후 분석 업데이트 완료 ({existing.get('update_count', 1)+1}회차)")
                
            except Exception as e:
                log_error(f"Retrospective Worker Error: {e}")
            finally:
                with self.data_lock:
                    self.worker_results["RETRO"] = "성공"
                self.clear_busy("RETRO")
            
            # 30분 대기
            time.sleep(1800)

    def updater_worker(self):
        """업데이트 체크 워커 (1시간 주기)"""
        current_ver = ""
        try:
            with open("VERSION", "r") as f:
                current_ver = f.read().strip()
        except: return

        while self.is_running:
            try:
                self.set_busy("최신 버전 확인 중", "UPDATE")
                from src.updater import check_for_updates
                res = check_for_updates(current_ver)
                if res.get("has_update"):
                    with self.data_lock:
                        is_already_notified = self.update_info.get("has_update")
                        self.update_info.update({
                            "has_update": True,
                            "latest_version": res["latest_version"],
                            "download_url": res["download_url"]
                        })
                    
                    if not is_already_notified:
                        self.notifier.notify_alert("신규 업데이트 발견", f"🆕 신규 버전 `v{res['latest_version']}`이 릴리스되었습니다.\n단축키 `U`를 눌러 업데이트를 진행하세요.")
                    self.add_log(f"🚀 새로운 버전 v{res['latest_version']}이(가) 출시되었습니다! (U 키를 눌러 업데이트)")
                
                with self.data_lock:
                    self.last_times['update'] = time.time()
                    self.worker_results["UPDATE"] = "성공"
            except Exception as e:
                try: log_error(f"Updater Worker Error: {e}")
                except: pass
            finally:
                self.clear_busy("UPDATE")
            
            # 1시간 대기 (장중에는 1시간마다 체크)
            time.sleep(3600)

    def telegram_status_worker(self):
        """30분 단위 정기 상태 보고 워커"""
        # 시작 후 첫 보고까지 약간의 여유(30초)를 두어 데이터가 충분히 쌓이게 함
        time.sleep(30)
        from datetime import time as dtime
        
        while self.is_running:
            try:
                # 1. 설정 확인 (전략 엔진의 설정값 참조)
                config_enabled = getattr(self.strategy, 'config', {}).get('vibe_strategy', {}).get('telegram_report_enabled', True)
                if not config_enabled:
                    time.sleep(600) # 10분 후 재확인
                    continue

                now = datetime.now()
                # 2. 장 운영 시간 제한 (09:00 ~ 15:30)
                market_start = dtime(9, 0)
                market_end = dtime(15, 30)
                is_market_time = market_start <= now.time() <= market_end
                
                # 주말 제외
                if now.weekday() >= 5:
                    time.sleep(3600)
                    continue

                if not is_market_time:
                    # 장외 시간에는 루프 주기를 짧게 가져가며 대기 (장 시작 전후 체크 위함)
                    time.sleep(300)
                    continue
                
                with self.data_lock:
                    vibe = self.cached_vibe
                    asset = self.cached_asset
                    holdings = self.cached_holdings
                    last_time = self.last_update_time or now.strftime('%H:%M:%S')

                # 자산 정보가 있는 경우에만 보고
                if asset.get('total_asset', 0) > 0:
                    vibe_emoji = "🟢" if "BULL" in vibe.upper() else "🔴" if "BEAR" in vibe.upper() else "🟡" if "NEUTRAL" in vibe.upper() else "⚪"
                    
                    # notify_alert가 내부적으로 제목과 구분선을 추가하므로 본문만 구성
                    msg = f"• *장세:* {vibe_emoji} {vibe}\n"
                    msg += f"• *자산:* {asset['total_asset']:,.0f}원\n"
                    msg += f"• *수익금 (수익률):* {int(asset.get('daily_pnl_amt', 0)):+,}원 ({abs(asset.get('daily_pnl_rate', 0.0)):.2f}%)\n"
                    
                    if holdings:
                        msg += f"• *보유 종목 ({len(holdings)}개):*\n"
                        # 수익률 기준 내림차순 정렬하여 전체 종목 표시
                        sorted_h = sorted(holdings, key=lambda x: float(x.get('evlu_pfls_rt', 0)), reverse=True)
                        for h in sorted_h:
                            rt = float(h.get('evlu_pfls_rt', 0))
                            qty = int(float(h.get('hldg_qty', 0)))
                            price = float(h.get('prpr', 0))
                            pnl = (price - float(h.get('pchs_avg_pric', 0))) * qty
                            msg += f"  - {h['prdt_name']}: `{int(pnl):+,}원 ({abs(rt):.2f}%)` ({qty}주, {price:,.0f}원)\n"
                    else:
                        msg += f"• *보유 종목:* 없음\n"
                    
                    self.notifier.notify_alert(f"정기 상태 보고 ({last_time})", msg)
                
            except Exception as e:
                log_error(f"Telegram Status Worker Error: {e}")
            
            # 30분 대기 (1800초)
            time.sleep(1800)

    def start_workers(self, is_virtual):
        threading.Thread(target=self.index_update_worker, daemon=True).start()
        threading.Thread(target=self.data_sync_worker, args=(is_virtual,), daemon=True).start()
        threading.Thread(target=self.trading_worker, args=(is_virtual,), daemon=True).start()
        threading.Thread(target=self.theme_update_worker, daemon=True).start()
        threading.Thread(target=self.log_cleanup_worker, daemon=True).start()
        threading.Thread(target=self.retrospective_worker, daemon=True).start()
        threading.Thread(target=self.updater_worker, daemon=True).start()
        threading.Thread(target=self.telegram_status_worker, daemon=True).start()
