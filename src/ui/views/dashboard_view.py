import os
import sys
import time
import threading
import io
import re
from typing import List, Dict, Optional
from datetime import datetime
from src.utils import *
from src.theme_engine import get_cached_themes, get_theme_for_stock
from src.strategy import PRESET_STRATEGIES
from src.logger import trading_log
from src.ui.renderer import VERSION_CACHE

def draw_tui(strategy, dm, cycle_info, prompt_mode=None):
    """시스템의 메인 제어 센터이자 실시간 모니터링 대시보드를 렌더링합니다.

    이 함수는 시황, 자산 현황, 보유 종목, 추천 종목, 실시간 차트 등 모든 핵심 정보를 
    터미널 UI(TUI) 형태로 레이아웃하며, `StringIO` 버퍼를 사용하여 화면 깜박임을 최소화합니다.

    Args:
        strategy: 트레이딩 전략 객체 (시황 분석 및 AI 브리핑 데이터 포함).
        dm: 데이터 매니저 객체 (실시간 지수, 자산, 보유 종목 등 캐시 데이터 참조).
        cycle_info (dict): 현재 루프 주기 정보 (사용되지 않으나 인터페이스 유지용).
        prompt_mode (str, optional): 현재 입력 모드 (STRATEGY 등). 기본값 None.

    Layout:
        1. 헤더 (Header): 시스템 버전, 시장 개장 상태, 현재 VIBE/PHASE, 활성 워커 정보 및 실시간 클락.
        2. 지수 영역 (Indices): 국장/미장 주요 지수, 환율, 비트코인 시세 및 김치 프리미엄.
        3. 전략 브리핑 (AI Briefing): AI가 도출한 현재 시장 진단, 매매 전략, 액션 가이드라인.
        4. 자산/설정 (Asset & Setup): 총자산(수익률), 일일 손익, AI 매수 금액, 종목별 투자 한도, 리스크 한도(Halt 상태).
        5. 보유 종목 (Holdings): 종목명, 수익률, 기술적 지표(전일대비/거래량), 개별 TP/SL 및 전략 라벨.
        6. 실시간 랭킹 (Rankings): 실시간 인기, 거래량 폭발, 테마별 대장주, AI 자동/수동 추천 종목 리스트.
        7. 라이브 차트 (Live Chart): 현재 선택된 종목의 분봉 캔들 차트 (ANSI 그래픽).
        8. 로그 영역 (Logs): 시스템 하단에 고정된 최근 거래 및 작업 로그 (최대 10개).

    Logic:
        - `align_kr`: 한글 폭(2)과 영문 폭(1)을 계산하여 터미널 정렬이 깨지지 않도록 보정합니다.
        - `ANSI 색상`: 수익(빨강), 손실(파랑), 경고(노랑), 특수(보라) 등 상태를 직관적으로 전달합니다.
        - `실시간 갱신`: 데이터 변경 시 버퍼를 다시 쓰고 표준 출력으로 플러시하여 부드러운 UI를 제공합니다.
    """
    if dm.is_full_screen_active: return
    with dm.ui_lock:
        try:
            size = os.get_terminal_size(); tw, th = size.columns, size.lines
        except: tw, th = 110, 30

        buf = io.StringIO()
        if (tw, th) != dm.last_size:
            buf.write("\033[2J\033[3J") # 화면 및 스크롤백 버퍼 전체 소거
            dm.last_size = (tw, th)
        buf.write("\033[H")
    
    now_dt = get_now()
    k_st, u_st = ("OPEN" if is_market_open() else "CLOSED"), ("OPEN" if is_us_market_open() else "CLOSED")
    
    # [수정] 헤더바 레이아웃: 버전/VIBE/작업 정보를 좌측에, 시간은 우측에 배치
    # 버전/상태/작업 정보를 왼쪽에 배치, 시간과 스레드 카운트를 오른쪽 끝에 배치
    is_v = getattr(strategy.api.auth, 'is_virtual', True)
    debug_tag = " [디버그]" if getattr(strategy, "debug_mode", False) else ""
    # [DEV] / [AUTO] 태그: 실행모드 + 자동업데이트 설정 조합
    from src.updater import is_running_as_executable as _is_exe_fn
    _is_exe = _is_exe_fn()
    _auto_upd_cfg = getattr(strategy, 'base_config', {}).get('auto_update', False)
    _dev_tag = "" if _is_exe else " \033[1;97m[DEV]\033[0;44m"
    _auto_tag = " \033[1;92m[AUTO]\033[0;44m" if _auto_upd_cfg else ""
    mode_tag = f" [모의]{debug_tag}{_dev_tag}{_auto_tag}" if is_v else f" [실전]{debug_tag}{_dev_tag}{_auto_tag}"
    # 업데이트 배지: 새 버전 감지 시 실행모드에 따라 구분
    if dm.update_info.get("has_update"):
        if not _is_exe:
            update_tag = f" \033[1;93m🆕NEW v{dm.update_info['latest_version']}\033[0;44m"
        elif _auto_upd_cfg:
            update_tag = f" \033[1;93m🔄v{dm.update_info['latest_version']}\033[0;44m"
        else:
            update_tag = f" \033[1;93m[🆕NEW v{dm.update_info['latest_version']} ▶U]\033[0;44m"
    else:
        update_tag = ""
    # 브로커 정보 확인 (키움 또는 KIS)
    broker_name = "키움" if "kiwoom" in strategy.api.auth.__class__.__name__.lower() else "KIS"
    version_text = f"[AI-VIBE-TRADER ver {VERSION_CACHE}] [{broker_name}]{mode_tag}{update_tag}"
    market_text = f"KR:{k_st} | US:{u_st}"
    status_active = dm.status_msg and (time.time() - dm.status_time < 10)
    busy_msg = dm.global_busy_msg
    busy_str = busy_msg if busy_msg else "대기 중 (IDLE)"

    if status_active:
        is_err = "[ERROR]" in dm.status_msg
        clean_msg = re.sub(r'\x1b\[[0-9;]*m', '', dm.status_msg).replace("[STATUS] ", "").strip()
        # 에러인 경우 빨간색, 일반 상태면 노란색
        msg_color = "\033[91m" if is_err else "\033[93m"
        work_text = f"작업: {busy_str} | {msg_color}{clean_msg}\033[0;44m"
    else:
        work_text = f"작업: {busy_str}"
    
    thread_count = threading.active_count()
    
    # 시간 정보: 년-월-일(요일-한글1자) 시:분:초
    def get_korean_weekday(dt):
        """날짜 객체로부터 한글 요일(월~일) 한 글자를 반환합니다."""
        return ["월", "화", "수", "목", "금", "토", "일"][dt.weekday()]

    def get_time_text(dt, level):
        """너비 제약에 따라 다양한 형식의 시간 문자열을 생성합니다.

        Args:
            dt (datetime): 표시할 시간 객체.
            level (int): 상세도 수준 (0: 전체, 3: 시간만).

        Returns:
            str: 포맷팅된 시간 문자열.
        """
        wd = get_korean_weekday(dt)
        if level == 0: return dt.strftime(f'%Y-%m-%d({wd}) %H:%M:%S')
        if level == 1: return dt.strftime(f'%m-%d({wd}) %H:%M:%S')
        if level == 2: return dt.strftime('%m-%d %H:%M:%S')
        if level == 3: return dt.strftime('%H:%M:%S')
        return ""

    # 시간 정보 최적화 및 레이아웃 조정 (클락 잘림/흔들림 방지)
    # [개선] 우측 시계를 고정폭으로 먼저 확보하고, 좌측 내용을 남은 공간에 채움
    # ANSI 코드를 모두 제거한 순수 시각폭 기준으로 계산하여 계산 오차 원천 방지

    def _ansi_strip(s):
        return re.sub(r'\x1b\[[0-9;]*m', '', s)

    def _vw(s):
        return get_visual_width(_ansi_strip(s))

    time_level = 0
    header_line = ""
    while time_level < 4:
        time_text = get_time_text(now_dt, time_level)
        # 우측 시계: 고정 형식 " (XX) HH:MM:SS " 또는 날짜 포함
        right_side = f" ({thread_count:02d}) {time_text} "
        right_w = _vw(right_side)  # 한글 요일(목/수 등) 2폭 포함하여 시각폭으로 계산

        # 좌측 기본 요소
        base_left = f"{version_text} | {market_text}"
        base_left_w = _vw(base_left)

        # 우측을 위한 공간을 고정으로 확보한 뒤 남은 폭에 작업 정보 배치
        # 구조: [버전 | 시장 | 작업정보 ....패딩....][시계]
        # left_budget = 시계 + 최소패딩(1) 을 제외한 나머지
        left_budget = tw - right_w  # 좌측이 사용 가능한 최대 시각폭

        # 구분자 ' | ' 포함한 작업 정보 가용폭
        sep = " | "
        avail_work_w = left_budget - base_left_w - len(sep) - 1  # 최소 패딩 1

        if avail_work_w >= 10:
            display_work = truncate_log_line(work_text, avail_work_w)
            left_content = f"{base_left}{sep}{display_work}"
        elif left_budget - base_left_w >= 2:
            # 작업 정보 생략, 버전+시장만
            left_content = base_left
        else:
            # 시장 정보까지 생략 (극단적 협소 상황)
            left_content = version_text

        left_w = _vw(left_content)
        # 남은 공간을 스페이스로 채워 시계를 오른쪽 끝에 고정
        pad = max(0, left_budget - left_w)
        header_line = left_content + " " * pad + right_side

        # 최종 시각폭이 tw 이하면 탈출
        if _vw(header_line) <= tw:
            break
        time_level += 1

    if not header_line:
        header_line = align_kr(version_text, tw)

    # ANSI 포함 문자열을 바이트 슬라이싱하면 색상 코드가 깨지므로 절대 [:tw] 금지
    # 대신 시각폭이 tw를 초과하지 않도록 위 while 루프에서 보장
    # 모의 거래인 경우 보라색(45), 실 거래인 경우 파란색(44) 적용
    header_bg = "45" if is_v else "44"
    buf.write(f"\033[{header_bg};37m{header_line}\033[0m\n")
    
    with dm.data_lock:
        def fmt_idx(label, k, price_fmt="{:,.0f}"):
            """지수 정보를 색상과 함께 포맷팅합니다.

            Args:
                label (str): 지수 이름 (KSP 등).
                k (str): 데이터 맵의 키.
                price_fmt (str): 가격 표시 형식.

            Returns:
                str: ANSI 색상이 적용된 지수 정보 문자열.
            """
            d = dm.cached_market_data.get(k)
            if not d: return ""
            color = "\033[91m" if d['rate'] >= 0 else "\033[94m"
            return f"{label} {price_fmt.format(d['price'])}({color}{d['rate']:+0.2f}%\033[0m)"

        # Line 1: 국장 | 미장
        kr_parts = [fmt_idx("KSP", "KOSPI"), fmt_idx("KDQ", "KOSDAQ"), fmt_idx("VIX", "VOSPI", "{:,.1f}")]
        us_parts = [fmt_idx("DOW", "DOW"), fmt_idx("NAS", "NASDAQ"), fmt_idx("SPX", "S&P500")]
        
        kr_str = " ".join([p for p in kr_parts if p])
        us_str = " ".join([p for p in us_parts if p])
        line1 = f" 국장: {kr_str} | 미장: {us_str}"
        buf.write(align_kr(line1, tw-1) + "\n")

        # Line 2: 환율 | 코인 | 선물
        fx_part = fmt_idx("", "FX_USDKRW", "{:,.1f}")
        
        # 코인 로직
        coin_parts = []
        btc_krw = dm.cached_market_data.get("BTC_KRW")
        btc_usd = dm.cached_market_data.get("BTC_USD")
        usd_krw = dm.cached_market_data.get("FX_USDKRW")
        if btc_krw:
            k_color = "\033[91m" if btc_krw['rate'] >= 0 else "\033[94m"
            coin_parts.append(f"K-BTC {btc_krw['price']/10000:,.0f}만({k_color}{btc_krw['rate']:+0.2f}%\033[0m)")
            if btc_usd and usd_krw:
                u_to_k = btc_usd['price'] * usd_krw['price']
                k_prem = (btc_krw['price'] - u_to_k) / u_to_k * 100
                p_color = "\033[91m" if k_prem >= 0 else "\033[94m"
                coin_parts.append(f"김프 {p_color}{k_prem:+0.2f}%\033[0m")
        
        coin_str = " ".join(coin_parts)
        ft_parts = [fmt_idx("NAS.F", "NAS_FUT"), fmt_idx("SPX.F", "SPX_FUT")]
        ft_str = " ".join([p for p in ft_parts if p])
        
        line2 = f" 환율: {fx_part} | 코인: {coin_str} | 선물: {ft_str}"
        buf.write(align_kr(line2, tw-1) + "\n")

        v_c = "\033[91m" if "Bull" in dm.cached_vibe else ("\033[94m" if "Bear" in dm.cached_vibe else "\033[93m")
        panic_txt = " !!! PANIC !!!" if dm.cached_panic else ""
        b_cfg = strategy.bear_config; auto_st = "ON" if b_cfg.get("auto_mode") else "OFF"
        phase = strategy.get_market_phase()
        phase_labels = {
            "P1":   ("🔥", "OFFENSIVE",   "장 초반 공격적 수익 극대화"),
            "P2":   ("🧘", "CONVERGENCE", "횡보장 대응 타이트한 관리"),
            "P3":   ("🏁", "CONCLUSION",  "수익 확정·본전 스탑 발동"),
            "P4":   ("💤", "PREPARATION", "익일 유망주 선취매 준비"),
            "IDLE": ("🌙", "IDLE",        "비장중"),
        }
        p_icon, p_eng, p_kr = phase_labels.get(phase["id"], ("❓", phase["id"], ""))
        
        # [신규] 세션 상태 (시세/동시호가) 추가
        from datetime import time as dtime
        now_dt_inner = get_now()
        now_t_inner = now_dt_inner.time()
        is_regular = dtime(9, 0) <= now_t_inner < dtime(15, 30)
        session_txt = "시세" if is_regular else "동시호가"
        
        phase_txt = f" | PHASE: {p_icon}{p_eng} ({p_kr}) | {session_txt}"
        vibe_desc = f"(하락장 대응[\033[94m{b_cfg.get('min_loss_to_buy')}% / {b_cfg.get('average_down_amount')/10000:,.0f}만/ 자동:{auto_st}\033[0m])" if "Bear" in dm.cached_vibe else ("(\033[91m상승장 수익 극대화 모드 [+3.0%]\033[0m)" if "Bull" in dm.cached_vibe else "(보합장 기본 전략 유지)")
        ai_msg = strategy.analyzer.ai_override_msg if hasattr(strategy.analyzer, "ai_override_msg") else ""
        ai_msg_formatted = f" \033[92m{ai_msg}\033[0m" if "일치" in ai_msg else (f" \033[93m{ai_msg}\033[0m" if ai_msg else "")
        # DEMA 정보 포맷팅
        dema_parts = []
        for name, info in dm.cached_dema_info.items():
            diff = ((info['price'] / info['dema'] - 1) * 100) if info.get('dema', 0) > 0 else 0
            d_c = "\033[91m↑" if diff > 0 else "\033[94m↓"
            dema_parts.append(f"{name}{d_c}\033[0m")
        dema_txt = f" [DEMA: {' '.join(dema_parts)}]" if dema_parts else ""

        status_line = f" VIBE: {v_c}{dm.cached_vibe}\033[0m{panic_txt}{dema_txt} {vibe_desc}{phase_txt}{ai_msg_formatted}"
        buf.write(align_kr(status_line, tw-1) + "\n")
        # 업데이트 알림이 있는 경우 커맨드 바에 U:업데이트 추가
        cmd_update = " | U:업데이트" if dm.update_info.get("has_update") else ""
        buf.write("\033[93m" + align_kr(f" [COMMANDS] 1:매도 | 2:매수 | 3:자동 | 4:추천 | 5:물타기 6:불타기 | AI 7:분석 8:시황 | 9:전략 | 리포트 P:성과 B:보유 D:추천 H:인기 A:AI로그 L:로그 | M:매뉴얼 | S:셋업 | Q:종료{cmd_update}", tw-1) + "\033[0m\n")
        
        # [Task 4] 입력 모드 또는 AI 브리핑 영역 (커맨드 바로 아래 고정 위치)
        effective_mode = prompt_mode or dm.current_prompt_mode
        if dm.is_input_active:
            buf.write(f"\033[K \033[33m{dm.input_prompt}\033[0m{dm.input_buffer}\033[1;33m_\033[0m\n")
            if effective_mode == 'STRATEGY':
                from src.strategy import PRESET_STRATEGIES
                # 전략 리스트를 6개씩 끊어서 2줄로 출력 (총 11개)
                items = sorted(list(PRESET_STRATEGIES.items()))
                for i in range(0, len(items), 6):
                    chunk = items[i:i+6]
                    line = "  ".join([f"\033[93m{k}\033[0m:{v['name']}" for k, v in chunk])
                    buf.write("\033[96m" + align_kr(f"  └ {line}", tw) + "\033[0m\n")
                # 총 4줄 영역 (입력 1 + 전략 2 = 3줄 사용)
                buf.write("\n" * 1)
            else:
                buf.write("\n" * 3) # 영역 보존
        elif strategy.ai_briefing:
            all_lines = [line.strip() for line in strategy.ai_briefing.split('\n') if line.strip()]
            brief_map = {"시장": "", "전략": "", "액션": "", "추천": ""}
            for l in all_lines:
                for k in brief_map.keys():
                    if f"AI[{k}]:" in l: brief_map[k] = l; break
            for k in ["시장", "전략", "액션", "추천"]:
                buf.write("\033[1;95m" + align_kr(f" {brief_map[k] if brief_map[k] else f'AI[{k}]: 데이터 없음'}", tw) + "\033[0m\n")
        else:
            if dm.market_info_status == "실패":
                buf.write("\n")
                buf.write("\033[91m" + align_kr("  [!] 시황 정보 갱신 실패 (Gemini API 오류 또는 네트워크 지연)", tw) + "\033[0m\n")
                buf.write("\033[90m" + align_kr("  └ 시스템 기본 전략 및 TP/SL 감시는 정상 작동 중입니다.", tw) + "\033[0m\n")
                buf.write("\n")
            elif dm.market_info_status == "대기" or strategy.is_analyzing:
                buf.write("\n")
                status_text = "최초 시황 분석 및 AI 전략 수립 중입니다..." if not strategy.first_analysis_attempted else "실시간 시황 및 추천 종목을 심층 분석 중입니다..."
                buf.write("\033[93m" + align_kr(f"  [...] {status_text}", tw) + "\033[0m\n")
                buf.write("\n" * 2)
            else:
                # 시황 데이터가 아예 없는 경우 안내 문구 표시 (분석 중이 아닐 때)
                buf.write("\n")
                buf.write("\033[90m" + align_kr("  [💬] 상세 시황 브리핑 및 AI 전략 조언을 준비 중입니다...", tw) + "\033[0m\n")
                buf.write("\033[90m" + align_kr("      (60분 주기 자동 갱신 또는 8번 키로 수동 갱신 가능)", tw) + "\033[0m\n")
                buf.write("\n")
        buf.write("=" * tw + "\n")
        asset = dm.cached_asset; tot_eval = asset.get('total_asset', 0); tot_prin = asset.get('total_principal', 0)
        tot_rt = ((tot_eval - tot_prin) / tot_prin * 100) if tot_prin > 0 else 0
        tot_color = "\033[91m" if tot_rt > 0 else "\033[94m" if tot_rt < 0 else "\033[0m"
        stk_eval = asset.get('stock_eval', 0); stk_prin = asset.get('stock_principal', 0)
        stk_rt = ((stk_eval - stk_prin) / stk_prin * 100) if stk_prin > 0 else 0
        stk_color = "\033[91m" if stk_rt > 0 else "\033[94m" if stk_rt < 0 else "\033[0m"
        
        from src.logger import trading_log
        
        # [Task 9/10] Asset 및 설정 영역 정렬 개편 (파이프 라인 정렬)
        daily_amts = trading_log.get_daily_amounts()
        tp_cur, sl_cur, _ = strategy.get_dynamic_thresholds("BASE", dm.cached_vibe.lower())
        
        # 수정 표시용 마커
        st_mark = '*' if strategy.is_modified('STRAT') else ' '
        al_mark = '*' if strategy.is_modified('ALGO') else ' '
        be_mark = '*' if strategy.is_modified('BEAR') else ' '
        bu_mark = '*' if strategy.is_modified('BULL') else ' '

        a_cfg = strategy.ai_config
        b_cfg = strategy.bear_config
        u_cfg = strategy.bull_config

        # auto_st_algo 제거 (하단 AI 추천 헤더와 중복 방지)
        auto_st_bear = "\033[93mON\033[0m" if b_cfg.get("auto_mode") else "\033[90mOFF\033[0m"
        auto_st_bull = "\033[93mON\033[0m" if u_cfg.get("auto_mode") else "\033[90mOFF\033[0m"

        # 정렬 폭 정의 (L:라벨, C:컨텐츠)
        L1, C1, L2, C2 = 8, 52, 8, 55

        # [v1.6.3] 컬럼 폭 최적화 (가용 줄이고 BEAR/BULL 늘림) 및 가독성 개선
        # W1:총자산, W2:가용/AI, W3:주식/BEAR, W4:일일/BULL, W5:실현/리스크
        W1, W2, W3, W4, W5 = 30, 22, 27, 30, 29

        # Line 1: ASSET & COSTS
        label_asset = align_kr(" ASSET", L1)
        seed = getattr(strategy, "base_seed_money", 0)
        is_v_mode = getattr(strategy.api.auth, 'is_virtual', True)
        is_kis_broker = 'kis' in strategy.api.auth.__class__.__name__.lower()
        use_seed = seed > 0 and is_kis_broker and is_v_mode
        if use_seed:
            c_prof = tot_eval - seed
            c_rt = (c_prof / seed) * 100
            c_color = "\033[91m" if c_prof > 0 else "\033[94m" if c_prof < 0 else "\033[0m"
            tot_info = f"총자산 {tot_eval:,.0f} ({c_color}{c_rt:+.2f}%\033[0m)"
        else:
            tot_info = f"총자산 {tot_eval:,.0f} ({tot_color}{tot_rt:+.2f}%\033[0m)"
            
        pnl_rate = asset.get('daily_pnl_rate', 0.0)
        pnl_amt = asset.get('daily_pnl_amt', 0.0)
        realized_p = trading_log.get_daily_profit()
        pnl_color = "\033[91m" if pnl_rate > 0 else ("\033[94m" if pnl_rate < 0 else "\033[93m")
        real_color = "\033[91m" if realized_p > 0 else ("\033[94m" if realized_p < 0 else "\033[93m")
        
        trading_fee = trading_log.get_daily_trading_fees()
        ai_costs = dm.cached_ai_costs
        total_ai_cost = sum(ai_costs.values())
        
        avail_cash = asset.get('cash', 0)
        cash_info = f"가용: {avail_cash:,.0f}"
        stk_info = f"주식: {stk_eval:,.0f}"
        daily_info = f"일일: {pnl_color}{pnl_amt:+,.0f} ({pnl_rate:+.2f}%)\033[0m"
        realized_info = f"실현: {real_color}{realized_p:+,.0f}\033[0m"
        
        # [v1.6.2] 비용 2줄 분리 (짤림 방지 및 색상 간섭 해결)
        t_cost_info = f"거래비용: \033[90m-{trading_fee:,.0f}\033[0m"
        line_asset = (f"{label_asset} | {align_kr(tot_info, W1)} | {align_kr(cash_info, W2)} | "
                      f"{align_kr(stk_info, W3)} | {align_kr(daily_info, W4)} | "
                      f"{align_kr(realized_info, W5)} | {t_cost_info}\033[0m")
        buf.write(align_kr(line_asset, tw) + "\n")

        # Line 2: SETUP & RISK
        label_setup = align_kr(" SETUP", L1)
        strat_info = f"TP:\033[91m{tp_cur:+.1f}%\033[0m SL:\033[94m{sl_cur:+.1f}%\033[0m"
        # [] 제거 및 한도 추가
        algo_info = f"AI: {a_cfg.get('amount_per_trade')/10000:,.0f}만/{a_cfg.get('max_investment_per_stock')/10000:,.0f}만"
        bear_info = f"BEAR:[{auto_st_bear}] {b_cfg.get('min_loss_to_buy'):+.1f}% {b_cfg.get('average_down_amount')/10000:,.0f}만/{b_cfg.get('max_investment_per_stock')/10000:,.0f}만"
        bull_info = f"BULL:[{auto_st_bull}] {u_cfg.get('min_profit_to_pyramid'):+.1f}% {u_cfg.get('average_down_amount')/10000:,.0f}만/{u_cfg.get('max_investment_per_stock')/10000:,.0f}만"
        
        halted = strategy.risk_mgr.is_halted
        risk_st = "\033[41;97m!HALTED!\033[0m" if halted else "\033[92mNORMAL\033[0m"
        limit_val = strategy.risk_mgr.max_daily_loss_rate
        risk_info = f"리스크: {risk_st} (한도:-{limit_val}%)"
        
        ai_cost_info = f"AI 비용: \033[90m-{total_ai_cost:,.0f}\033[0m"
        line_setup = (f"{label_setup} | {align_kr(strat_info, W1)} | {align_kr(algo_info, W2)} | "
                      f"{align_kr(bear_info, W3)} | {align_kr(bull_info, W4)} | "
                      f"{align_kr(risk_info, W5)} | {ai_cost_info}\033[0m")
        buf.write(align_kr(line_setup, tw-1) + "\n")
        buf.write("-" * tw + "\n")

        eff_w = tw - 10; w = [max(4, int(eff_w * 0.03)), max(5, int(eff_w * 0.04)), max(15, int(eff_w * 0.15)), max(10, int(eff_w * 0.09)), max(14, int(eff_w * 0.12)), max(10, int(eff_w * 0.08)), max(8, int(eff_w * 0.07)), max(10, int(eff_w * 0.08)), max(18, int(eff_w * 0.12)), max(10, int(eff_w * 0.07)), max(12, int(eff_w * 0.10)), max(6, int(eff_w * 0.05))]
        buf.write("\033[1m" + align_kr(align_kr("NO",w[0])+align_kr("시장",w[1])+align_kr("종목코드/명",w[2])+align_kr("현재가",w[3],'right')+align_kr("전일대비",w[4],'right')+align_kr("평단가",w[5],'right')+align_kr("수량",w[6],'right')+align_kr("평가금액",w[7],'right')+align_kr("수익금(수익률)",w[8],'right')+"  "+align_kr("TP/SL",w[9],'right')+"  "+align_kr("전략",w[10],'center')+align_kr("잔여",w[11],'right'), tw-1) + "\033[0m\n")
        
        f_h = dm.cached_holdings if dm.ranking_filter == "ALL" else [h for h in dm.cached_holdings if get_market_name(h.get('pdno','')) == dm.ranking_filter]
        base_fixed = 23; ranking_target = 10; asset_count = len(f_h); max_h_display = max(1, th - base_fixed - ranking_target)
        if asset_count < max_h_display: max_h_display = asset_count
        ranking_items_count = min(10, max(3, th - base_fixed - max_h_display))
        
        if not f_h: buf.write(align_kr(f"No active {dm.ranking_filter} holdings found.", tw-1, 'center') + "\n")
        else:
            for idx, h in enumerate(f_h[:max_h_display], 1):
                code, name = h.get("pdno", ""), h.get("prdt_name", "Unknown"); info = dm.cached_stock_info.get(code, {"tp": 0, "sl": 0, "spike": False})
                p_a, p_cu = float(h.get('pchs_avg_pric', 0)), float(h.get('prpr', 0)); d_v, d_r = info.get("day_val", float(h.get('prdy_vrss', 0))), info.get("day_rate", float(h.get('prdy_ctrt', 0)))
                pnl_amt = (p_cu - p_a) * float(h.get('hldg_qty', 0)); pnl_rt = float(h.get('evlu_pfls_rt', 0))
                pnl_txt = f"{int(pnl_amt):+,}({abs(pnl_rt):.2f}%)"; preset_label = strategy.get_preset_label(code); rem_txt = "-"
                p_strat = strategy.preset_strategies.get(code)
                if p_strat and p_strat.get('is_manual') and preset_label:
                    preset_label += "(M)"
                if p_strat and p_strat.get('deadline'):
                    try: rem_mins = int((datetime.strptime(p_strat['deadline'], '%Y-%m-%d %H:%M:%S') - get_now()).total_seconds() / 60); rem_txt = f"{rem_mins}M" if rem_mins > 0 else "EXP"
                    except: rem_txt = "ERR"
                # [Task 9] TP/SL 색상 적용 (단위 % 제거)
                tp_txt = f"\033[91m{info['tp']:+.1f}\033[0m"
                sl_txt = f"\033[94m{info['sl']:+.1f}\033[0m"
                
                # [신규] 수급 시그널 생성 (외인/연기금)
                supply_tag = ""
                inv = info.get('investor')
                if inv:
                    f_net, i_net = inv.get('frgn_net_buy', 0), inv.get('inst_net_buy', 0)
                    f_tag = "\033[91mF↑\033[0m" if f_net > 0 else ("\033[94mF↓\033[0m" if f_net < 0 else "")
                    i_tag = "\033[91mI↑\033[0m" if i_net > 0 else ("\033[94mI↓\033[0m" if i_net < 0 else "")
                    if f_tag or i_tag:
                        supply_tag = f" [{f_tag}{'/' if f_tag and i_tag else ''}{i_tag}]"

                name_area = f"[{code}] {name[:(w[2]-15)//2*2]}" + ("*" if info['spike'] else "") + supply_tag
                # [신규] 동시호가(예상체결가) 표시 - (예) 제거 요청 반영
                p_cu_txt = f"{int(p_cu):,}"
                # if info.get('is_antc'):
                #     p_cu_txt += "(예)"
                
                buf.write(align_kr(align_kr(str(idx), w[0]) + align_kr(get_market_name(code), w[1]) + align_kr(name_area, w[2]) + align_kr(p_cu_txt, w[3], 'right') + ("\033[91m" if d_v > 0 else "\033[94m" if d_v < 0 else "") + align_kr(f"{int(d_v):+,}({abs(d_r):.1f}%)" if d_v != 0 else "-", w[4], 'right') + "\033[0m" + align_kr(f"{int(p_a):,}", w[5], 'right') + align_kr(f"{int(float(h.get('hldg_qty', 0))):,}", w[6], 'right') + align_kr(f"{int(float(h.get('evlu_amt', 0))):,}", w[7], 'right') + ("\033[91m" if pnl_amt >= 0 else "\033[94m") + align_kr(pnl_txt, w[8], 'right') + "\033[0m  " + align_kr(f"{tp_txt}/{sl_txt}", w[9], 'right') + "  " + ("\033[96m" if preset_label else "\033[90m") + align_kr(preset_label if preset_label else "표준", w[10], 'center') + "\033[0m" + align_kr(rem_txt, w[11], 'right'), tw-1) + "\n")
            if len(f_h) > max_h_display: buf.write(align_kr(f"... 외 {len(f_h) - max_h_display}종목 생략됨 ...", tw, 'center') + "\n")
        
        buf.write("-" * tw + "\n"); themes = get_cached_themes()
        if themes:
            theme_str = " | ".join([f"{t['name']}({t['count']})" for t in themes[:12]])
            theme_line = f" 테마: {theme_str}"
            while get_visual_width(theme_line) > tw - 2 and " | " in theme_str:
                theme_str = theme_str.rsplit(" | ", 1)[0]
                theme_line = f" 테마: {theme_str}..."
            buf.write("\033[93m" + align_kr(theme_line, tw-1) + "\033[0m\n")
        else:
            buf.write("\n")
        
        y_recs = strategy.yesterday_recs_processed
        if y_recs:
            sorted_recs = sorted(y_recs, key=lambda x: x['change'], reverse=True)[:10]
            y_parts = []
            for r in sorted_recs:
                color = "\033[91m" if r['change'] >= 0 else "\033[94m"
                y_parts.append(f"{r['name']}({color}{r['change']:>+4.1f}%\033[0m)")
            
            # [v1.6.6] 1줄로 복구하되, 이름을 축약하여 최대한 많은 종목(최대 10개) 표시
            y_parts = []
            for r in sorted_recs:
                name = r['name']
                # [개선] 자리 여유가 있는 경우를 고려하여 이름 축약 임계치를 8->14로 상향 (사용자 피드백 반영)
                if get_visual_width(name) > 14:
                    name = align_kr(name, 12).strip() + "..."
                color = "\033[91m" if r['change'] >= 0 else "\033[94m"
                y_parts.append(f"{name}({color}{r['change']:>+4.1f}%\033[0m)")
            
            y_str = " | ".join(y_parts)
            y_line = f" 전일: {y_str}"
            # 여전히 너비가 부족하면 뒤에서부터 하나씩 제거
            while get_visual_width(re.sub(r'\x1b\[[0-9;]*m', '', y_line)) > tw - 2 and " | " in y_str:
                y_parts.pop()
                y_str = " | ".join(y_parts)
                y_line = f" 전일: {y_str}..."
            
            buf.write(align_kr(y_line, tw-1) + "\n")
        else:
            buf.write(align_kr("\033[90m 전일 추천 내역이 없습니다.\033[0m", tw-1) + "\n")

        buf.write("-" * tw + "\n")

        # ` | ` 구분자: 반각문자(1) + 공백 양쪽(1+1) = 시각너비 3, 구분자 3개 = 9
        # [Fix] 우측 끝 1칸 여백 확보 (tw - 9 -> tw - 10)
        eff_w = tw - 10
        col_w1 = max(15, int(eff_w * 0.24))
        col_w2 = max(15, int(eff_w * 0.24))
        col_w3 = max(15, int(eff_w * 0.24))
        col_w4 = max(15, eff_w - col_w1 - col_w2 - col_w3)
        
        full_hot = [g for g in dm.cached_hot_raw if str(g.get('mkt','')).strip().upper() == dm.ranking_filter or dm.ranking_filter == "ALL"]
        # [v1.7.1] 현재 상태(ranking_type)에 따라 거래량 또는 거래대금 데이터를 선택
        raw_source = dm.cached_amt_raw if dm.state.ranking_type == "거래대금" else dm.cached_vol_raw
        full_vol = [l for l in raw_source if str(l.get('mkt','')).strip().upper() == dm.ranking_filter or dm.ranking_filter == "ALL"]
        hot_list = full_hot[:ranking_items_count]
        vol_list = full_vol[:ranking_items_count]
        
        # 테마 상품 구성
        theme_products = []
        themes = get_cached_themes()
        
        pool = []
        seen_codes = set()
        for g in full_hot + full_vol:
            code = g.get('code')
            if code and code not in seen_codes:
                seen_codes.add(code)
                pool.append(g)
                
        theme_groups = {}
        for item in pool:
            t_name = get_theme_for_stock(item['code'], item.get('name', ''))
            if t_name != "기타":
                if t_name not in theme_groups:
                    theme_groups[t_name] = []
                theme_groups[t_name].append(item)
                
        theme_names = [t['name'] for t in themes if t['name'] != "기타"]
        for t_name in theme_names:
            if t_name in theme_groups:
                theme_products.extend(theme_groups[t_name][:2])
            if len(theme_products) >= ranking_items_count:
                break
                
        theme_products = theme_products[:ranking_items_count]
        
        # 그래도 부족하면 기타 포함
        if len(theme_products) < ranking_items_count:
            used_codes = {x['code'] for x in theme_products}
            for item in pool:
                if item['code'] not in used_codes:
                    theme_products.append(item)
                    if len(theme_products) >= ranking_items_count:
                        break
                        
        ai_recs = strategy.ai_recommendations[:ranking_items_count]

        # [v1.6.4] 동적 정렬을 위한 최대 너비 계산 유틸리티
        def get_col_metrics(items):
            """리스트 내 종목들의 이름과 가격 정보의 최대 시각 너비를 계산합니다.

            Args:
                items (list): 종목 딕셔너리 리스트.

            Returns:
                tuple: (최대 이름 너비, 최대 가격/등락률 너비).
            """
            max_n, max_p = 0, 0
            for it in items:
                if not it: continue
                n_w = get_visual_width(it.get('name', 'Unknown'))
                if n_w > max_n: max_n = n_w
                r = float(it.get('rate', 0)); p = int(float(it.get('price', 0)))
                p_w = get_visual_width(f"({p:,}/{r:>+4.1f}%)")
                if p_w > max_p: max_p = p_w
            return max_n, max_p

        m_n_hot, m_p_hot = get_col_metrics(hot_list)
        m_n_vol, m_p_vol = get_col_metrics(vol_list)
        m_n_thm, m_p_thm = get_col_metrics(theme_products)
        m_n_ai, m_p_ai = get_col_metrics(ai_recs)

        def fmt_r(item: Dict, width: int, t_n=0, t_p=0):
            """실시간 랭킹(인기, 거래량, 테마) 종목 한 줄을 포맷팅합니다.

            Args:
                item (dict): 종목 정보.
                width (int): 할당된 너비.
                t_n (int): 이름 최대 너비 (참조용).
                t_p (int): 가격 최대 너비 (참조용).

            Returns:
                str: 포맷팅된 종목 정보 문자열.
            """
            if not item: return " " * width
            r = float(item['rate']); p = int(float(item.get('price', 0))); c = "\033[91m" if r >= 0 else "\033[94m"
            name = item.get('name', 'Unknown'); orig_name = name
            theme_raw = get_theme_for_stock(item['code'], name)
            theme_clean = re.sub(r'\(.*?\)', '', theme_raw).strip()
            theme_clean = theme_clean[:3] # 3글자로 제한
            theme_fmt = align_kr(theme_clean, 6)
            rate_str = f"{r:>+4.1f}%"
            
            price_vw = get_visual_width(f"({p:,}/{rate_str})")
            # 가용 이름 너비 계산 (공백 없이 최대한 이름에 할당)
            max_name_vw = width - 16 - price_vw
            
            # 이름 축약
            d_name = name
            if get_visual_width(d_name) > max_name_vw:
                while get_visual_width(d_name + "..") > max_name_vw and len(d_name) > 1: d_name = d_name[:-1]
                d_name += ".."
            
            # 조립 (이름은 왼쪽, 가격은 오른쪽, 남는 공간은 가운데 띄어쓰기로 채움)
            # [Fix] 우측 끝 1칸 여백 고정 확보
            prefix = f"[{theme_fmt}][{item['code']}]"
            
            # [신규] 동시호가 표시 (중앙 상태에서 확인) - (예) 제거 요청 반영
            p_txt = f"{p:,}"
            # if dm.state.stock_info.get(item['code'], {}).get('is_antc'):
            #     p_txt += "(예)"
            
            spaces = max(0, width - 16 - get_visual_width(d_name) - get_visual_width(f"({p_txt}/{rate_str})"))
            price_txt = f"({p_txt}/{c}{rate_str}\033[0m)"
            
            return f"{prefix}{d_name}{' ' * spaces}{price_txt}"

        def fmt_ai(item, width, t_n=0, t_p=0):
            """AI 추천 종목 한 줄을 [자동]/[수동] 태그와 함께 포맷팅합니다.

            Args:
                item (dict): 종목 정보.
                width (int): 할당된 너비.
                t_n (int): 이름 최대 너비 (참조용).
                t_p (int): 가격 최대 너비 (참조용).

            Returns:
                str: 포맷팅된 AI 추천 종목 문자열.
            """
            if not item: return " " * width
            r = float(item.get('rate', 0)); p = int(float(item.get('price', 0))); c = "\033[91m" if r >= 0 else "\033[94m"
            name = item.get('name', 'Unknown'); orig_name = name
            theme_raw = item.get('theme', '?')
            theme_clean = re.sub(r'\(.*?\)', '', theme_raw).strip()
            theme_clean = theme_clean[:3] # 3글자로 제한
            theme_fmt = align_kr(theme_clean, 6)
            rate_str = f"{r:>+4.1f}%"
            
            # [자동]/[수동] 태그 추가
            is_auto = item.get('auto_eligible', True)
            auto_tag_text = "[자동]" if is_auto else "[수동]"
            auto_tag_color = "\033[92m" if is_auto else "\033[90m"
            
            # 가용 이름 너비 계산 (공백 없이 최대한 이름에 할당)
            base_w = 22
            price_vw = get_visual_width(f"({p:,}/{rate_str})")
            max_name_vw = width - base_w - price_vw
            
            d_name = name
            if get_visual_width(d_name) > max_name_vw:
                while get_visual_width(d_name + "..") > max_name_vw and len(d_name) > 1: d_name = d_name[:-1]
                d_name += ".."
            
            # 조립 (가운데 여백 채우기)
            # [Fix] 우측 끝 1칸 여백 고정 확보
            prefix = f"[{theme_fmt}][{item['code']}]{auto_tag_color}{auto_tag_text}\033[0m"
            
            p_txt = f"{p:,}"
            # if dm.state.stock_info.get(item['code'], {}).get('is_antc'):
            #     p_txt += "(예)"
            
            spaces = max(0, width - base_w - get_visual_width(d_name) - get_visual_width(f"({p_txt}/{rate_str})"))
            price_txt = f"({p_txt}/{c}{rate_str}\033[0m)"
            
            return f"{prefix}{d_name}{' ' * spaces}{price_txt}"

        b_st = "ON" if strategy.auto_ai_trade else "OFF"
        s_st = "ON" if strategy.auto_sell_mode else "OFF"
        ai_mode_label = f"매수:{b_st}|매도:{s_st}"
        buf.write(
            f"\033[1;93m{align_kr('🔥 실시간 인기 종목', col_w1)}\033[0m | "
            f"\033[1;96m{align_kr(f'📊 {dm.state.ranking_type} 상위 종목', col_w2)}\033[0m | "
            f"\033[1;95m{align_kr('💡 테마 종목', col_w3)}\033[0m | "
            f"\033[1;92m{align_kr(f'✨ AI 추천 [{ai_mode_label}]', col_w4)}\033[0m\n"
        )
        buf.write("─" * tw + "\n")
        for i in range(ranking_items_count):
            buf.write(
                f"{fmt_r(hot_list[i] if i < len(hot_list) else None, col_w1, m_n_hot, m_p_hot)} | "
                f"{fmt_r(vol_list[i] if i < len(vol_list) else None, col_w2, m_n_vol, m_p_vol)} | "
                f"{fmt_r(theme_products[i] if i < len(theme_products) else None, col_w3, m_n_thm, m_p_thm)} | "
                f"{fmt_ai(ai_recs[i] if i < len(ai_recs) else None, col_w4, m_n_ai, m_p_ai)}\n"
            )

        # [Phase 3] 실시간 캔들 차트 대시보드 (하단 상시 노출)
        if hasattr(dm, 'cached_chart_data') and dm.cached_chart_data.get("candles"):
            from src.strategy.chart_renderer import ChartRenderer
            chart_h = 7 # 7줄 고정 (공간 효율성)
            chart_txt = ChartRenderer.render_candle_chart(
                dm.cached_chart_data["candles"], 
                width=tw-15, 
                height=chart_h, 
                title=f"LIVE CHART: {dm.cached_chart_data['name']}({dm.cached_chart_data['code']})"
            )
            buf.write("-" * tw + "\n")
            for line in chart_txt.split('\n'):
                buf.write(align_kr(line, tw) + "\n")
    
    rem = th - buf.getvalue().count('\n')
    
    # 로그 최대 출력 너비 = 터미널 너비 - 앞 공백 1칸 - 여유 1칸
    _log_max_w = max(20, tw - 2)
    if rem > 0:
        _raw_last = dm.last_log_msg if dm.last_log_msg and (time.time()-dm.last_log_time<60) else ''
        _last_line = truncate_log_line(_raw_last, _log_max_w) if _raw_last else ''
        buf.write(f"\033[K {_last_line}\n"); rem -= 1
    if rem > 0:
        logs = list(reversed(dm.trading_logs))
        if len(logs) > rem:
            # 보일 수 있는 만큼(rem-1개) 최신 로그를 먼저 출력
            display_count = rem - 1
            skip = len(logs) - display_count
            for i in range(display_count):
                buf.write(f"\033[K {truncate_log_line(logs[i], _log_max_w)}\n")
            buf.write(f"\033[K \033[90m... 💬 {skip}건의 로그 생략됨 ...\033[0m\n")
            rem = 0
        else:
            for tl in logs:
                buf.write(f"\033[K {truncate_log_line(tl, _log_max_w)}\n")
                rem -= 1
    while rem > 0: buf.write("\033[K\n"); rem -= 1
    lines = buf.getvalue().split('\n')
    if lines and not lines[-1]: lines.pop()
    with dm.ui_lock:
        sys.stdout.write("\033[H")
        for i in range(min(th, len(lines))): 
            sys.stdout.write(lines[i] + "\033[K" + ("\n" if i < th-1 and i < len(lines)-1 else ""))
        # [수정] 화면 하단의 남은 영역 소거 (\033[J) 하여 드래그/스크롤 시 잔상 방지
        sys.stdout.write("\033[J")
        sys.stdout.flush()
    buf.close()

