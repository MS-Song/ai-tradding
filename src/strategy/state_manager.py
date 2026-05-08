import os
import json
import threading
from datetime import datetime
from src.logger import log_error

class StateManager:
    def __init__(self, strategy, state_file="trading_state.json"):
        """StateManager를 초기화하고 백그라운드 저장 워커를 시작합니다.

        Args:
            strategy (VibeStrategy): 상태 정보를 제공할 메인 전략 엔진 인스턴스.
            state_file (str, optional): 상태 정보를 저장할 JSON 파일명. 기본값 "trading_state.json".
        """
        self.strategy = strategy
        self.state_file = state_file
        self._lock = threading.Lock()       # 동시 쓰기 충돌 방지
        self._pending = threading.Event()   # 대기 중인 저장 요청 신호
        self._stop = False
        # 전용 백그라운드 저장 워커 스레드 시작
        self._worker = threading.Thread(target=self._write_worker, daemon=True, name="StateSaveWorker")
        self._worker.start()

    # ──────────────────────────────────────────────────────────
    # 백그라운드 저장 워커
    # ──────────────────────────────────────────────────────────
    def _write_worker(self):
        """대기 중인 저장 요청을 하나씩 처리하는 전용 스레드.
        연속으로 _pending.set()이 쌓여도 1회의 실제 쓰기로 처리됨."""
        while not self._stop:
            triggered = self._pending.wait(timeout=1.0)
            if triggered:
                self._pending.clear()
                self._do_save()

    def _atomic_write(self, path: str, data: dict):
        """임시파일에 쓴 뒤 원자적으로 교체.
        os.replace()는 Windows/Linux 공통으로 원자성이 보장되어
        중간에 프로세스가 종료되어도 파일이 절대 반쪽 상태가 안 됨."""
        tmp_path = path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            os.replace(tmp_path, path)
        except Exception:
            try: os.remove(tmp_path)
            except: pass
            raise

    def _do_save(self):
        """실제 직렬화 및 파일 쓰기 (Lock 보호, 백그라운드 스레드에서 실행)"""
        with self._lock:
            try:
                s = self.strategy
                today = datetime.now().strftime('%Y-%m-%d')

                # [안전 병합] 디스크의 최신 히스토리와 메모리 히스토리를 병합
                if os.path.exists(self.state_file):
                    try:
                        with open(self.state_file, "r", encoding="utf-8") as f:
                            disk_data = json.load(f)
                        for date_key, recs in disk_data.get("recommendation_history", {}).items():
                            if date_key not in s.recommendation_history:
                                s.recommendation_history[date_key] = recs
                    except Exception: pass

                if s.ai_recommendations:
                    s.recommendation_history[today] = [
                        {"code": r['code'], "name": r['name'], "price": float(r.get('price', 0)), "theme": r['theme'], "score": r['score']}
                        for r in s.ai_recommendations
                    ]
                    dates = sorted(s.recommendation_history.keys())
                    if len(dates) > 7:
                        for d in dates[:-7]: del s.recommendation_history[d]

                data = {
                    "base_tp": s.exit_mgr.base_tp,
                    "base_sl": s.exit_mgr.base_sl,
                    "manual_thresholds": s.exit_mgr.manual_thresholds,
                    "last_avg_down_prices": s.recovery_eng.last_avg_down_prices,
                    "last_buy_prices": s.pyramid_eng.last_buy_prices,
                    "last_sell_times": s.last_sell_times,
                    "last_sl_times": s.last_sl_times,
                    "last_buy_times": s.last_buy_times,
                    "last_avg_down_msg": s.last_avg_down_msg,
                    "recommendation_history": s.recommendation_history,
                    "ai_config": s.ai_config,
                    "bear_config": s.recovery_eng.config,
                    "bull_config": s.bull_config,
                    "preset_strategies": s.preset_eng.preset_strategies,
                    "last_closing_bet_date": getattr(s, "_last_closing_bet_date", None),
                    "rejected_stocks": s.rejected_stocks,
                    "bad_sell_times": getattr(s, 'bad_sell_times', {}),
                    "replacement_logs": s.replacement_logs,
                    "last_rejected_date": today,
                    "start_day_asset": s.start_day_asset,
                    "start_day_pnl": s.start_day_pnl,
                    "last_asset_date": s.last_asset_date,
                    "notified_dates": getattr(s, 'state', None).notified_dates if getattr(s, 'state', None) else {}
                }
                self._atomic_write(self.state_file, data)
            except Exception as e:
                log_error(f"상태 저장 실패: {e}")

    # ──────────────────────────────────────────────────────────
    # 공개 인터페이스
    # ──────────────────────────────────────────────────────────
    def load_all_states(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    d = json.load(f)
                    s = self.strategy

                    if "base_tp" in d: s.exit_mgr.base_tp = d["base_tp"]
                    if "base_sl" in d: s.exit_mgr.base_sl = d["base_sl"]
                    s.exit_mgr.manual_thresholds = d.get("manual_thresholds", {})
                    s.recovery_eng.last_avg_down_prices = d.get("last_avg_down_prices", {})
                    s.pyramid_eng.last_buy_prices = d.get("last_buy_prices", {})
                    s.last_sell_times = d.get("last_sell_times", {})
                    s.last_sl_times = d.get("last_sl_times", {})
                    s.last_buy_times = d.get("last_buy_times", {})
                    s.last_avg_down_msg = d.get("last_avg_down_msg", "없음")
                    s.recommendation_history = d.get("recommendation_history", {})

                    s.preset_eng.preset_strategies = d.get("preset_strategies", {})

                    today = datetime.now().strftime('%Y-%m-%d')
                    if d.get("last_rejected_date") == today:
                        s.rejected_stocks = d.get("rejected_stocks", {})
                    else:
                        s.rejected_stocks = {}

                    for code, ps in s.preset_eng.preset_strategies.items():
                        if 'buy_time' not in ps: ps['buy_time'] = None
                        if 'deadline' not in ps: ps['deadline'] = None
                        if 'is_p3_processed' not in ps: ps['is_p3_processed'] = False

                    if "ai_config" in d:
                        s.ai_config.update(d["ai_config"])
                        s.ai_config["auto_apply"] = s.base_config.get("ai_config", {}).get("auto_apply", False)

                    if "bear_config" in d: s.recovery_eng.config.update(d["bear_config"])
                    if "bull_config" in d: s.bull_config.update(d["bull_config"])
                    s._last_closing_bet_date = d.get("last_closing_bet_date")
                    s.start_day_asset = d.get("start_day_asset", 0.0)
                    s.start_day_pnl = d.get("start_day_pnl", 0.0)
                    s.last_asset_date = d.get("last_asset_date", "")
                    s.replacement_logs = d.get("replacement_logs", [])
                    # bad_sell_times 로드 (재시작 후에도 재진입 차단 유지)
                    if not hasattr(s, 'bad_sell_times'): s.bad_sell_times = {}
                    s.bad_sell_times = d.get("bad_sell_times", {})
                    if hasattr(s, 'state') and s.state is not None:
                        s.state.notified_dates = d.get("notified_dates", {})
            except Exception as e:
                log_error(f"상태 파일 로드 실패: {e}")

    def save_all_states(self):
        """비동기 저장 요청 — 즉시 반환, 백그라운드 워커가 실제 쓰기 담당.
        연속 호출이 쌓여도 워커가 처리 중이면 자동으로 하나로 합산됨."""
        self._pending.set()  # 신호만 설정 후 즉시 반환 (논블로킹)

    def update_yesterday_recs(self):
        today = datetime.now().strftime('%Y-%m-%d')
        dates = sorted([d for d in self.strategy.recommendation_history.keys() if d < today])
        if dates:
            self.strategy.yesterday_recs = self.strategy.recommendation_history[dates[-1]]
        else:
            self.strategy.yesterday_recs = []

    def refresh_yesterday_recs_performance(self, hot_raw, vol_raw):
        if not self.strategy.yesterday_recs: return
        processed = []
        for r in self.strategy.yesterday_recs:
            curr_item = next((item for item in (hot_raw + vol_raw) if item and item['code'] == r['code']), None)
            if not curr_item:
                p_data = self.strategy.api.get_naver_stock_detail(r['code'])
                curr_p = float(p_data.get('price', r['price']))
            else:
                curr_p = float(curr_item['price'])
            chg = ((curr_p - r['price']) / r['price'] * 100) if r['price'] > 0 else 0
            processed.append({**r, "curr_price": curr_p, "change": chg})
        self.strategy.yesterday_recs_processed = sorted(processed, key=lambda x: abs(x['change']), reverse=True)
