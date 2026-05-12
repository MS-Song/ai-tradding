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

    def auto_assign_preset(self, code: str, name: str) -> Optional[dict]:
        """AI를 호출하여 해당 종목에 가장 적합한 전략 프리셋을 자동으로 판정하고 할당합니다.

        현재 시황(VIBE), 펀더멘털 데이터, 최근 뉴스를 AI에게 전달하여 
        시뮬레이션된 최적의 전략 파라미터(ID, TP, SL, 수명 등)를 도출합니다.

        Args:
            code (str): 종목 코드.
            name (str): 종목명.

        Returns:
            Optional[dict]: AI가 도출한 전략 상세 정보. 실패 시 None.
        """
        try:
            detail = self.api.get_naver_stock_detail(code)
            news = self.api.get_naver_stock_news(code)
            vibe = self.get_vibe() if self.get_vibe else "Neutral"
            result = self.ai_advisor.simulate_preset_strategy(code, name, vibe, detail, news)
            if result:
                self.assign_preset(code, result["preset_id"], result["tp"], result["sl"], result["reason"], result.get("lifetime_mins"), name=name)
                return result
        except Exception as e:
            log_error(f"자동 프리셋 할당 오류: {e}")
        return None
