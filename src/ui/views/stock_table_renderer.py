"""3대 리포트(D/B/H) 공통 종목 테이블 렌더링 유틸리티.

코드, 종목명, 현재가, 등락률, PER, PBR, 시총, 거래량, 거래금액, 외국인, 기관
11개 공통 Core 컬럼을 통일된 포맷으로 렌더링합니다.
"""
from src.utils import align_kr, get_visual_width

# ── 공통 Core 컬럼 너비 정의 ──
W_CODE   = 8
W_NAME   = 12
W_PRICE  = 10
W_RATE   = 8
W_PER    = 7
W_PBR    = 6
W_MKTCAP = 10
W_VOL    = 10
W_AMT    = 10
W_FRGN   = 9
W_INST   = 9

# 구분자 " | " = 3자 × 10개 = 30, Core 총 약 129자
CORE_SEPARATOR = " | "


def format_volume(val):
    """거래량/거래금액을 가독성 좋은 축약 문자열로 변환합니다."""
    if not val or val == 0:
        return "-"
    val = float(val)
    if val >= 100_000_000:  # 1억 이상
        return f"{val / 100_000_000:.1f}억"
    elif val >= 10_000:     # 1만 이상
        return f"{val / 10_000:.0f}만"
    else:
        return f"{int(val):,}"


def format_net_buy(val):
    """순매수 수량을 부호 포함 축약 문자열로 변환합니다."""
    if val is None or val == 0:
        return "-"
    val = float(val)
    if abs(val) >= 100_000_000:
        return f"{val / 100_000_000:+.1f}억"
    elif abs(val) >= 10_000:
        return f"{val / 10_000:+.0f}만"
    else:
        return f"{int(val):+,}"


def render_core_header(extra_headers=None):
    """공통 11개 Core 컬럼 헤더 문자열을 반환합니다.

    Args:
        extra_headers (list, optional): Core 컬럼 뒤에 추가할 (이름, 너비, 정렬) 튜플 리스트.

    Returns:
        str: ANSI 볼드가 적용된 헤더 문자열.
    """
    parts = [
        align_kr('코드',   W_CODE),
        align_kr('종목명',  W_NAME),
        align_kr('현재가',  W_PRICE,  'right'),
        align_kr('등락률',  W_RATE,   'right'),
        align_kr('PER',    W_PER,    'right'),
        align_kr('PBR',    W_PBR,    'right'),
        align_kr('시총',   W_MKTCAP, 'center'),
        align_kr('거래량',  W_VOL,    'right'),
        align_kr('거래금액', W_AMT,   'right'),
        align_kr('외국인',  W_FRGN,   'right'),
        align_kr('기관',   W_INST,   'right'),
    ]

    if extra_headers:
        for name, width, al in extra_headers:
            parts.append(align_kr(name, width, al))

    return CORE_SEPARATOR.join(parts)


def render_core_row(code, name, price, rate, per, pbr, mktcap,
                    vol, amt, frgn, inst, extra_columns=None):
    """공통 11개 Core 컬럼 행 문자열을 반환합니다.

    Args:
        code (str): 종목 코드.
        name (str): 종목명.
        price: 현재가.
        rate: 등락률 (%).
        per: PER 값 (문자열 또는 숫자).
        pbr: PBR 값 (문자열 또는 숫자).
        mktcap: 시가총액 (문자열).
        vol: 거래량.
        amt: 거래금액.
        frgn: 외국인 순매수 (주 수량).
        inst: 기관 순매수 (주 수량).
        extra_columns (list, optional): Core 뒤에 추가할 (값 문자열, 너비, 정렬) 튜플 리스트.

    Returns:
        str: ANSI 색상이 적용된 행 문자열.
    """
    # 등락률 색상
    rate_f = float(rate) if rate else 0.0
    rate_color = "\033[91m" if rate_f > 0 else "\033[94m" if rate_f < 0 else ""

    price_str = f"{int(float(price)):,}" if price else "-"
    rate_str = f"{rate_color}{rate_f:+.2f}%\033[0m"

    per_str = str(per) if per and str(per) != "N/A" else "N/A"
    pbr_str = str(pbr) if pbr and str(pbr) != "N/A" else "N/A"

    mktcap_str = str(mktcap).replace(' ', '').replace('시가총액', '').strip() if mktcap and str(mktcap) != "N/A" else "-"

    vol_str = format_volume(vol)
    amt_str = format_volume(amt)

    # 외국인/기관 순매수 색상 (양수: 빨강, 음수: 파랑)
    frgn_val = float(frgn) if frgn else 0
    inst_val = float(inst) if inst else 0
    frgn_str = format_net_buy(frgn_val)
    inst_str = format_net_buy(inst_val)
    frgn_color = "\033[91m" if frgn_val > 0 else "\033[94m" if frgn_val < 0 else ""
    inst_color = "\033[91m" if inst_val > 0 else "\033[94m" if inst_val < 0 else ""

    parts = [
        align_kr(code, W_CODE),
        align_kr(name, W_NAME),
        align_kr(price_str, W_PRICE, 'right'),
        align_kr(rate_str, W_RATE, 'right'),
        align_kr(per_str, W_PER, 'right'),
        align_kr(pbr_str, W_PBR, 'right'),
        align_kr(mktcap_str, W_MKTCAP, 'center'),
        align_kr(vol_str, W_VOL, 'right'),
        align_kr(amt_str, W_AMT, 'right'),
        f"{frgn_color}{align_kr(frgn_str, W_FRGN, 'right')}\033[0m",
        f"{inst_color}{align_kr(inst_str, W_INST, 'right')}\033[0m",
    ]

    if extra_columns:
        for val, width, al in extra_columns:
            parts.append(align_kr(str(val), width, al))

    return CORE_SEPARATOR.join(parts)


def get_core_width():
    """Core 컬럼 11개 + 구분자의 총 시각적 너비를 반환합니다."""
    widths = [W_CODE, W_NAME, W_PRICE, W_RATE, W_PER, W_PBR,
              W_MKTCAP, W_VOL, W_AMT, W_FRGN, W_INST]
    return sum(widths) + len(CORE_SEPARATOR) * (len(widths) - 1)
