from typing import Tuple, Dict, List, Optional

class ExitManager:
    def __init__(self, base_tp: float, base_sl: float):
        self.base_tp, self.base_sl = base_tp, base_sl
        self.manual_thresholds: Dict[str, List[float]] = {}

    def get_vibe_modifiers(self, vibe: str) -> Tuple[float, float]:
        """현재 Vibe에 따른 TP/SL 보정치 반환 (Vibe에 따른 실시간 대응)"""
        tp_mod, sl_mod = 0.0, 0.0
        v = vibe.upper()
        if v == "BULL":
            tp_mod = 3.0    # 상승장: 수익 극대화 (익절가 상향)
            sl_mod = 1.0    # 상승장: 손절선 소폭 완화
        elif v == "BEAR":
            tp_mod = -2.0   # 하락장: 짧은 익절 (보수적)
            sl_mod = -2.0   # 하락장: 손절선 타이트하게 관리
        elif v == "DEFENSIVE":
            tp_mod, sl_mod = -3.0, -3.0 # 방어모드: 극도로 보수적
        return tp_mod, sl_mod

    def get_thresholds(self, code: str, kr_vibe: str, price_data: Optional[dict] = None, phase_cfg: dict = None, base_tp: float = None, base_sl: float = None) -> Tuple[float, float, bool]:
        # 1. 특정 종목 수동 설정(Manual)이 있으면 최우선 적용 (보정 없음)
        if code in self.manual_thresholds:
            vals = self.manual_thresholds[code]
            return float(vals[0]), float(vals[1]), True
            
        # 2. 기본값(AI가 설정한 값 또는 프리셋 값) 가져오기
        target_tp = base_tp if base_tp is not None else self.base_tp
        target_sl = base_sl if base_sl is not None else self.base_sl
        
        # 3. 시장 분위기(Vibe) 및 페이즈 보정 적용
        # [핵심 변경] AI가 할당한 개별 전략(Preset)이나 수동 설정값이 있는 경우, 
        # 이미 해당 시점의 장세가 반영된 수치이므로 '추가 보정'을 생략하여 유저 혼란 방지 (Double-Counting 방지)
        if base_tp is not None or base_sl is not None:
            return round(target_tp, 1), round(target_sl, 1), False

        tp_mod, sl_mod = self.get_vibe_modifiers(kr_vibe)
        
        # 시간 페이즈 보정 합산
        if phase_cfg:
            # [보정] 하락장/방어모드에서 페이즈(P2:CONVERGENCE)에 의한 추가 익절가 하향은 방지 (이미 충분히 타이트함)
            # 단, 손절가는 리스크 관리를 위해 페이즈 보정을 유지함
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
        # 거래 수수료(약 0.23%)와 슬리피지를 고려하여 최종 익절가는 최소 1.0% 이상으로 유지
        if target_tp < 1.0:
            target_tp = 1.0
            
        return round(target_tp, 1), round(target_sl, 1), is_vol_spike
