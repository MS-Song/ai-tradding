from datetime import datetime, timedelta
from typing import Dict, Optional
from src.strategy.constants import PRESET_STRATEGIES
from src.logger import log_error, trading_log
from src.utils import get_now


class PresetStrategyEngine:
    """종목별 맞춤형 프리셋 전략(Strategy Preset)을 관리하고 할당하는 엔진입니다.

    AI 어드바이저의 분석 결과를 바탕으로 개별 종목의 특성(변동성, 수급 등)에 최적화된 
    익절/손절선과 전략 유효 시간(Deadline)을 설정합니다. 유효 기간이 만료된 전략의 
    자동 갱신 및 상태 유지를 담당합니다.

    Attributes:
        preset_strategies (Dict[str, dict]): 종목 코드별 현재 활성화된 프리셋 전략 정보 저장소.
        ai_advisor: 최적 전략 도출을 위한 AI 분석 엔진.
        api: 시세 및 종목 상세 정보 수집을 위한 API 클라이언트.
        get_vibe (callable): 현재 시장 VIBE 정보를 가져오는 콜백 함수.
        save_state (callable): 전략 할당/변경 시 상태를 `trading_state.json` 등에 영속 저장하는 콜백 함수.
    """
    def __init__(self, ai_advisor, api=None, get_vibe_cb=None, state_save_cb=None):
        self.preset_strategies: Dict[str, dict] = {}
        self.preset_strategy_stats: Dict[str, dict] = {}
        self.min_trades_for_pruning = 3
        self.ai_advisor = ai_advisor
        self.api = api
        self.get_vibe = get_vibe_cb
        self.save_state = state_save_cb
        
    def _calculate_deadline(self, preset_id, start_time_str, lifetime_mins):
        """전략의 유형과 시황을 고려하여 최종 만료 시각(Deadline)을 산출합니다.

        전략 유형별 수명 제한:
            - 단타/고변동성 전략 (03, 08, 07): 최대 3시간(180분).
            - 추세 추종 전략 (05, 09, 06): 최대 4시간(240분).

        Args:
            preset_id (str): 프리셋 고유 아이디.
            start_time_str (str): 전략이 수립된 시각 (YYYY-MM-DD HH:MM:SS).
            lifetime_mins (int): 전략 수립 시 AI가 제안한 수명(분 단위).

        Returns:
            Optional[str]: 계산된 만료 시각 문자열 ('YYYY-MM-DD HH:MM:SS'). 계산 실패 시 None.
        """
        if not start_time_str or not lifetime_mins: return None
        try:
            l_mins = int(lifetime_mins)
            # 고변동성/단타성 전략은 최대 3시간으로 제한
            if preset_id in ["03", "08", "07"]:
                l_mins = min(l_mins, 180)
            # 일반 추세 추종 전략은 최대 4시간으로 제한
            elif preset_id in ["05", "09", "06"]:
                l_mins = min(l_mins, 240)
            
            if l_mins <= 0: return None
            
            start_dt = datetime.strptime(start_time_str, '%Y-%m-%d %H:%M:%S')
            deadline_dt = start_dt + timedelta(minutes=l_mins)
            return deadline_dt.strftime('%Y-%m-%d %H:%M:%S')
        except Exception as e:
            log_error(f"Deadline 계산 실패: {e}")
            return None
            
    def assign_preset(self, code: str, preset_id: str, tp: float = None, sl: float = None, reason: str = "", lifetime_mins: int = None, name: str = "", is_manual: bool = False):
        """특정 종목에 프리셋 전략을 명시적으로 할당하거나 해제합니다.

        Args:
            code (str): 종목 코드.
            preset_id (str): 할당할 프리셋 ID. '00'일 경우 할당된 전략을 해제하고 표준 로직으로 복귀합니다.
            tp (float, optional): 적용할 익절선 (%). 미지정 시 프리셋 기본값 사용.
            sl (float, optional): 적용할 손절선 (%). 미지정 시 프리셋 기본값 사용.
            reason (str, optional): 전략 수립 근거 또는 상세 설명.
            lifetime_mins (int, optional): 전략 유효 시간 (분 단위).
            name (str, optional): 종목명.
            is_manual (bool): 사용자가 수동으로 할당했는지 여부.

        Returns:
            bool: 전략 할당 성공 여부.
        """
        preset = PRESET_STRATEGIES.get(preset_id)
        if not preset: return False
            
        # 기존 저장된 종목명이 있으면 활용
        if not name and code in self.preset_strategies:
            name = self.preset_strategies[code].get('stock_name', '')
        # 종목명이 없으면 API를 통해 가져오기 (마지막 수단)
        if not name and self.api:
            try:
                detail = self.api.get_naver_stock_detail(code)
                if detail: name = detail.get('pdnm', '')
            except Exception as e:
                from src.logger import logger
                logger.debug(f"전략 할당 중 종목명 취득 실패 ({code}): {e}")

        if preset_id == "00":
            if code in self.preset_strategies:
                del self.preset_strategies[code]
                trading_log.log_config(f"전략 해제: [{code}]{name} -> 표준 복귀")
        else:
            now_str = get_now().strftime('%Y-%m-%d %H:%M:%S')
            use_tp = tp if tp is not None else preset["default_tp"]
            use_sl = sl if sl is not None else preset["default_sl"]
            self.preset_strategies[code] = {
                "preset_id": preset_id,
                "name": preset["name"],
                "stock_name": name, 
                "tp": use_tp,
                "sl": use_sl,
                "reason": reason or preset["desc"],
                "buy_time": now_str,
                "deadline": self._calculate_deadline(preset_id, now_str, lifetime_mins),
                "is_p3_processed": False,
                "is_manual": is_manual
            }
            trading_log.log_config(f"전략 할당: [{code}]{name} -> {preset['name']} | TP:{use_tp}% SL:{use_sl}%")
            
        if self.save_state: self.save_state()
        return True

    def record_trade_result(self, preset_id: str, profit_rt: float, profit_amount: float = 0.0):
        """특정 프리셋 전략의 매매 결과를 기록하고 누적 통계(승률, PF, EV)를 실시간 갱신합니다.

        EV (수학적 기대값) = (Win Rate * Avg Win %) - (Loss Rate * Avg Loss %)
        """
        if not preset_id or preset_id == "00":
            return
        
        stat = self.preset_strategy_stats.setdefault(preset_id, {
            "name": PRESET_STRATEGIES.get(preset_id, {}).get("name", f"전략{preset_id}"),
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_profits": [],
            "loss_profits": [],
            "win_rate": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "profit_factor": 1.0,
            "ev": 0.0,
            "is_pruned": False
        })
        
        stat["trades"] += 1
        if profit_rt > 0:
            stat["wins"] += 1
            stat["win_profits"].append(float(profit_rt))
        else:
            stat["losses"] += 1
            stat["loss_profits"].append(abs(float(profit_rt)))
            
        trades = stat["trades"]
        wins = stat["wins"]
        stat["win_rate"] = round(wins / trades, 4) if trades > 0 else 0.0
        
        avg_w = sum(stat["win_profits"]) / len(stat["win_profits"]) if stat["win_profits"] else 0.0
        avg_l = sum(stat["loss_profits"]) / len(stat["loss_profits"]) if stat["loss_profits"] else 0.0
        stat["avg_win"] = round(avg_w, 2)
        stat["avg_loss"] = round(avg_l, 2)
        
        win_rate = stat["win_rate"]
        loss_rate = 1.0 - win_rate
        ev = (win_rate * avg_w) - (loss_rate * avg_l)
        stat["ev"] = round(ev, 2)
        
        sum_w = sum(stat["win_profits"])
        sum_l = sum(stat["loss_profits"])
        if sum_l > 0:
            stat["profit_factor"] = round(sum_w / sum_l, 2)
        else:
            stat["profit_factor"] = 99.0 if sum_w > 0 else 1.0
            
        # 표본 수가 충족되고 EV가 0 이하이거나 Profit Factor < 0.8이면 도태
        stat["is_pruned"] = (trades >= self.min_trades_for_pruning and (ev <= 0.0 or stat["profit_factor"] < 0.8))
        if stat["is_pruned"]:
            from src.logger import logger
            logger.warning(f"📉 [전략 도태] 프리셋 [{preset_id}:{stat['name']}] EV:{ev:+.2f}%, PF:{stat['profit_factor']:.2f} (표본 {trades}회) -> 약세 전략 자동 도태")

        if self.save_state:
            self.save_state()

    def is_preset_pruned(self, preset_id: str) -> bool:
        """해당 프리셋 전략이 기대값 음수로 인해 도태되었는지 여부를 확인합니다."""
        if not preset_id or preset_id not in self.preset_strategy_stats:
            return False
        stat = self.preset_strategy_stats[preset_id]
        return bool(stat.get("is_pruned", False))

    def get_best_preset_id(self, fallback: str = "01") -> str:
        """도태되지 않은 프리셋 중 기대값(EV)이 가장 높은 최적 전략 ID를 반환합니다."""
        candidates = []
        for pid, s in self.preset_strategy_stats.items():
            if not s.get("is_pruned", False) and s.get("trades", 0) > 0:
                candidates.append((pid, s.get("ev", 0.0)))
        if candidates:
            candidates.sort(key=lambda x: x[1], reverse=True)
            return candidates[0][0]
        return fallback

    def auto_assign_preset(self, code: str, name: str) -> Optional[dict]:
        """AI를 호출하여 해당 종목에 가장 적합한 전략 프리셋을 자동으로 판정하고 할당합니다.

        도태된(Pruned) 약세 전략이 제안될 경우, 양의 기대값을 가진 대안 전략으로 자동 교체합니다.
        """
        try:
            detail = self.api.get_naver_stock_detail(code)
            news = self.api.get_naver_stock_news(code)
            vibe = self.get_vibe() if self.get_vibe else "Neutral"
            result = self.ai_advisor.simulate_preset_strategy(code, name, vibe, detail, news)
            if result:
                pid = result["preset_id"]
                if self.is_preset_pruned(pid):
                    orig_name = PRESET_STRATEGIES.get(pid, {}).get("name", pid)
                    new_pid = self.get_best_preset_id(fallback="01" if pid != "01" else "02")
                    new_name = PRESET_STRATEGIES.get(new_pid, {}).get("name", new_pid)
                    from src.logger import logger
                    logger.warning(f"⚠️ [전략 도태 차단] [{code}]{name} AI 제안 전략 [{pid}:{orig_name}]은 EV 음수로 도태됨 -> 최적 전략 [{new_pid}:{new_name}]으로 대체 할당")
                    result["preset_id"] = new_pid
                    result["reason"] = f"[도태 대체:{orig_name}->{new_name}] " + result.get("reason", "")
                
                self.assign_preset(code, result["preset_id"], result["tp"], result["sl"], result["reason"], result.get("lifetime_mins"), name=name)
                return result
        except Exception as e:
            log_error(f"자동 프리셋 할당 오류: {e}")
        return None
