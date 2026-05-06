import os
import threading
import time
import queue
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

from src.data.state import TradingState
from src.workers.market_worker import MarketWorker
from src.workers.sync_worker import DataSyncWorker
from src.workers.trade_worker import TradeWorker
from src.workers.report_worker import ReportWorker
from src.workers.retrospective_worker import RetrospectiveWorker
from src.utils.notifier import TelegramNotifier
from src.logger import log_error, cleanup_text_log, trading_log, logger

class DataManager:
    def __init__(self, api, strategy):
        self.api = api
        self.strategy = strategy
        
        # --- 핵심 상태 관리 객체 (Phase 1) ---
        self.state = TradingState()
        self.strategy.state = self.state # [추가] StateManager가 notified_dates 등에 접근할 수 있도록 주입
        self.strategy.state_mgr.load_all_states() # [추가] state 주입 후 다시 로드하여 notified_dates 등 복구
        
        # --- 알림 엔진 초기화 ---
        self.notifier = TelegramNotifier(dm=self)
        trading_log.set_notifier(self.notifier)
        
        # --- 텔레그램 인바운드 명령 엔진 초기화 ---
        try:
            from src.utils.telegram_receiver import TelegramCommandListener
            self.telegram_listener = TelegramCommandListener(dm=self)
            self.telegram_listener.start()
        except ImportError as e:
            from src.logger import log_error
            log_error(f"TelegramCommandListener Load Error: {e}")

        
        # --- 워커 인스턴스 (Phase 2) ---
        self.workers = {
            "MARKET": MarketWorker(self.state, api, strategy, self.notifier),
            "DATA": DataSyncWorker(self.state, api, strategy),
            "TRADE": TradeWorker(self.state, api, strategy),
            "REPORT": ReportWorker(self.state, strategy, self.notifier),
            "RETRO": RetrospectiveWorker(self.state, strategy, self.notifier)
        }
        
        # --- 하위 호환용 락 (기존 코드에서 참조함) ---
        self.data_lock = self.state.lock
        self.ui_lock = threading.Lock() # UI 전용 락 유지
        
        # --- 초기 알림 ---
        self.notifier.notify_alert("시스템 시작", self._build_system_msg("🚀 KIS-Vibe-Trader 엔진이 가동되었습니다."))

    # --- 하위 호환성을 위한 프로퍼티 매핑 ---
    @property
    def is_running(self): return self.state.is_running
    @is_running.setter
    def is_running(self, val): self.state.is_running = val
    
    @property
    def status_msg(self): return self.state.status_msg
    @status_msg.setter
    def status_msg(self, val): self.state.status_msg = val
    
    @property
    def status_time(self): return self.state.status_time
    @status_time.setter
    def status_time(self, val): self.state.status_time = val
    
    @property
    def trading_logs(self): return self.state.trading_logs
    
    @property
    def cached_holdings(self): return self.state.holdings
    @property
    def cached_asset(self): return self.state.asset
    @property
    def cached_stock_info(self): return self.state.stock_info
    @property
    def cached_vibe(self): return self.state.vibe
    @property
    def cached_market_data(self): return self.state.market_data
    @property
    def cached_panic(self): return self.state.is_panic
    @property
    def cached_hot_raw(self): return self.state.hot_raw
    @property
    def hot_stocks(self): return self.state.hot_raw
    @property
    def cached_vol_raw(self): return self.state.vol_raw
    @property
    def vol_stocks(self): return self.state.vol_raw
    @property
    def cached_recommendations(self): return self.state.recommendations
    @property
    def recommendations(self): return self.state.recommendations
    @property
    def cached_dema_info(self): return self.state.dema_info
    @property
    def cached_ai_costs(self): return self.state.ai_costs
    @property
    def cached_holdings_fetched(self): return self.state.holdings_fetched
    @property
    def is_kr_market_active(self): return self.state.is_kr_market_active
    @property
    def is_input_active(self): return self.state.is_input_active
    @is_input_active.setter
    def is_input_active(self, val): self.state.is_input_active = val
    @property
    def is_full_screen_active(self): return self.state.is_full_screen_active
    @is_full_screen_active.setter
    def is_full_screen_active(self, val): self.state.is_full_screen_active = val
    @property
    def worker_results(self): return self.state.worker_results
    @property
    def worker_last_tasks(self): return self.state.worker_last_tasks
    @property
    def last_times(self): return self.state.last_times
    @property
    def _worker_statuses(self): return self.state.worker_statuses
    @property
    def worker_names(self): return self.state.worker_names
    @property
    def global_busy_msg(self): return self.state.get_global_busy_msg()
    @property
    def vibe(self): return self.state.vibe
    @property
    def is_panic(self): return self.state.is_panic
    @property
    def dema_info(self): return self.state.dema_info
    @property
    def asset_info(self): return self.state.asset
    @property
    def update_time(self): return self.state.last_update_time
    @property
    def last_size(self): return self.state.last_terminal_size
    @last_size.setter
    def last_size(self, val): self.state.last_terminal_size = val
    @property
    def update_info(self): return self.state.update_info
    @property
    def ai_costs(self): return self.state.ai_costs
    @property
    def chart_data(self): return self.state.chart_data
    @property
    def input_prompt(self): return self.state.input_prompt
    @input_prompt.setter
    def input_prompt(self, val): self.state.input_prompt = val
    @property
    def input_buffer(self): return self.state.input_buffer
    @input_buffer.setter
    def input_buffer(self, val): self.state.input_buffer = val
    @property
    def current_prompt_mode(self): return self.state.current_prompt_mode
    @current_prompt_mode.setter
    def current_prompt_mode(self, val): self.state.current_prompt_mode = val
    
    @property
    def is_trading_paused(self): return self.state.is_trading_paused
    @property
    def market_info_status(self):
        res = self.state.worker_results.get("INDEX")
        if res == "실패": return "실패"
        if res == "성공": return "성공"
        return "대기"

    @property
    def ranking_filter(self): return self.state.ranking_filter
    @ranking_filter.setter
    def ranking_filter(self, val): self.state.ranking_filter = val

    @property
    def last_log_msg(self): return self.state.last_log_msg
    @last_log_msg.setter
    def last_log_msg(self, val):
        self.state.last_log_msg = val
        self.state.last_log_time = time.time()
    @property
    def last_log_time(self): return self.state.last_log_time

    @property
    def busy_anim_step(self): return self.state.busy_anim_step
    @busy_anim_step.setter
    def busy_anim_step(self, val): self.state.busy_anim_step = val
    @property
    def ma_20_cache(self): return self.state.ma_20_cache

    # --- 필수 메서드 구현 (UI/Interaction 호출용) ---
    def set_busy(self, msg, worker="GLOBAL", friendly_name=None):
        self.state.update_worker_status(worker, status=msg, friendly_name=friendly_name)

    def clear_busy(self, worker="GLOBAL"):
        self.state.clear_worker_status(worker)

    def update_worker_status(self, worker, result=None, last_task=None, friendly_name=None):
        self.state.update_worker_status(worker, result=result, last_task=last_task, friendly_name=friendly_name)

    def update_indicator(self, name: str, status: str, value: str, remark: str):
        """주요 지표 갱신 상태를 업데이트하고, 실패 시 텔레그램 알림을 발송합니다."""
        with self.state.lock:
            self.state.indicator_updates[name] = {
                "time": time.time(),
                "status": status,
                "value": value,
                "remark": remark
            }
        
        if status == "실패" and self.notifier:
            try:
                self.notifier.notify_alert("지표 갱신 실패", f"⚠️ <b>{name}</b> 갱신 중 오류가 발생했습니다.\n비고: {remark}")
            except Exception as e:
                from src.logger import log_error
                log_error(f"Telegram notification error in update_indicator: {e}")

    def is_busy(self):
        return self.state.is_worker_busy()

    def is_blocking_busy(self):
        # GLOBAL 작업 중이면 매매 차단
        return self.state.is_worker_busy("GLOBAL")

    def show_status(self, msg, is_error=False):
        self.state.set_status(msg, is_error)

    def add_log(self, msg):
        with self.state.lock:
            self.state.last_log_msg = f"\033[96m[LOG] {msg}\033[0m"
            self.state.last_log_time = time.time()

    def add_trading_log(self, msg):
        self.state.add_trading_log(msg)
        trading_log.log_config(msg)

    def start_workers(self, is_virtual: bool):
        """메인 루프에서 호출하여 백그라운드 스레드 가동"""
        for worker in self.workers.values():
            worker.start()
        
        # 로그 정리 및 테마 수집은 별도 스레드로 유지 (추후 별도 워커화 가능)
        threading.Thread(target=self._maintenance_loop, daemon=True).start()
        
        # [Auto-Update] 시작 시 즉시 1회 버전 체크 (비동기)
        threading.Thread(target=self._check_update_once, daemon=True).start()

    def _maintenance_loop(self):
        """로그 정리 및 주기적 관리 작업"""
        _last_update_check = 0  # 마지막 버전 체크 시각
        while self.state.is_running:
            try:
                self.set_busy("로그 정리", "CLEANUP")
                cleanup_text_log("error.log", days_to_keep=2)
                trading_log.cleanup(days_to_keep=2)
                self.update_worker_status("CLEANUP", result="성공", last_task="로그 파일 정리 완료")
                
                # [Auto-Update] 6시간마다 GitHub 버전 체크
                if time.time() - _last_update_check > 6 * 3600:
                    self._run_update_check()
                    _last_update_check = time.time()
                    
                self.update_worker_status("UPDATE", result="성공", last_task="시스템 상태 체크 완료")
            except Exception as e:
                log_error(f"Maintenance Loop Error: {e}")
            finally:
                self.clear_busy("CLEANUP")
            
            time.sleep(3600) # 1시간 주기

    def _check_update_once(self):
        """시작 직후 즉시 1회 GitHub 버전 체크 (비동기 호출용)"""
        time.sleep(5)  # 시스템 안정화 후 체크
        self._run_update_check()

    def _run_update_check(self):
        """GitHub 릴리스 API로 버전 체크 후 state.update_info 갱신"""
        try:
            from src.updater import check_for_updates, is_running_as_executable
            from src.ui.renderer import VERSION_CACHE
            result = check_for_updates(VERSION_CACHE)
            with self.state.lock:
                self.state.update_info["has_update"] = result.get("has_update", False)
                self.state.update_info["latest_version"] = result.get("latest_version", "")
                self.state.update_info["download_url"] = result.get("download_url", "")
            
            if result.get("has_update"):
                is_exe = is_running_as_executable()
                # 자동 업데이트 설정값 읽기 (strategy.config 또는 .env 직접)
                auto_update_enabled = False
                try:
                    cfg = self.strategy.config.get("vibe_strategy", {})
                    auto_update_enabled = cfg.get("auto_update", False)
                except Exception:
                    from dotenv import dotenv_values
                    auto_update_enabled = dotenv_values(".env").get("AUTO_UPDATE", "FALSE") == "TRUE"
                
                if is_exe and auto_update_enabled:
                    # 실행파일 모드 + 자동 업데이트 ON → 자동 다운로드 및 재기동
                    self.add_log(f"🆕 [AUTO-UPDATE] v{result['latest_version']} 자동 업데이트 시작...")
                    self.update_worker_status("UPDATE", result="업데이트 시작", last_task=f"v{result['latest_version']} 자동 적용 중")
                    threading.Thread(target=self._apply_auto_update, args=(result,), daemon=True).start()
                else:
                    # 개발 모드 또는 자동 업데이트 OFF → 알림만
                    if is_exe:
                        hint = "S:셈업 → AUTO_UPDATE=Y로 자동 업데이트 활성화 가능 | 단축키 [U]로 수동 업데이트"
                    else:
                        hint = "[개발모드] 수동 업데이트만 지원 | 다음에 다시: 단축키 [U]"
                    self.add_log(f"🆕 [AUTO-UPDATE] 새 버전 감지: v{result['latest_version']} (v{VERSION_CACHE}) — {hint}")
                    self.update_worker_status("UPDATE", result="업데이트 가능", last_task=f"v{result['latest_version']} 릴리스 감지")
            else:
                self.update_worker_status("UPDATE", result="최신", last_task=f"현재 v{VERSION_CACHE} 최신 버전")
        except Exception as e:
            log_error(f"Update Check Error: {e}")

    def _apply_auto_update(self, result: dict):
        """실행파일 모드에서만 호출: 다운로드 → 적용 → 재기동"""
        try:
            from src.updater import download_update, apply_update_and_restart
            import platform
            
            is_windows = platform.system() == "Windows"
            new_bin = "KIS-Vibe-Trader_new.exe" if is_windows else "KIS-Vibe-Trader-Linux_new"
            
            url = result.get("download_url", "")
            if not url:
                self.add_log("❌ [AUTO-UPDATE] 다운로드 URL을 찾을 수 없습니다. 릴리스 자산 확인 필요.")
                self.update_worker_status("UPDATE", result="URL 없음", last_task="다운로드 URL 누락")
                return
            
            self.set_busy("업데이트 다운로드 중", "UPDATE")
            
            def prog_cb(downloaded, total):
                pct = downloaded / total * 100 if total > 0 else 0
                self.set_busy(f"다운로드 {pct:.1f}%", "UPDATE")
            
            success = download_update(url, new_bin, progress_cb=prog_cb)
            if success:
                self.add_log(f"✅ [AUTO-UPDATE] v{result['latest_version']} 다운로드 완료! 3초 후 재기동...")
                self.update_worker_status("UPDATE", result="재기동 중", last_task=f"v{result['latest_version']} 적용 완료")
                try:
                    self.notifier.notify_alert("업데이트 적용", f"🛠️ v{result['latest_version']} 업데이트를 적용하고 재기동합니다.")
                except Exception:
                    pass
                time.sleep(3)
                apply_update_and_restart(new_bin)
            else:
                self.add_log("❌ [AUTO-UPDATE] 다운로드 실패. 수동으로 업데이트하려면 [U] 키를 누르세요.")
                self.update_worker_status("UPDATE", result="다운로드 실패", last_task="수동 업데이트 필요")
        except Exception as e:
            log_error(f"Auto-Update Apply Error: {e}")
            self.add_log(f"❌ [AUTO-UPDATE] 오류: {e}")
        finally:
            self.clear_busy("UPDATE")

    def _build_system_msg(self, headline: str) -> str:
        """실행 시스템 정보를 포함한 알림 메시지를 생성합니다."""
        import socket, platform, sys, os
        from src.updater import is_running_as_executable
        from src.ui.renderer import VERSION_CACHE
        
        try:
            hostname = socket.gethostname()
        except Exception:
            hostname = "Unknown"
        
        # IP 주소 (로칼 + 외부 IP 모두 시도)
        try:
            local_ip = socket.gethostbyname(hostname)
        except Exception:
            local_ip = "Unknown"
        
        try:
            import urllib.request
            public_ip = urllib.request.urlopen("https://api.ipify.org", timeout=3).read().decode()
        except Exception:
            public_ip = "N/A"
        
        run_mode = "EXE" if is_running_as_executable() else "DEV(python)"
        os_info = f"{platform.system()} {platform.release()}"
        py_ver = f"Python {sys.version.split()[0]}" if not is_running_as_executable() else ""
        cwd = os.getcwd()
        # 경로가 너무 길면 마지막 두 단계만
        cwd_parts = cwd.replace("\\", "/").split("/")
        cwd_short = "/".join(cwd_parts[-2:]) if len(cwd_parts) >= 2 else cwd
        
        lines = [headline, ""]
        lines.append(f"🖥️  호스트: `{hostname}`")
        lines.append(f"🌐  로칼 IP: `{local_ip}`")
        lines.append(f"🏠  외부 IP: `{public_ip}`")
        lines.append(f"💻  OS: `{os_info}`")
        lines.append(f"⚡  실행모드: `{run_mode}`{f' / {py_ver}' if py_ver else ''}")
        lines.append(f"📂  경로: `.../{cwd_short}`")
        lines.append(f"🔖  버전: `v{VERSION_CACHE}`")
        return "\n".join(lines)

    def shutdown(self, reason="사용자 종료"):
        self.notifier.notify_alert("시스템 종료", self._build_system_msg(f"🛑 트레이딩 엔진이 종료되었습니다.\n📌 사유: {reason}"))
        self.state.is_running = False
        for worker in self.workers.values():
            worker.stop()
            
        # --- 텔레그램 스레드 안전 종료 ---
        if hasattr(self, 'telegram_listener') and self.telegram_listener:
            if hasattr(self.telegram_listener, 'stop'):
                self.telegram_listener.stop()
        if hasattr(self, 'notifier') and self.notifier:
            self.notifier.stop()
            
        time.sleep(1)

    # --- 긴급 제어 메서드 (Telegram Inbound) ---
    def toggle_trading_pause(self, pause: bool):
        with self.state.lock:
            self.state.is_trading_paused = pause
        if pause:
            self.show_status("신규 매수 일시 정지됨", is_error=True)
            self.add_log("⏸️ [TELEGRAM] 신규 매수 일시 정지 활성화")
            self.add_trading_log("⏸️ [TELEGRAM] 신규 매수 일시 정지 활성화")
        else:
            self.show_status("매매 정상 재개됨")
            self.add_log("▶️ [TELEGRAM] 매매 정상 재개")
            self.add_trading_log("▶️ [TELEGRAM] 매매 정상 재개")

    def execute_emergency_panic(self):
        with self.state.lock:
            self.state.manual_panic = True
            self.state.is_panic = True
            self.state.is_trading_paused = True
        self.show_status("🚨 긴급 패닉 모드 발동 - 전 종목 청산 대기중", is_error=True)
        self.add_log("🚨 [TELEGRAM INBOUND] 긴급 패닉 모드 활성화! 전 종목 청산 진행")
        self.add_trading_log("🚨 [긴급] 텔레그램 패닉 명령 수신 - 전 종목 청산 시도")

    def force_defensive_mode(self):
        with self.state.lock:
            self.state.force_vibe = "Defensive"
            self.state.vibe = "Defensive"
        self.show_status("🛡️ 강제 방어모드 전환", is_error=False)
        self.add_log("🛡️ [TELEGRAM] 강제 방어모드(Defensive) 전환")
        self.add_trading_log("🛡️ [TELEGRAM] 강제 방어모드(Defensive) 전환")
        
    def reset_emergency_state(self):
        with self.state.lock:
            self.state.manual_panic = False
            self.state.is_panic = False
            self.state.is_trading_paused = False
            self.state.force_vibe = None
        self.show_status("🔄 긴급 상태 전면 해제 (정상화)", is_error=False)
        self.add_log("🔄 [TELEGRAM] 모든 긴급 제어 해제 (패닉/정지/방어모드)")
        self.add_trading_log("🔄 [TELEGRAM] 모든 긴급 제어 해제 (정상 운용 복귀)")

    def execute_manual_trade(self, action: str, code: str, qty: int, price: Optional[float] = None) -> Tuple[bool, str]:
        # action: "BUY" or "SELL"
        is_buy = action.upper() == "BUY"
        action_kr = "매수" if is_buy else "매도"
        
        # 종목명 찾기 (캐시 또는 보유 종목)
        stock_name = self.state.stock_info.get(code, {}).get("name")
        if not stock_name:
            for h in self.state.holdings:
                if h.get("pdno") == code:
                    stock_name = h.get("prdt_name")
                    break
        if not stock_name:
            stock_name = code  # 못 찾으면 코드 그대로 사용

        # [추가] 매도 시 보유 수량 체크 및 조정
        if not is_buy:
            holding = next((h for h in self.state.holdings if h.get("pdno") == code), None)
            if holding:
                max_qty = int(float(holding.get("hldg_qty", 0)))
                if qty > max_qty:
                    self.add_trading_log(f"⚠️ {stock_name} 보유수량({max_qty}) 초과 -> {max_qty}주로 조정")
                    qty = max_qty
            else:
                # 보유하지 않은 종목 매도 시도 시
                msg = f"❌ 매도 실패: {stock_name}({code}) 종목을 보유하고 있지 않습니다."
                self.add_trading_log(msg)
                return False, msg

        try:
            p_val = int(price) if price and price > 0 else 0
            success, msg = self.api.order_market(code, qty, is_buy, p_val)
            order_type = "시장가" if p_val == 0 else f"지정가({p_val:,}원)"
                
            if success:
                self.add_log(f"✅ [TELEGRAM] 수동 {action_kr} 완료: {stock_name}({code}) {qty}주 ({order_type})")
                self.add_trading_log(f"✅ 수동 {action_kr}: {stock_name}({code}) {qty}주 ({order_type})")
                
                # trading_logs.json 에 정식 기록 및 텔레그램 알림 발송
                curr_p = float(p_val) if p_val > 0 else float(self.state.stock_info.get(code, {}).get("price", 0))
                profit = 0.0
                if not is_buy:
                    for h in self.state.holdings:
                        if h.get("pdno") == code:
                            avg_p = float(h.get("pchs_avg_pric", 0))
                            if avg_p > 0 and curr_p > 0:
                                profit = (curr_p - avg_p) * qty
                            break
                trade_type = "수동매수" if is_buy else "수동매도"
                ma20 = self.state.ma_20_cache.get(code, 0.0)
                
                trading_log.log_trade(
                    trade_type, code, stock_name, curr_p, qty, 
                    f"텔레그램 수동 주문 ({order_type})", 
                    profit=profit, model_id="수동", ma_20=ma20
                )
                
                # 빠른 동기화를 위해 업데이트 요청
                self.update_all_data(False, force=True)
                return True, f"✅ 수동 {action_kr} 주문 성공: {stock_name}({code}) {qty}주 ({order_type})"
            else:
                self.add_log(f"❌ [TELEGRAM] 수동 {action_kr} 실패: {stock_name}({code}) - {msg}")
                self.add_trading_log(f"❌ 수동 {action_kr} 실패: {stock_name}({code}) - {msg}")
                return False, f"❌ 수동 {action_kr} 실패: {stock_name}({code}) - {msg}"
        except Exception as e:
            msg = f"❌ 주문 중 오류 발생: {e}"
            self.add_trading_log(msg)
            return False, msg

    def trigger_ai_diagnosis(self):
        """AI 진단(시황 및 추천)을 즉시 실행하도록 워커에게 요청"""
        with self.state.lock:
            self.state.force_ai_diagnosis = True
        self.add_log("🧠 [TELEGRAM] AI 즉시 진단 요청됨")
        return "🧠 <b>AI 즉시 진단을 시작합니다...</b>\n(약 10~20초 소요될 수 있습니다)"

    def get_recent_logs(self, count=10) -> str:
        """최신 트레이딩 로그를 가져옴"""
        try:
            if not os.path.exists("trading.log"):
                return "📂 트레이딩 로그 파일이 없습니다."
            
            with open("trading.log", "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            # 최신 count개 추출 및 포맷팅
            recent = lines[-count:]
            if not recent:
                return "📂 기록된 로그가 없습니다."
                
            # 가독성을 위해 불필요한 부분 제거 (날짜/시간은 유지)
            formatted = []
            for line in recent:
                # 2026-04-30 15:30:00 | INFO    | [TRADE] ... -> [15:30:00] [TRADE] ...
                parts = line.split(" | ")
                if len(parts) >= 3:
                    time_part = parts[0].split(" ")[1] if " " in parts[0] else parts[0]
                    msg_part = parts[2].strip()
                    formatted.append(f"<code>[{time_part}]</code> {msg_part}")
                else:
                    formatted.append(f"<code>{line.strip()}</code>")
            
            return "📝 <b>최신 트레이딩 로그 ({0}개)</b>\n━━━━━━━━━━━━━━\n{1}".format(len(formatted), "\n".join(formatted))
        except Exception as e:
            return f"❌ 로그 읽기 오류: {e}"

    def get_recent_errors(self, count=10) -> str:
        """최신 에러 로그를 가져옴"""
        try:
            if not os.path.exists("error.log"):
                return "📂 에러 로그 파일이 없습니다."
            
            with open("error.log", "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            recent = lines[-count:]
            if not recent:
                return "✅ 최근 발생한 에러가 없습니다."
                
            formatted = []
            for line in recent:
                parts = line.split(" | ")
                if len(parts) >= 3:
                    time_part = parts[0].split(" ")[1] if " " in parts[0] else parts[0]
                    msg_part = parts[2].strip()
                    formatted.append(f"<code>[{time_part}]</code> {msg_part}")
                else:
                    formatted.append(f"<code>{line.strip()}</code>")
            
            return "⚠️ <b>최신 에러 로그 ({0}개)</b>\n━━━━━━━━━━━━━━\n{1}".format(len(formatted), "\n".join(formatted))
        except Exception as e:
            return f"❌ 에러 로그 읽기 오류: {e}"

    # --- 호환성용 더미/대행 메서드 ---
    def update_all_data(self, is_virtual, force=False, lite=False):
        """수동 매매 등으로 인해 즉시 데이터 갱신이 필요할 때 호출"""
        if force:
            worker = self.workers.get("DATA")
            if worker and hasattr(worker, "force_sync"):
                worker.force_sync = True
                self.show_status("잔고 동기화 요청됨...")

    def notify_latest_trades(self):
        """TradeWorker에서 호출하거나 여기서 별도 처리"""
        # TelegramNotifier가 이미 dm(self)을 가지고 있으므로 내부에서 처리 가능
        pass
