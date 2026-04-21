import threading
import time
import concurrent.futures
from datetime import datetime
from src.utils import is_market_open, is_ai_enabled_time
from src.theme_engine import analyze_popular_themes
from src.logger import log_error, log_trade, trading_log, cleanup_text_log

class DataManager:
    def __init__(self, api, strategy):
        self.api = api
        self.strategy = strategy
        self.is_running = True # [추가] 실행 상태 플래그
        
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
        self.last_update_time = ""
        self.ranking_filter = "ALL"
        self.is_kr_market_active = False
        self.last_size = (0, 0)
        
        # --- 입력 상태 관리 (Task 4) ---
        self.is_input_active = False
        self.input_prompt = ""
        self.input_buffer = ""
        self.is_full_screen_active = False
        
        # --- 글로벌 진행 표시기 상태 ---
        self._worker_statuses = {} # {worker_name: status_msg}
        self._global_busy_msg = None
        self.busy_anim_step = 0
        
        self.data_lock = threading.Lock()
        self.ui_lock = threading.Lock()
        
        # 개별 갱신 시각 관리
        self.last_times = {"index": 0, "asset": 0, "ranking": 0}

    def set_busy(self, msg, worker="GLOBAL"):
        with self.data_lock:
            self._worker_statuses[worker] = msg

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
            
            res = " | ".join(statuses)
            # 공간 확보를 위해 축약 제한 완화 (35 -> 60)
            if len(res) > 60:
                res = res[:57] + "..."
            return res

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
        # 기준점이 없거나 날짜가 변경된 경우에만 기준 자산 설정
        if self.strategy.start_day_asset == 0 or self.strategy.last_asset_date != today_str:
            self.strategy.start_day_asset = a['total_asset']
            self.strategy.last_asset_date = today_str
            self.strategy._save_all_states()
            self.add_log(f"📅 기준 자산 설정: {self.strategy.start_day_asset:,.0f}원")

        if self.strategy.start_day_asset > 0:
            a['daily_pnl_rate'] = (a['total_asset'] / self.strategy.start_day_asset - 1) * 100
            a['daily_pnl_amt'] = a['total_asset'] - self.strategy.start_day_asset
        else:
            a['daily_pnl_rate'] = 0.0
            a['daily_pnl_amt'] = 0.0


    def add_log(self, msg):
        self.last_log_msg = f"\033[96m[LOG] {msg}\033[0m"
        self.last_log_time = time.time()

    def add_trading_log(self, msg):
        t_str = datetime.now().strftime('%H:%M:%S')
        self.trading_logs.append(f"\033[95m[TRADING] [{t_str}] {msg}\033[0m")
        if len(self.trading_logs) > 10:
            self.trading_logs.pop(0)
        log_trade(msg)

    def update_all_data(self, is_virtual, force=False):
        self.set_busy("전체 데이터 동기화")
        try:
            curr_t = time.time()
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                # 1. 자산/잔고 패치 (가장 먼저 시작하여 UI 즉시 노출 유도)
                f_bal = executor.submit(self.api.get_full_balance, force=True)
                # 2. 시장 트렌드 및 지수 패치
                f_trend = executor.submit(self.strategy.determine_market_trend)
                # 3. 인기/랭킹 종목
                f_hot = executor.submit(self.api.get_naver_hot_stocks)
                f_vol = executor.submit(self.api.get_naver_volume_stocks)
                
                # [순차 적용] 자산 정보 수신 즉시 UI 반영
                h, a = f_bal.result()
                self._update_daily_metrics(a)
                with self.data_lock:
                    self.cached_holdings = h
                    self.cached_asset = a
                self.last_times["asset"] = curr_t
                
                # [순차 적용] 시장 트렌드 수신 즉시 반영
                f_trend.result()
                with self.data_lock:
                    self.cached_market_data = self.strategy.current_market_data
                    self.cached_vibe = self.strategy.current_market_vibe
                    self.cached_panic = self.strategy.global_panic
                self.last_times["index"] = curr_t
                
                # [순차 적용] 랭킹 정보 나중에 반영
                h_raw = f_hot.result(); v_raw = f_vol.result()
                self.cached_hot_raw = h_raw; self.cached_vol_raw = v_raw
                analyze_popular_themes(h_raw, v_raw)
                self.last_times["ranking"] = curr_t

                # 보유 종목 상세 정보 패치
                temp_stock_info = {}
                for stock in h:
                    code = stock.get('pdno')
                    p_data = self.api.get_inquire_price(code)
                    tp, sl, spike = self.strategy.get_dynamic_thresholds(code, self.cached_vibe.lower(), p_data)
                    temp_stock_info[code] = {
                        "tp": tp, "sl": sl, "spike": spike,
                        "day_val": p_data.get('vrss', 0) if p_data else 0,
                        "day_rate": p_data.get('ctrt', 0) if p_data else 0
                    }
                
                with self.data_lock:
                    self.cached_stock_info.update(temp_stock_info)

                self.last_update_time = datetime.now().strftime('%H:%M:%S')
                self.add_log("전체 데이터 동기화 완료")
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
                self.last_times["index"] = curr_t
                kospi_info = self.cached_market_data.get("KOSPI")
                self.is_kr_market_active = kospi_info.get("status") == "02" if (kospi_info and "status" in kospi_info) else is_market_open()
            except RuntimeError: break # 종료 시 즉시 중단
            except Exception as e:
                log_error(f"Market Trend Update Error: {e}")

            # 2) 네이버 인기/거래량 종목 수집 (실패해도 나머지 진행)
            try:
                self.set_busy("종목 수집", "INDEX")
                h_raw = self.api.get_naver_hot_stocks()
                v_raw = self.api.get_naver_volume_stocks()
                themes = analyze_popular_themes(h_raw, v_raw)
                with self.data_lock:
                    self.cached_hot_raw = h_raw
                    self.cached_vol_raw = v_raw
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
                    # 추천 정보 초기화 (장 마감 대응)
                    self.strategy.ai_recommendations = []
                
                self.strategy.refresh_yesterday_recs_performance(h_raw, v_raw)
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

    # --- 데이터 업데이트 스레드 (KIS API: 잔고/주문) ---
    def data_update_worker(self, is_virtual):
        import math
        self.update_all_data(is_virtual, force=True)
        
        while self.is_running:
            try:
                # [추가] 매매 선행 분석 대기
                if not self.strategy.is_ready:
                    time.sleep(2)
                    continue

                curr_t = time.time()
                self.set_busy("잔고 동기화", "DATA")
                h, a = self.api.get_full_balance(force=True)

                if h or a.get('total_asset', 0) > 0:
                    # 1. 락 밖에서 필요한 데이터 미리 수집 (API 호출 등)
                    temp_stock_info = {}
                    for stock in h:
                        code = stock.get('pdno')
                        p_data = self.api.get_inquire_price(code) # API 호출 (락 외부)
                        tp, sl, spike = self.strategy.get_dynamic_thresholds(code, self.cached_vibe.lower(), p_data)
                        
                        day_val = p_data.get('vrss', 0) if p_data else 0
                        day_rate = p_data.get('ctrt', 0) if p_data else 0
                        
                        temp_stock_info[code] = {
                            "tp": tp, "sl": sl, "spike": spike,
                            "day_val": day_val, "day_rate": day_rate
                        }

                    # 2. 락 안에서는 캐시 업데이트만 수행 (최소한의 시간 점유)
                    self._update_daily_metrics(a)
                    with self.data_lock:
                        self.cached_holdings = h
                        self.cached_asset = a
                        self.cached_stock_info.update(temp_stock_info)
                    
                    self.last_times["asset"] = curr_t
                    self.add_log(f"잔고 업데이트 완료 (Cash: {a['cash']:,}원)")
                    self.clear_busy("DATA")

                vibe = self.cached_vibe
                self.cached_recommendations = self.strategy.get_buy_recommendations(market_trend=vibe.lower())
                
                if self.is_kr_market_active and not self.cached_panic:
                    self.set_busy("매매 사이클", "DATA")
                    auto_res = self.strategy.run_cycle(market_trend=vibe.lower(), skip_trade=False)
                    if auto_res:
                        for r in auto_res: self.add_trading_log(f"🤖 자동: {r}")
                    
                    # 서킷 브레이커 작동 중이면 추가 매수 로직 스킵
                    if self.strategy.risk_mgr.is_halted:
                        time.sleep(5)
                        continue
                    
                    if self.strategy.bear_config.get("auto_mode", False) and self.cached_recommendations:
                        # --- 물타기/불타기 자동 매매 실행 (bear/bull auto_mode 독립 제어) ---
                        for rec in self.cached_recommendations:
                            rec_type = rec.get('type')
                            is_auto_enabled = False
                            if rec_type == "물타기" and self.strategy.bear_config.get("auto_mode", False):
                                is_auto_enabled = True
                            elif rec_type == "불타기" and self.strategy.bull_config.get("auto_mode", False):
                                is_auto_enabled = True

                            if not is_auto_enabled:
                                continue

                            code_r = rec['code']

                            # [핑퐁 방지] 익절/손절 후 2시간(7200초) 이내 자동 재진입 금지
                            _curr_t = time.time()
                            _last_sell_t = self.strategy.last_sell_times.get(code_r, 0)
                            _last_sl_t   = self.strategy.last_sl_times.get(code_r, 0)
                            _last_exit_t = max(_last_sell_t, _last_sl_t)
                            _COOLDOWN_BUY = 7200  # 2시간

                            if _curr_t - _last_exit_t < _COOLDOWN_BUY:
                                _rem_min = int((_COOLDOWN_BUY - (_curr_t - _last_exit_t)) / 60)
                                _exit_type = "익절" if _last_sell_t >= _last_sl_t else "손절"
                                self.add_log(f"🔒 재진입쿨다운({_exit_type}): {rec['name']} 잔여 {_rem_min}분")
                                self.add_trading_log(
                                    f"⏸ 스킵(재진입쿨다운/{_exit_type}후): {rec['name']}({code_r}) "
                                    f"{rec_type} 조건충족 / 잔여 {_rem_min}분"
                                )
                            else:
                                p = self.api.get_inquire_price(code_r)
                                if p and p.get('price'):
                                    # [Safety] 매수 가능 현금 확인 (D+2 기준이 아닌 D+0 기준 예수금으로 안전성 확보)
                                    available_cash = a.get('cash', 0)
                                    if available_cash < 1000: # 최소 1000원 이상은 있어야 시도
                                        self.add_log(f"⚠️ 현금 부족으로 {rec_type} 스킵: {int(available_cash):,}원")
                                        continue
                                        
                                    # 매수 희망액과 가용 현금 중 작은 금액으로 집행
                                    actual_invest_amt = min(rec['suggested_amt'], available_cash)
                                    qty = math.floor(actual_invest_amt / p['price'])
                                    
                                    if qty > 0:
                                        success, msg = self.api.order_market(code_r, qty, True)
                                        if success:
                                            m_id = self.strategy.ai_advisor.last_used_model_id if hasattr(self.strategy.ai_advisor, 'last_used_model_id') else ""
                                            trading_log.log_trade(f"자동{rec_type}", code_r, rec['name'], p['price'], qty, f"자동 {rec_type} 실행", model_id=m_id)
                                            msg_txt = f"자동{rec_type}: {rec['name']} {qty}주"
                                            self.strategy.last_avg_down_msg = f"[{datetime.now().strftime('%H:%M')}] {msg_txt}"
                                            self.strategy.record_buy(code_r, p['price'])
                                            self.add_trading_log(f"🤖 {msg_txt}")
                                            self.update_all_data(is_virtual, force=True)
                                            break  # 거래 후 데이터 동기화를 위해 루프 탈출
                                        else:
                                            self.add_log(f"{rec_type} 실패: {msg}")

                    if self.strategy.auto_ai_trade and self.strategy.ai_recommendations:
                        # [제약] Phase 3(CONCLUSION) 이후로는 신규 자율 매수 금지 (마무리 단계 집중)
                        # Phase 4의 '종가 베팅' 전용 로직만 허용하기 위함
                        phase = self.strategy.get_market_phase()
                        if phase['id'] in ['P1', 'P2']:
                            for top_ai in self.strategy.ai_recommendations:
                                # 1. 인버스 필터 (평시 장세에서 인버스 스킵)
                                if top_ai.get('is_inverse', False) and "defensive" not in vibe.lower() and "bear" not in vibe.lower():
                                    continue

                            # 2. 보유 현황 및 투자 한도 체크
                            holding_item = next((h for h in self.cached_holdings if h['pdno'] == top_ai['code']), None)
                            curr_eval = float(holding_item.get('evlu_amt', 0)) if holding_item else 0
                            
                            a_cfg = self.strategy.ai_config
                            trade_amt = a_cfg.get("amount_per_trade", 500000)
                            max_inv = a_cfg.get("max_investment_per_stock", 2000000)
                            
                            # (현재 평가금 + 매수 예정액)이 한도를 초과하면 다음 순위 종목으로
                            if curr_eval + (trade_amt * 0.95) > max_inv:
                                continue
                            
                            # [수정] 재진입 제한(Cooldown) 체크 - 익절/손절/청산 후 2시간 이내 재진입 금지
                            if self.strategy.is_reentry_restricted(top_ai['code']):
                                continue
                            
                            # [추가] 매수 쿨타임 체크 (10분) - 동일 종목 연속 매수 방지
                            last_buy_t = self.strategy.last_buy_times.get(top_ai['code'], 0)
                            if time.time() - last_buy_t < 600:
                                continue

                            # [추가] 이미 거절된 종목은 로깅 없이 즉시 스킵
                            if top_ai['code'] in self.strategy.rejected_stocks:
                                continue

                            # [추가] AI 실행 가능 시간 체크 (디버그 모드 제외)
                            if not is_ai_enabled_time() and not getattr(self.strategy, "debug_mode", False):
                                # P4 종가 베팅 로직은 execution.py 내부에서 phase 체크를 하므로 
                                # 여기서는 일반 자율 매수(P1, P2)만 차단함.
                                # 단, 사용자가 요청한 사항은 '자동 실행' 전체 차단이므로 로그를 남김
                                continue

                            # 3. AI 최종 매수 컨펌 (최초 거절 시에만 로깅됨)
                            is_confirmed, refuse_reason = self.strategy.confirm_buy_decision(top_ai['code'], top_ai['name'], score=top_ai.get('score', 0.0))
                            if not is_confirmed:
                                self.add_trading_log(f"⚠️ AI매수거절: {top_ai['name']} | 사유: {refuse_reason}")
                                continue

                            # [추가] 최대 종목 수(8종목) 제한 및 교체 로직
                            replacement_memo = "AI 추천 기반 자율 매수"
                            if len(self.cached_holdings) >= self.strategy.MAX_STOCK_COUNT:
                                self.set_busy("종목 교체 분석", "DATA")
                                should_replace, target_code, replace_reason = self.strategy.get_replacement_target(
                                    top_ai['code'], top_ai['name'], top_ai.get('score', 0.0), self.cached_holdings
                                )
                                self.clear_busy("DATA")
                                
                                if should_replace and target_code:
                                    target_item = next((h for h in self.cached_holdings if h['pdno'] == target_code), None)
                                    target_name = target_item['prdt_name'] if target_item else target_code
                                    
                                    # 1. 대상 종목 전량 매도
                                    sell_qty = int(float(target_item['hldg_qty'])) if target_item else 0
                                    if sell_qty > 0:
                                        self.add_trading_log(f"🔄 종목 교체 결정: [{target_name}] 매도 후 [{top_ai['name']}] 매수")
                                        self.add_trading_log(f"📝 교체 사유: {replace_reason}")
                                        
                                        # P성과 리포트 기록을 위한 수익금 계산
                                        s_price = float(target_item.get('prpr', 0))
                                        s_avg = float(target_item.get('pchs_avg_pric', 0))
                                        s_profit = (s_price - s_avg) * sell_qty
                                        
                                        s_success, s_msg = self.api.order_market(target_code, sell_qty, False)
                                        if s_success:
                                            # 전량 교체 매도 기록 (P성과 리포트 연동)
                                            m_id = self.strategy.last_buy_models.get(target_code, "")
                                            trading_log.log_trade("교체매도", target_code, target_name, s_price, sell_qty, f"종목 교체: {top_ai['name']}로 변경", profit=s_profit, model_id=m_id)
                                            self.strategy.record_sell(target_code) # 매도 시점 기록 (재진입 방지)
                                            
                                            # AI 로그 리포트 기록 (A 로그 연동)
                                            log_entry = {
                                                "time": datetime.now().strftime('%H:%M:%S'),
                                                "out_code": target_code,
                                                "out_name": target_name,
                                                "in_code": top_ai['code'],
                                                "in_name": top_ai['name'],
                                                "reason": replace_reason
                                            }
                                            self.strategy.replacement_logs.insert(0, log_entry)
                                            self.strategy.replacement_logs = self.strategy.replacement_logs[:10] # 최근 10건 유지
                                            self.strategy.save_manual_thresholds() # 영속 저장
                                            
                                            self.add_trading_log(f"✅ {target_name} {sell_qty}주 매도 완료 (교체 준비)")
                                            # 매도 후 잔고 갱신을 위해 잠시 대기 및 데이터 업데이트
                                            time.sleep(1)
                                            self.update_all_data(is_virtual, force=True)
                                            
                                            # 교체 매입 메모 설정을 위해 변수 세팅
                                            replacement_memo = f"종목 교체 매수 ({target_name} 대체)"
                                        else:
                                            self.add_log(f"❌ 교체 매도 실패: {s_msg}")
                                            continue
                                else:
                                    # 교체 대상이 없거나 거절된 경우
                                    # self.add_log(f"ℹ️ 보유 한도 초과(8종목) 및 교체 부적합: {top_ai['name']} 스킵")
                                    continue

                             # 4. 매매 실행
                            p = self.api.get_inquire_price(top_ai['code'])
                            if p and p.get('price'):
                                curr_p = p['price']
                                
                                # [Safety] AI 자율 매수 전 가용 현금 체크
                                available_cash = self.cached_asset.get('cash', 0)
                                if available_cash < trade_amt * 0.5: # 설정액의 절반도 없으면 스킵
                                    self.add_log(f"⚠️ 현금 부족으로 AI 매수 대기: {int(available_cash):,}원")
                                    continue

                                # [Phase 1] ATR 기반 지능형 포지션 사이징 적용
                                qty = self.strategy.risk_mgr.calculate_position_size(
                                    top_ai['code'], 
                                    self.cached_asset['total_asset'], 
                                    curr_p,
                                    default_amt=min(trade_amt, int(available_cash))
                                )
                                
                                if qty > 0:
                                    success, msg = self.api.order_market(top_ai['code'], qty, True)
                                    if success:
                                        m_id = self.strategy.ai_advisor.last_used_model_id if hasattr(self.strategy.ai_advisor, 'last_used_model_id') else ""
                                        trading_log.log_trade("AI자율매수", top_ai['code'], top_ai['name'], p['price'], qty, replacement_memo, model_id=m_id)
                                        self.add_trading_log(f"✨ AI자율매수: {top_ai['name']} {qty}주 선점")
                                        # [중요] 매수 시각 기록하여 쿨타임 발동
                                        self.strategy.record_buy(top_ai['code'], p['price'])
                                        # 자동 매수 성공 → 프리셋 전략 자동 할당
                                        preset_result = self.strategy.auto_assign_preset(top_ai['code'], top_ai['name'])
                                        if preset_result:
                                            self.add_trading_log(f"📋 전략 자동적용: [{preset_result['preset_name']}] TP:{preset_result['tp']:+.1f}% SL:{preset_result['sl']:.1f}%")
                                        self.update_all_data(is_virtual, force=True)
                                        break # 한 루프에 한 종목씩 안전하게 처리
                                    else:
                                        if "잔고가 부족" in msg: self.strategy.auto_ai_trade = False
                                        self.add_log(f"AI매수 실패: {msg}")
                                        # 매수 실패 시 다음 순위 종목 시도 가능하도록 함 (필요시 continue)

                # 5. [Phase 3] 주요 종목 차트 업데이트 (UI 블로킹 방지)
                self._update_featured_chart()
                
                # 6. 대기
                time.sleep(5 if is_virtual else 0.5)
                self.last_update_time = datetime.now().strftime('%H:%M:%S')
            except Exception as e:
                log_error(f"Data Update Error: {e}")
            finally:
                self.clear_busy("DATA")
            time.sleep(5)

    def theme_update_worker(self):
        """테마 데이터를 주기적으로 크롤링하여 파일로 저장 (Naver Finance)"""
        while self.is_running:
            try:
                from src.theme_engine import save_theme_data
                self.set_busy("테마 데이터 수집")
                theme_map = self.api.get_naver_theme_data()
                if theme_map:
                    save_theme_data(theme_map)
                    self.add_trading_log("✨ 테마 데이터베이스 갱신 완료")
            except Exception as e:
                try:
                    log_error(f"Theme Update Error: {e}")
                except: pass
            finally:
                self.clear_busy()
            
            # 테마 데이터는 6시간마다 갱신
            time.sleep(6 * 3600)

    def log_cleanup_worker(self):
        """로그 파일을 주기적으로 정리 (1시간 주기, 영업일 기준 2일치 유지)"""
        while self.is_running:
            try:
                self.set_busy("로그 정리 중")
                self.add_log("로그 파일 정리를 시작합니다...")
                
                # 1. trading_logs.json 정리
                j_cleaned = trading_log.cleanup(days_to_keep=2)
                
                # 2. error.log 정리
                e_cleaned = cleanup_text_log("error.log", days_to_keep=2)
                
                # 3. trading.log 정리
                t_cleaned = cleanup_text_log("trading.log", days_to_keep=2)
                
                if j_cleaned or e_cleaned or t_cleaned:
                    self.add_log("오래된 로그 파일 정리를 완료했습니다.")
                else:
                    self.add_log("로그 파일이 이미 최신 상태입니다.")
                    
            except Exception as e:
                log_error(f"Log Cleanup Worker Error: {e}")
            finally:
                self.clear_busy()
            
            # 1시간 대기
            time.sleep(3600)

    def start_workers(self, is_virtual):
        threading.Thread(target=self.index_update_worker, daemon=True).start()
        threading.Thread(target=self.data_update_worker, args=(is_virtual,), daemon=True).start()
        threading.Thread(target=self.theme_update_worker, daemon=True).start()
        threading.Thread(target=self.log_cleanup_worker, daemon=True).start()
