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

    def get_thresholds(self, code: str, kr_vibe: str, price_data: Optional[dict] = None, phase_cfg: dict = None) -> Tuple[float, float, bool]:
        # 1. 특정 종목 수동 설정(Manual)이 있으면 최우선 적용 (보정 없음)
        if code in self.manual_thresholds:
            vals = self.manual_thresholds[code]
            return float(vals[0]), float(vals[1]), True
            
        # 2. 기본값(AI가 설정한 값 포함) 가져오기
        target_tp, target_sl = self.base_tp, self.base_sl
        
        # 3. 시장 분위기(Vibe)에 따른 실시간 보정 적용
        tp_mod, sl_mod = self.get_vibe_modifiers(kr_vibe)
        
        # 시간 페이즈 보정 합산
        if phase_cfg:
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
                
        return round(target_tp, 1), round(target_sl, 1), is_vol_spike
