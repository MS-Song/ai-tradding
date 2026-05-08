from typing import Tuple, Dict, List, Optional

class ExitManager:
    """보유 종목의 익절(Take Profit) 및 손절(Stop Loss) 전략을 관리하는 엔진입니다.

    시장 장세(VIBE), 시간대별 페이즈(P1~P4), 그리고 개별 종목의 실시간 변동성(거래량 폭발 등)을 
    결합하여 최적의 매도 임계치를 동적으로 산출합니다. 사용자의 수동 설정 및 AI 전략 
    프리셋에 대한 우선순위 처리를 담당합니다.

    Attributes:
        base_tp (float): 시스템의 기본 익절 목표 수익률 (%).
        base_sl (float): 시스템의 기본 손절 허용 수익률 (%).
        manual_thresholds (dict): 사용자가 TUI를 통해 특정 종목에 직접 설정한 임계값 저장소.
    """
    def __init__(self, base_tp: float, base_sl: float):
        self.base_tp, self.base_sl = base_tp, base_sl
        self.manual_thresholds: Dict[str, List[float]] = {}

    def get_vibe_modifiers(self, vibe: str) -> Tuple[float, float]:
        """현재 시장 장세(VIBE)에 따른 익절/손절 보정치를 반환합니다.

        보정 규칙 (GEMINI.md 2.A):
            - BULL: 수익 극대화 위해 익절 상향(+3.0), 손절 완화(-1.0).
            - BEAR: 보수적 접근 위해 익절 하향(-2.0), 손절 타이트(+2.0).
            - DEFENSIVE: 극단적 자산 보호 위해 익절 극소화(-3.0), 손절 극단 타이트(+3.0).

        Args:
            vibe (str): 현재 시장 분위기 ('BULL', 'BEAR', 'NEUTRAL', 'DEFENSIVE').

        Returns:
            Tuple[float, float]: (익절 보정치, 손절 보정치).
        """
        tp_mod, sl_mod = 0.0, 0.0
        v = vibe.upper()
        if v == "BULL":
            tp_mod = 3.0    # 상승장: 수익 극대화 (익절가 상향)
            sl_mod = -1.0   # 상승장: 손절선 완화 (더 여유있게, -5 -> -6)
        elif v == "BEAR":
            tp_mod = -2.0   # 하락장: 짧은 익절 (보수적)
            sl_mod = 2.0    # 하락장: 손절선 타이트하게 관리 (-5 -> -3)
        elif v == "DEFENSIVE":
            tp_mod, sl_mod = -3.0, 3.0 # 방어모드: 극도로 보수적 (-5 -> -2)
        return tp_mod, sl_mod

    def get_thresholds(self, code: str, kr_vibe: str, price_data: Optional[dict] = None, phase_cfg: dict = None, base_tp: float = None, base_sl: float = None) -> Tuple[float, float, bool]:
        """특정 종목에 적용할 최종 익절 및 손절 임계치를 산출합니다.

        우선순위 및 보정 로직:
            1. 수동 설정(Manual): 최우선 적용하며 추가 보정을 생략합니다.
            2. AI 전략/프리셋: 지정된 값을 기본으로 하되 장세 중복 보정은 방지합니다.
            3. 보정 합산: 기본값 + 시장 장세(Vibe) + 시간 페이즈(Phase) + 거래량 폭발 보정을 누적합니다.
            4. Fee Guard: 수수료 및 슬리피지를 고려하여 최소 수익성(1.0%)을 보장합니다.

        Args:
            code (str): 종목 코드.
            kr_vibe (str): 현재 시장 장세.
            price_data (dict, optional): 현재가 및 전일 대비 거래량 등 시세 데이터.
            phase_cfg (dict, optional): 현재 시간 페이즈(P1~P4) 설정 및 보정값.
            base_tp (float, optional): 외부(AI 프리셋 등)에서 지정된 기본 익절선.
            base_sl (float, optional): 외부(AI 프리셋 등)에서 지정된 기본 손절선.

        Returns:
            Tuple[float, float, bool]: (최종 익절%, 최종 손절%, 거래량폭발여부).
        """
        # 1. 특정 종목 수동 설정(Manual)이 있으면 최우선 적용 (보정 없음)
        if code in self.manual_thresholds:
            vals = self.manual_thresholds[code]
            return float(vals[0]), float(vals[1]), True
            
        # 2. 기본값(AI가 설정한 값 또는 프리셋 값) 가져오기
        target_tp = base_tp if base_tp is not None else self.base_tp
        target_sl = base_sl if base_sl is not None else self.base_sl
        
        # 3. 시장 분위기(Vibe) 및 페이즈 보정 적용
        # AI가 할당한 개별 전략이나 수동 설정값이 있으면 중복 보정 생략
        if base_tp is not None or base_sl is not None:
            return round(target_tp, 1), round(target_sl, 1), False

        tp_mod, sl_mod = self.get_vibe_modifiers(kr_vibe)
        
        # 시간 페이즈 보정 합산
        if phase_cfg:
            # 하락장/방어모드에서 P2 등에 의한 추가 익절가 하향 방지
            if not (kr_vibe.upper() in ["BEAR", "DEFENSIVE"] and phase_cfg.get('tp_delta', 0) < 0):
                tp_mod += phase_cfg.get('tp_delta', 0)
                
            # 하락장 예외: Bear/Defensive일 때는 P1의 SL 완화 적용 안 함
            if not (kr_vibe.upper() in ["BEAR", "DEFENSIVE"] and phase_cfg['id'] == "P1"):
                sl_mod += phase_cfg.get('sl_delta', 0)
        
        target_tp += tp_mod
        target_sl += sl_mod
            
        # 4. 개별 종목 변동성(거래량 등)에 따른 추가 보정
        is_vol_spike = False
        if price_data and price_data.get('prev_vol', 0) > 0:
            if price_data['vol'] / price_data['prev_vol'] >= 1.5:
                target_tp += 2.0; is_vol_spike = True # 거래량 폭발 시 익절가 상향
                
        # 5. 수수료 및 최소 수익 방어 (Fee Guard)
        if target_tp < 1.0:
            target_tp = 1.0
            
        # 6. 손절선 상한 방어 (SL Guard)
        # 방어모드(Defensive)나 특정 페이즈(P2) 보정치가 가산되어 손절선이 양수(수익권)로 올라가는 것을 방지
        # 아무리 타이트한 장세라도 수수료와 호가 스프레드를 고려하여 최소 -1.0%의 공간은 확보함
        if target_sl > -1.0:
            target_sl = -1.0

        return round(target_tp, 1), round(target_sl, 1), is_vol_spike

