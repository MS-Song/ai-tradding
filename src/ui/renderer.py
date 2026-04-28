import os
import sys
import io
import time
import threading
from datetime import datetime
from src.utils import is_market_open, is_us_market_open, get_visual_width, align_kr, ANSI_ESCAPE, get_market_name, get_key_immediate
from src.theme_engine import get_cached_themes

VERSION_CACHE = "Unknown"
try:
    with open("VERSION", "r") as f:
        VERSION_CACHE = f.read().strip()
except: pass

def truncate_log_line(text: str, max_width: int, suffix: str = '…') -> str:
    """ANSI 이스케이프 코드를 보존하면서 시각 너비(한글 2칸) 기준으로 텍스트를 잘라냅니다.
    max_width를 초과하는 경우 suffix(기본 '…')를 붙입니다."""
    import unicodedata
    plain = ANSI_ESCAPE.sub('', text)
    if get_visual_width(plain) <= max_width:
        return text  # 잘라낼 필요 없음

    suffix_w = get_visual_width(suffix)
    target_w = max_width - suffix_w

    # ANSI 토큰 단위로 순회하며 시각 너비를 누적
    result = []
    cur_w = 0
    i = 0
    while i < len(text):
        m = ANSI_ESCAPE.match(text, i)
        if m:
            # ANSI 시퀀스는 너비 0 — 그대로 보존
            result.append(m.group())
            i = m.end()
        else:
            ch = text[i]
            if ord(ch) < 128:
                cw = 1
            elif unicodedata.east_asian_width(ch) in ['W', 'F', 'A']:
                cw = 2
            else:
                cw = 1
            if cur_w + cw > target_w:
                break
            result.append(ch)
            cur_w += cw
            i += 1

    return ''.join(result) + '\033[0m' + suffix

def draw_tui(strategy, dm, cycle_info, prompt_mode=None):
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
    
    now_dt = datetime.now()
    k_st, u_st = ("OPEN" if is_market_open() else "CLOSED"), ("OPEN" if is_us_market_open() else "CLOSED")
    
    # [수정] 헤더바 레이아웃: 버전/VIBE/작업 정보를 좌측에, 시간은 우측에 배치
    # 버전/상태/작업 정보를 왼쪽에 배치, 시간과 스레드 카운트를 오른쪽 끝에 배치
    is_v = getattr(strategy.api.auth, 'is_virtual', True)
    debug_tag = " [디버그]" if getattr(strategy, "debug_mode", False) else ""
    mode_tag = f" [모의]{debug_tag}" if is_v else f" [실전]{debug_tag}"
    update_tag = f" \033[1;93m[NEW v{dm.update_info['latest_version']}]\033[0;44m" if dm.update_info.get("has_update") else ""
    version_text = f"[AI TRADING SYSTEM ver {VERSION_CACHE}]{mode_tag}{update_tag}"
    market_text = f"KR:{k_st} | US:{u_st}"
    status_active = dm.status_msg and (time.time() - dm.status_time < 10)
    busy_msg = dm.global_busy_msg
    busy_str = busy_msg if busy_msg else "-"

    if status_active:
        import re
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
        return ["월", "화", "수", "목", "금", "토", "일"][dt.weekday()]

    def get_time_text(dt, level):
        wd = get_korean_weekday(dt)
        if level == 0: return dt.strftime(f'%Y-%m-%d({wd}) %H:%M:%S')
        if level == 1: return dt.strftime(f'%m-%d({wd}) %H:%M:%S')
        if level == 2: return dt.strftime('%m-%d %H:%M:%S')
        if level == 3: return dt.strftime('%H:%M:%S')
        return ""

    # 시간 정보 최적화 및 레이아웃 조정 (클락 잘림 방지)
    time_level = 0
    header_line = ""
    while time_level < 4:
        time_text = get_time_text(now_dt, time_level)
        right_side = f" ({thread_count:02d}) {time_text} "
        right_w = get_visual_width(right_side)
        
        # 왼쪽 기본 요소: 버전 | 시장상태
        base_left = f"{version_text} | {market_text}"
        base_left_w = get_visual_width(base_left)
        
        # 작업 정보를 포함할 여유 공간 계산 (최소 1칸 여백 보장)
        # 구조: [버전 | 시장] | [작업내용] (공백) [시간]
        # 중간 구분자 ' | ' 너비 3 포함
        avail_work_w = tw - base_left_w - 3 - right_w - 1
        
        if avail_work_w >= 10:
            # 작업 정보를 표시할 공간이 어느 정도 있음
            display_work = truncate_log_line(work_text, avail_work_w)
            left_side = f"{base_left} | {display_work}"
            left_w = get_visual_width(left_side)
            spaces = " " * max(1, tw - left_w - right_w)
            header_line = left_side + spaces + right_side
        else:
            # 작업 정보 표시 공간이 너무 부족하면 작업 정보 생략 시도
            left_side = base_left
            left_w = get_visual_width(left_side)
            if left_w + 1 + right_w <= tw:
                spaces = " " * (tw - left_w - right_w)
                header_line = left_side + spaces + right_side
            else:
                # 시장 정보까지 생략 (극단적 상황)
                left_side = version_text
                left_w = get_visual_width(left_side)
                spaces = " " * max(1, tw - left_w - right_w)
                header_line = left_side + spaces + right_side
        
        if get_visual_width(header_line) <= tw:
            break
        time_level += 1
    
    if not header_line:
        header_line = align_kr(version_text, tw)[:tw]
    
    header_line = header_line[:tw]
    # 모의 거래인 경우 보라색(45), 실 거래인 경우 파란색(44) 적용
    header_bg = "45" if is_v else "44"
    buf.write(f"\033[{header_bg};37m{header_line}\033[0m\n")
    
    with dm.data_lock:
        import re
        def fmt_idx(label, k, price_fmt="{:,.0f}"):
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
        buf.write(align_kr(line1, tw) + "\n")

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
        buf.write(align_kr(line2, tw) + "\n")

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
        phase_txt = f" | PHASE: {p_icon}{p_eng} ({p_kr})"
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
        buf.write(align_kr(status_line, tw) + "\n")
        # 업데이트 알림이 있는 경우 커맨드 바에 U:업데이트 추가
        cmd_update = " | U:업데이트" if dm.update_info.get("has_update") else ""
        buf.write("\033[93m" + align_kr(f" [COMMANDS] 1:매도 | 2:매수 | 3:자동 | 4:추천 | 5:물타기 6:불타기 | AI 7:분석 8:시황 | 9:전략 | 리포트 P:성과 B:보유 D:추천 H:인기 A:AI로그 L:로그 | M:매뉴얼 | S:셋업 | Q:종료{cmd_update}", tw) + "\033[0m\n")
        
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

        # Line 1: ASSET & RISK 통합 (사용자 피드백 반영: 순서 및 레이아웃 최적화)
        label = align_kr(" ASSET", L1)
        seed = getattr(strategy, "base_seed_money", 0)
        if seed > 0:
            c_prof = tot_eval - seed
            c_rt = (c_prof / seed) * 100
            c_color = "\033[91m" if c_prof > 0 else "\033[94m" if c_prof < 0 else "\033[0m"
            tot_info = f"총자산 {tot_eval:,.0f} ({c_color}{c_rt:+.2f}%\033[0m) (입금: {seed:,.0f})"
        else:
            tot_info = f"총자산 {tot_eval:,.0f} ({tot_color}{tot_rt:+.2f}%\033[0m)"
            
        pnl_rate = asset.get('daily_pnl_rate', 0.0)
        pnl_amt = asset.get('daily_pnl_amt', 0.0)
        realized_p = trading_log.get_daily_profit()
        pnl_color = "\033[91m" if pnl_rate > 0 else ("\033[94m" if pnl_rate < 0 else "\033[93m")
        real_color = "\033[91m" if realized_p > 0 else ("\033[94m" if realized_p < 0 else "\033[93m")
        
        halted = strategy.risk_mgr.is_halted
        risk_st = "\033[41;97m!HALTED!\033[0m" if halted else "\033[92mNORMAL\033[0m"
        
        d0_c, d2_c = asset.get('d0_cash', 0), asset.get('d2_cash', 0)
        d2_color = "\033[91m" if d2_c < 0 else ("\033[94m" if d0_c != d2_c else "")
        cash_info = f"가용(D+0): {d0_c:,.0f} | 정산(D+2): {d2_color}{d2_c:,.0f}\033[0m"
        stk_info = f"주식: {stk_eval:,.0f}"
        
        # 일일: 전체 변동(원금 대비 ROI) + 실현 손익 병기
        daily_info = f"{pnl_color}{pnl_amt:+,.0f}원 ({pnl_rate:+.2f}%)\033[0m | 실현: {real_color}{realized_p:+,.0f}원\033[0m"
        
        # [순서 변경] 총자산 -> 예수금 -> 주식 -> 일일 -> 리스크
        limit_val = strategy.risk_mgr.max_daily_loss_rate
        risk_active_info = f"{risk_st} (한도:-{limit_val}%)"
        line_combined = f"{label} | {tot_info} | {cash_info} | {stk_info} | 일일: {daily_info} | 리스크: {risk_active_info}"
        buf.write(align_kr(line_combined, tw) + "\n")

        # Line 2: STRAT + ALGO
        strat_label = align_kr(f"{st_mark}STRAT", L1)
        strat_info = f"TP:\033[91m{strategy.base_tp:+.1f}%\033[0m(\033[91m{tp_cur:+.1f}%\033[0m) SL:\033[94m{strategy.base_sl:+.1f}%\033[0m(\033[94m{sl_cur:+.1f}%\033[0m)"
        algo_label = align_kr(f"{al_mark}ALGO", L2)
        algo_info = f"{a_cfg.get('amount_per_trade'):,}원/{a_cfg.get('max_investment_per_stock'):,}원 (누적:{daily_amts['ALGO']:,.0f})"
        costs = dm.cached_ai_costs
        cost_info = f" | AI 비용(추정): \033[96mgemini({costs.get('gemini',0):,.0f}원) groq({costs.get('groq',0):,.0f}원)\033[0m"
        line_strat = f"{strat_label} | {align_kr(strat_info, C1)} | {algo_label} | {algo_info}{cost_info}"
        buf.write(align_kr(line_strat, tw) + "\n")

        # Line 3: BEAR + BULL
        bear_label = align_kr(f"{be_mark}BEAR", L1)
        bear_info = f"[{auto_st_bear}] TRG:\033[94m{b_cfg.get('min_loss_to_buy'):+.1f}%\033[0m {b_cfg.get('average_down_amount'):,}원/{b_cfg.get('max_investment_per_stock'):,}원 (누적:{daily_amts['BEAR']:,.0f})"
        bull_label = align_kr(f"{bu_mark}BULL", L2)
        bull_info = f"[{auto_st_bull}] TRG:\033[91m+{u_cfg.get('min_profit_to_pyramid'):.1f}%\033[0m {u_cfg.get('average_down_amount'):,}원/{u_cfg.get('max_investment_per_stock'):,}원 (누적:{daily_amts['BULL']:,.0f})"
        line_bear = f"{bear_label} | {align_kr(bear_info, C1)} | {bull_label} | {bull_info}"
        buf.write(align_kr(line_bear, tw) + "\n")
        buf.write("-" * tw + "\n")

        eff_w = tw - 4; w = [max(4, int(eff_w * 0.03)), max(5, int(eff_w * 0.04)), max(15, int(eff_w * 0.15)), max(10, int(eff_w * 0.09)), max(14, int(eff_w * 0.12)), max(10, int(eff_w * 0.08)), max(8, int(eff_w * 0.07)), max(10, int(eff_w * 0.08)), max(18, int(eff_w * 0.12)), max(10, int(eff_w * 0.07)), max(12, int(eff_w * 0.10)), max(6, int(eff_w * 0.05))]
        buf.write("\033[1m" + align_kr(align_kr("NO",w[0])+align_kr("시장",w[1])+align_kr("종목코드/명",w[2])+align_kr("현재가",w[3],'right')+align_kr("전일대비",w[4],'right')+align_kr("평단가",w[5],'right')+align_kr("수량",w[6],'right')+align_kr("평가금액",w[7],'right')+align_kr("수익금(수익률)",w[8],'right')+"  "+align_kr("TP/SL",w[9],'right')+"  "+align_kr("전략",w[10],'center')+align_kr("잔여",w[11],'right'), tw) + "\033[0m\n")
        
        f_h = dm.cached_holdings if dm.ranking_filter == "ALL" else [h for h in dm.cached_holdings if get_market_name(h.get('pdno','')) == dm.ranking_filter]
        base_fixed = 23; ranking_target = 10; asset_count = len(f_h); max_h_display = max(1, th - base_fixed - ranking_target)
        if asset_count < max_h_display: max_h_display = asset_count
        ranking_items_count = min(10, max(3, th - base_fixed - max_h_display))
        
        if not f_h: buf.write(align_kr(f"No active {dm.ranking_filter} holdings found.", tw, 'center') + "\n")
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
                    try: rem_mins = int((datetime.strptime(p_strat['deadline'], '%Y-%m-%d %H:%M:%S') - datetime.now()).total_seconds() / 60); rem_txt = f"{rem_mins}M" if rem_mins > 0 else "EXP"
                    except: rem_txt = "ERR"
                # [Task 9] TP/SL 색상 적용 (단위 % 제거)
                tp_txt = f"\033[91m{info['tp']:+.1f}\033[0m"
                sl_txt = f"\033[94m{info['sl']:+.1f}\033[0m"
                
                buf.write(align_kr(align_kr(str(idx), w[0]) + align_kr(get_market_name(code), w[1]) + align_kr(f"[{code}] {name[:(w[2]-10)//2*2]}" + (" *" if info['spike'] else ""), w[2]) + align_kr(f"{int(p_cu):,}", w[3], 'right') + ("\033[91m" if d_v > 0 else "\033[94m" if d_v < 0 else "") + align_kr(f"{int(d_v):+,}({abs(d_r):.1f}%)" if d_v != 0 else "-", w[4], 'right') + "\033[0m" + align_kr(f"{int(p_a):,}", w[5], 'right') + align_kr(f"{int(float(h.get('hldg_qty', 0))):,}", w[6], 'right') + align_kr(f"{int(float(h.get('evlu_amt', 0))):,}", w[7], 'right') + ("\033[91m" if pnl_amt >= 0 else "\033[94m") + align_kr(pnl_txt, w[8], 'right') + "\033[0m  " + align_kr(f"{tp_txt}/{sl_txt}", w[9], 'right') + "  " + ("\033[96m" if preset_label else "\033[90m") + align_kr(preset_label if preset_label else "표준", w[10], 'center') + "\033[0m" + align_kr(rem_txt, w[11], 'right'), tw) + "\n")
            if len(f_h) > max_h_display: buf.write(align_kr(f"... 외 {len(f_h) - max_h_display}종목 생략됨 ...", tw, 'center') + "\n")
        
        buf.write("-" * tw + "\n"); themes = get_cached_themes()
        if themes:
            theme_str = " | ".join([f"{t['name']}({t['count']})" for t in themes[:12]])
            theme_line = f" 테마: {theme_str}"
            while get_visual_width(theme_line) > tw - 2 and " | " in theme_str:
                theme_str = theme_str.rsplit(" | ", 1)[0]
                theme_line = f" 테마: {theme_str}.."
            buf.write("\033[93m" + align_kr(theme_line, tw) + "\033[0m\n")
        else:
            buf.write("\n")
        
        y_recs = strategy.yesterday_recs_processed
        if y_recs:
            sorted_recs = sorted(y_recs, key=lambda x: x['change'], reverse=True)[:10]
            y_parts = []
            for r in sorted_recs:
                color = "\033[91m" if r['change'] >= 0 else "\033[94m"
                y_parts.append(f"{r['name']}({color}{r['change']:>+4.1f}%\033[0m)")
            
            y_str = " | ".join(y_parts)
            y_line = f" 전일: {y_str}"
            # ANSI 제거 후 너비 체크
            import re
            while get_visual_width(re.sub(r'\x1b\[[0-9;]*m', '', y_line)) > tw - 2 and " | " in y_str:
                y_parts.pop()
                y_str = " | ".join(y_parts)
                y_line = f" 전일: {y_str}.."
            buf.write(align_kr(y_line, tw) + "\n")
        else:
            buf.write(align_kr("\033[90m 전일 추천 내역이 없습니다.\033[0m", tw) + "\n")

        buf.write("-" * tw + "\n")

        # ` ｜ ` 구분자: 전각문자(2) + 공백 양쪽(1+1) = 시각너비 4, 구분자 2개 = 8
        col_w = max(20, (tw - 8) // 3)
        hot_list = [g for g in dm.cached_hot_raw if str(g.get('mkt','')).strip().upper() == dm.ranking_filter or dm.ranking_filter == "ALL"][:ranking_items_count]
        vol_list = [l for l in dm.cached_vol_raw if str(l.get('mkt','')).strip().upper() == dm.ranking_filter or dm.ranking_filter == "ALL"][:ranking_items_count]
        ai_recs = strategy.ai_recommendations[:ranking_items_count]

        def fmt_r(item, width=col_w):
            if not item: return " " * width
            r = float(item['rate']); p = int(float(item.get('price', 0))); c = "\033[91m" if r >= 0 else "\033[94m"
            name = item.get('name', 'Unknown')
            orig_name = name
            from src.theme_engine import get_theme_for_stock
            theme = get_theme_for_stock(item['code'], name)[0:4]
            rate_str = f"{r:>+4.1f}%"
            # ANSI 제외 plain 너비로 축약 여부 결정
            plain = f"({theme})[{item['code']}] {name} ({p:,}/{rate_str})"
            while get_visual_width(plain) > width and len(name) > 1:
                name = name[:-1]
                plain = f"({theme})[{item['code']}] {name}.. ({p:,}/{rate_str})"
            suffix = ".." if name != orig_name else ""
            txt = f"({theme})[{item['code']}] {name}{suffix} ({p:,}/{c}{rate_str}\033[0m)"
            return align_kr(txt, width)

        def fmt_ai(item, width=col_w):
            if not item: return " " * width
            r = float(item.get('rate', 0)); p = int(float(item.get('price', 0))); c = "\033[91m" if r >= 0 else "\033[94m"
            name = item.get('name', 'Unknown')
            orig_name = name
            theme = item.get('theme', '?')[0:4]
            rate_str = f"{r:>+4.1f}%"
            # ANSI 제외 plain 너비로 축약 여부 결정
            plain = f"({theme})[{item['code']}] {name} ({p:,}/{rate_str})"
            while get_visual_width(plain) > width and len(name) > 1:
                name = name[:-1]
                plain = f"({theme})[{item['code']}] {name}.. ({p:,}/{rate_str})"
            suffix = ".." if name != orig_name else ""
            txt = f"({theme})[{item['code']}] {name}{suffix} ({p:,}/{c}{rate_str}\033[0m)"
            return align_kr(txt, width)

        b_st = "ON" if strategy.auto_ai_trade else "OFF"
        s_st = "ON" if strategy.auto_sell_mode else "OFF"
        ai_mode_label = f"매수:{b_st}|매도:{s_st}"
        buf.write(
            f"\033[1;93m{align_kr('🔥 실시간 인기 종목', col_w)}\033[0m ｜ "
            f"\033[1;96m{align_kr('📊 거래량 상위 종목', col_w)}\033[0m ｜ "
            f"\033[1;92m{align_kr(f'✨ AI 추천 [{ai_mode_label}]', col_w)}\033[0m\n"
        )
        buf.write("─" * tw + "\n")
        for i in range(ranking_items_count):
            buf.write(
                f"{fmt_r(hot_list[i] if i < len(hot_list) else None)} ｜ "
                f"{fmt_r(vol_list[i] if i < len(vol_list) else None)} ｜ "
                f"{fmt_ai(ai_recs[i] if i < len(ai_recs) else None)}\n"
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
        for i in range(min(th, len(lines))): sys.stdout.write(lines[i] + "\033[K" + ("\n" if i < th-1 and i < len(lines)-1 else ""))
        sys.stdout.flush()
    buf.close()

def draw_manual_page():
    current_tab = 1
    total_tabs = 5
    
    while True:
        try:
            size = os.get_terminal_size()
            tw, th = size.columns, size.lines
        except:
            tw, th = 80, 24
        buf = io.StringIO(); buf.write("\033[H\033[2J")
        buf.write("\033[46;37m" + align_kr(" [KIS-VIBE-TRADER SYSTEM MANUAL] ", tw, 'center') + "\033[0m\n")
        
        # 탭 메뉴 바
        tabs = [
            (1, "1.단축키"),
            (2, "2.페이즈&전략"),
            (3, "3.매매엔진"),
            (4, "4.리스크관리"),
            (5, "5.설정&팁"),
        ]
        tab_parts = []
        for tid, tname in tabs:
            sel = "\033[7m" if current_tab == tid else ""
            tab_parts.append(f"{sel} {tname} \033[0m")
        menu_bar = " | ".join(tab_parts)
        buf.write(align_kr(f" {menu_bar} ", tw, 'center') + "\n")
        buf.write("=" * tw + "\n")
        
        # 가용 높이 계산 (헤더 3줄 + 하단 안내 3줄 제외)
        avail = max(10, th - 6)
        lines_written = 0
        
        def w(text):
            nonlocal lines_written
            if lines_written < avail:
                buf.write(text + "\n")
                lines_written += 1
        
        if current_tab == 1:
            # ── 단축키 가이드 ──
            w("\033[1;93m [단축키 전체 맵]\033[0m")
            w("-" * tw)
            w("\033[1m 분류       | 키  | 기능                        | 입력 형식 / 설명\033[0m")
            w("-" * tw)
            w(" \033[96m매매 조작\033[0m  | \033[1m1\033[0m  | 수동 매도                   | 번호 수량 가격 (가격 생략=시장가)")
            w("           | \033[1m2\033[0m  | 수동 매수                   | 종목코드 수량 가격")
            w("           | \033[1m3\033[0m  | TP/SL 수정                  | 번호 TP SL (번호 R=초기화, 번호없이 TP SL=전체변경)")
            w("           | \033[1m4\033[0m  | AI 추천 설정                | 금액 한도 자동(y/n)")
            w("           | \033[1m5\033[0m  | 물타기(BEAR) 설정           | 트리거% 금액 한도 자동(y/n)")
            w("           | \033[1m6\033[0m  | 불타기(BULL) 설정           | 트리거% 금액 한도 자동(y/n)")
            w("-" * tw)
            w(" \033[92mAI 분석\033[0m   | \033[1m7\033[0m  | 개별 종목 심층분석           | 보유종목 번호 또는 6자리 코드")
            w("           | \033[1m8\033[0m  | 시황 분석 + AI 추천 갱신     | (입력 없음, 자동 실행)")
            w("           | \033[1m9\033[0m  | 프리셋 전략 할당            | 번호 → 전략ID (엔터=AI자동, 00=표준복귀)")
            w("-" * tw)
            w(" \033[95m리포트\033[0m    | \033[1mP\033[0m  | 성과 대시보드               | 수익TOP10, 손실TOP10, 금일투자성과, 투자적중 복기")
            w("           | \033[1mB\033[0m  | 보유 종목 진단              | AI 포트폴리오 매니저 진단 의견")
            w("           | \033[1mD\033[0m  | 추천 종목 상세              | AI 추천 10종목 입체 분석")
            w("           | \033[1mH\033[0m  | 인기 테마 분석              | 실시간 인기 TOP10 테마 트렌드")
            w("           | \033[1mA\033[0m  | AI 로그                    | 매수거절, 종목교체, 전략근거 이력")
            w("           | \033[1mL\033[0m  | 거래/설정 로그              | 최근 거래 내역 + 설정 변경 히스토리")
            w("-" * tw)
            w(" \033[93m시스템\033[0m    | \033[1mM\033[0m  | 사용자 매뉴얼 (현재 화면)    | 탭 전환으로 모든 기능 설명 확인")
            w("           | \033[1mS\033[0m  | 환경 설정 (셋업)            | API키, 자동매매, 디버그모드 등 전체 설정")
            w("           | \033[1mU\033[0m  | 자동 업데이트               | GitHub 최신 릴리스 감지 및 자동 재기동")
            w("           | \033[1mQ\033[0m  | 프로그램 종료               | 즉시 안전 종료")
        
        elif current_tab == 2:
            # ── 시장 페이즈 & 전략 ──
            w("\033[1;93m [시장 페이즈 (Market Phase) — 시간대별 자동 전략 보정]\033[0m")
            w("-" * tw)
            w(" \033[91m🔥 P1 OFFENSIVE  (09:00~10:00)\033[0m  장 초반 변동성 극대화")
            w("    TP \033[91m+2.0%\033[0m 상향 | SL \033[94m-1.0%\033[0m 완화 (단, 하락/방어장 시 손절 완화 제외)")
            w("    → 적극적 수익 추구 구간. 큰 움직임을 활용하여 익절 기회 극대화")
            w("")
            w(" \033[92m🧘 P2 CONVERGENCE (10:00~14:30)\033[0m  시장 수렴 안정화")
            w("    TP \033[94m-1.0%\033[0m 보수화 | SL \033[94m-1.0%\033[0m 타이트 관리")
            w("    → 횡보장 대응. 리스크를 줄이며 안정적 운영")
            w("")
            w(" \033[93m🏁 P3 CONCLUSION  (14:30~15:10)\033[0m  당일 수익 확정 단계")
            w("    보정 없음 | 수익률 ≥+0.5% 종목 50% 분할 매도")
            w("    → 분할 매도 후 잔여 물량 손절선을 +0.2%(본전)로 상향하여 추가 수익 추종")
            w("")
            w(" \033[96m💤 P4 PREPARATION (15:10~15:30)\033[0m  익일 준비 / AI 장마감 판단")
            w("    ① 종가베팅 : 추천 1~3순위 중 1종목 선별 매수 (기보유 시 시간 갱신하여 청산 방어)")
            w("    ② AI 장마감: 잔여 종목별 [펀더멘털+뉴스+수익률] 분석 → 불확실하면 Sell")
            w("    → 단, 종가베팅 확정 종목 및 당일 매수 종목은 P4 청산 로직에서 안전하게 보호됨")
            w("")
            w("-" * tw)
            w("\033[1;93m [VIBE 시장 장세별 TP/SL 실시간 보정 (Current Delta)]\033[0m")
            w("-" * tw)
            w("\033[1m  장세        | 익절 보정  | 손절 보정  | 설명\033[0m")
            w("  \033[91mBull(상승)\033[0m  | \033[91m+3.0%\033[0m     | \033[92m+1.0%\033[0m     | 수익 극대화, 손절 완화")
            w("  \033[94mBear(하락)\033[0m  | \033[94m-2.0%\033[0m     | \033[94m-2.0%\033[0m     | 짧은 익절, 리스크 강화")
            w("  \033[90mDefensive\033[0m   | \033[94m-3.0%\033[0m     | \033[94m-3.0%\033[0m     | 극보수적 자산 보호 모드")
            w("  Neutral     |  0.0%     |  0.0%     | 기본 전략 유지")
            w("")
            w("\033[1;93m [프리셋 전략 엔진 (9번 키)]\033[0m")
            w("-" * tw)
            w("  KIS 10대 공식 전략을 AI가 동적 TP/SL과 함께 자동 매칭")
            w("  01:골든크로스 02:모멘텀 03:52주신고가 04:연속상승 05:이격도")
            w("  06:돌파실패 07:강한종가 08:변동성확장 09:평균회귀 10:추세필터 00:표준복귀")
            w("  → 엔터(빈 입력) 시 AI가 최적 전략을 자동 선택하여 적용")
        
        elif current_tab == 3:
            # ── 매매 엔진 ──
            w("\033[1;93m [물타기 엔진 (BEAR — 하락 대응, 5번 키)]\033[0m")
            w("-" * tw)
            w("  \033[1m트리거\033[0m   : 수익률이 [현재 손절선(SL) + 1.0%] 이하 & 현재가 < 매입평단")
            w("  \033[1m추가조건\033[0m : 직전 물타기가 대비 \033[94m-2.0%\033[0m 이상 추가 하락 시에만 집행")
            w("  \033[1m손절유예\033[0m : 물타기 직후 \033[93m30분\033[0m 동안 즉각 손절 유예")
            w("    └ 긴급 조건: 손실률 ≤ SL-1% | 글로벌패닉 | Defensive전환 | P4 → 즉시손절")
            w("  \033[1m쿨다운\033[0m   : 손절 후 \033[91m2시간\033[0m 이내 자동 물타기 재진입 금지 (핑퐁 방지)")
            w("  \033[1m가이드\033[0m   : 🔵 BEAR 라인 (청색 계열)")
            w("")
            w("\033[1;93m [불타기 엔진 (BULL — 상승 추종, 6번 키)]\033[0m")
            w("-" * tw)
            w("  \033[1m트리거\033[0m   : 수익률 ≥ [min_profit_to_pyramid]% & 현재가 > 매입평단")
            w("    └ TP 충돌 방지: 불타기 트리거는 항상 \033[91m익절선(TP) - 1.0%\033[0m 이하로 자동 제한")
            w("  \033[1m추가조건\033[0m : 직전 불타기가 대비 \033[91m+2.0%\033[0m 이상 추가 상승 시에만 허용")
            w("  \033[1m작동조건\033[0m : \033[91mBull(상승장)\033[0m 또는 \033[93m거래량 폭발(vol_spike)\033[0m 시에만 작동")
            w("  \033[1m쿨다운\033[0m   : 익절 후 \033[91m2시간\033[0m 이내 자동 불타기 재진입 금지")
            w("  \033[1m가이드\033[0m   : 🔴 BULL 라인 (적색 계열)")
            w("")
            w("\033[1;93m [AI 자율 매매 (8번/3번 키)]\033[0m")
            w("-" * tw)
            w("  \033[1m매수\033[0m: P1~P2(09:00~14:30)에만 신규 진입. 당일등락률 -1.5%~+8.0% 구간만 진입")
            w("  \033[1m매도\033[0m: 설정(S:셋업)에서 AI자율매도(AUTO) ON 시 선제적 포지션 정리 가능")
            w("  \033[1m보호\033[0m: 매수 후 1시간 이내 AI 매도 차단 (긴급: 패닉/Defensive 시 즉시 매도)")
            w("  \033[1m한도\033[0m: 최대 보유 \033[91m8종목\033[0m | 초과 시 AI가 기존 vs 후보 비교 → 교체 매매 실행")
            w("  \033[1m컨펌\033[0m: 매수 직전 AI가 2차 분석(기술적지표+뉴스) → 최종 승인/거절 결정")
            w("    └ 거절 시 해당 종목 1시간 매수 제외 → 자동 해제 후 재평가")
        
        elif current_tab == 4:
            # ── 리스크 관리 & 안전장치 ──
            w("\033[1;93m [익절/손절 쿨다운 시스템]\033[0m")
            w("-" * tw)
            w("  \033[1m익절 쿨다운\033[0m: 부분 익절 시 해당 종목 \033[93m1시간\033[0m 추가 익절 제한")
            w("    └ 리셋: 불타기/물타기 발생 시 쿨다운 자동 리셋 → 즉시 익절 허용")
            w("    └ 긴급 바이패스: 수익률 ≥ TP+3% | 거래량폭발+TP+1.5% | P4+수익권")
            w("  \033[1m손절 쿨다운\033[0m: 없음 (즉시 실행). 단, 물타기 직후 30분 유예")
            w("  \033[1m재진입 쿨다운\033[0m: 익절/손절 후 \033[91m2시간\033[0m 물타기/불타기 금지 (핑퐁 방지)")
            w("")
            w("\033[1;93m [글로벌 패닉 차단]\033[0m")
            w("-" * tw)
            w("  미국 지수 \033[91m-1.5%\033[0m 이하 또는 비트코인 \033[91m-3.5%\033[0m 급락 시 모든 매수 즉시 차단")
            w("")
            w("\033[1;93m [자산 보호 안전장치 (Cash Safety)]\033[0m")
            w("-" * tw)
            w("  • 주문 전 잔고 부족 시 자동 스킵")
            w("  • 가용 현금 1,000원 미만 → 모든 매수 중단 (미수 방지)")
            w("  • 가용 현금 부족 시 min(설정액, 가용현금) 범위로 수량 자동 축소")
            w("")
            w("\033[1;93m [AI 동적 리스크 관리 (Time-Stop)]\033[0m")
            w("-" * tw)
            w("  • 전략 적용 시 AI가 종목 모멘텀 수명을 예측 → 데드라인(Lifetime) 설정")
            w("  • 데드라인(REM:EXP) 경과 시 익절선을 현재 수익 후반으로 타이트하게 조정")
            w("  • VIBE와 종목 변동성에 따라 TP/SL을 실시간 미세 보정")
            w("")
            w("\033[1;93m [통합 배치 리뷰 (Batch Review)]\033[0m")
            w("-" * tw)
            w("  • 전 보유 종목을 1회 API 호출로 통합 분석 → [즉시매도/전략갱신/유지] 결정")
            w("  • 토큰 비용 절감 + 의사결정 속도 향상")
        
        elif current_tab == 5:
            # ── 설정 & 운영 팁 ──
            w("\033[1;93m [핵심 운영 팁]\033[0m")
            w("-" * tw)
            w("  \033[1m[3:자동]\033[0m 번호 없이 'TP SL' 입력 → 보유 전 종목의 기본 익절/손절 일괄 변경")
            w("  \033[1m[8:시황]\033[0m AI 제안 수치 = 현재 Vibe 반영 최종 목표값 → 시스템 자동 적용")
            w("  \033[1m[9:전략]\033[0m 엔터(빈 입력) → AI가 해당 종목에 최적 프리셋 전략 자동 매칭")
            w("  \033[1m[9:전략]\033[0m 엔터(보유 전체) → 배치 리뷰 1회 호출로 전 종목 일괄 전략 진단")
            w("  \033[1m[B:보유]\033[0m 리포트 내 R키 → 실시간 AI 포트폴리오 재진단 (10분 이상 경과 시 갱신 권고)")
            w("")
            w("\033[1;93m [TUI 메인 화면 구성 안내]\033[0m")
            w("-" * tw)
            w("  \033[1m헤더바\033[0m    : 버전, 시장상태(KR/US), 작업현황, 시간")
            w("  \033[1m지수라인\033[0m  : KOSPI/KOSDAQ/VIX | DOW/NAS/SPX | 환율/코인/선물")
            w("  \033[1mVIBE라인\033[0m  : 시장 장세(Bull/Bear/Neutral) + 페이즈 + AI 보정 상태")
            w("  \033[1m커맨드바\033[0m  : 전체 단축키 한 줄 표시")
            w("  \033[1m자산영역\033[0m  : 총자산/예수금/주식/일일변동/리스크 상태")
            w("  \033[1mSTRAT/ALGO\033[0m: 현재 TP/SL + 보정값 | AI 매매설정 및 비용")
            w("  \033[1mBEAR/BULL\033[0m : 물타기/불타기 설정 및 누적 집행 현황")
            w("  \033[1m보유종목\033[0m  : 코드/현재가/평단가/수익률/TP·SL/전략명/잔여시간")
            w("  \033[1m랭킹영역\033[0m  : 인기종목 | 거래량상위 | AI추천 (3단 병렬)")
            w("  \033[1m로그영역\033[0m  : 최신 시스템 로그 (최신 우선, 오래된 항목 생략)")
            w("")
            w("\033[1;93m [설정 영속성 (S:셋업)]\033[0m")
            w("-" * tw)
            w("  • 모든 설정은 \033[96mtrading_state.json\033[0m에 실시간 영속 저장 → 재시작 시 자동 복구")
            w("  • 항목: base_tp/sl, 물타기/불타기/AI설정, 프리셋 전략, 거절 목록 등")
            w("")
            w("\033[1;93m [AI 토큰 최적화]\033[0m")
            w("-" * tw)
            w("  • 자동 AI 기능: \033[96m08:40~15:50\033[0m 사이에만 작동 (장외 시간 토큰 절약)")
            w("  • 수동 실행(8,9,7,B,D,H 등): 시간 제한 없이 즉시 실행")
            w("  • AI 디버그 모드: S:셋업에서 ON → 시간 제한 무시 (헤더에 [디버그] 표시)")
        
        # 하단 안내 바
        buf.write("\n" + "-" * tw + "\n")
        nav_hint = " | ".join([f"\033[{'7m' if current_tab == i else '0m'}{i}\033[0m" for i in range(1, total_tabs + 1)])
        buf.write(align_kr(f" [{nav_hint}]: 탭 전환 | Q, ESC, SPACE: 메인으로 복귀 ", tw, 'center') + "\n")
        sys.stdout.write(buf.getvalue()); sys.stdout.flush()
        
        # 키 입력 대기
        while True:
            k = get_key_immediate()
            if k:
                kl = k.lower()
                if kl == '1': current_tab = 1; break
                elif kl == '2': current_tab = 2; break
                elif kl == '3': current_tab = 3; break
                elif kl == '4': current_tab = 4; break
                elif kl == '5': current_tab = 5; break
                elif kl in ['q', 'esc', ' ', '\r']:
                    buf.close()
                    return
            time.sleep(0.01)

def draw_trading_logs(strategy, dm):
    import io
    import os
    import copy
    import threading
    import time
    from src.logger import trading_log
    
    current_tab = 1
    total_tabs = 4
    
    while True:
        try:
            size = os.get_terminal_size()
            tw, th = size.columns, size.lines
        except:
            tw, th = 80, 24
        buf = io.StringIO(); buf.write("\033[H\033[2J")
        is_v = getattr(strategy.api.auth, 'is_virtual', True)
        header_bg = "45" if is_v else "44"
        buf.write(f"\033[{header_bg};37m" + align_kr(" [SYSTEM LOGS & MONITORING DASHBOARD] ", tw, 'center') + "\033[0m\n")
        
        # 탭 메뉴 바
        t1 = "\033[7m" if current_tab == 1 else ""
        t2 = "\033[7m" if current_tab == 2 else ""
        t3 = "\033[7m" if current_tab == 3 else ""
        t4 = "\033[7m" if current_tab == 4 else ""
        
        menu = f" {t1} 1.시스템로그(거래/설정) \033[0m | {t2} 2.모니터링(워커/상태) \033[0m | {t3} 3.에러로그(error.log) \033[0m | {t4} 4.TRADING LOG \033[0m "
        buf.write(align_kr(menu, tw, 'center') + "\n")
        buf.write("=" * tw + "\n\n")

        available_h = max(5, th - 10)
        curr_time = time.time()

        if current_tab == 1:
            dm.set_busy("시스템 로그 조회 중", "GLOBAL")
            log_area_h = max(4, th - 15)
            trade_h = int(log_area_h * 0.7)
            config_h = max(1, log_area_h - trade_h)
            
            buf.write("\033[1;93m [최근 거래 내역 (TRADE)]\033[0m\n")
            with trading_log.lock:
                trades = copy.deepcopy(trading_log.data.get("trades", []))
            if not trades:
                buf.write("  최근 거래 내역이 없습니다.\n")
            else:
                h_time = align_kr('시간', 20); h_type = align_kr('구분', 10)
                h_name = align_kr('종목명(코드)', 22); h_price = align_kr('체결가', 10)
                h_qty = align_kr('수량', 6); h_pnl = align_kr('수익금', 12)
                header = f"  {h_time} | {h_type} | {h_name} | {h_price} | {h_qty} | {h_pnl} | 메모"
                buf.write("\033[1m" + header + "\033[0m\n" + "  " + "-" * (tw - 4) + "\n")
                
                for t in trades[:trade_h]:
                    t_type = t.get('type', 'Unknown')
                    t_color = "\033[91m" if "매수" in t_type else "\033[94m" if "매도" in t_type or "익절" in t_type or "손절" in t_type else ""
                    p_val = t.get('profit', 0)
                    p_color = "\033[91m" if p_val > 0 else "\033[94m" if p_val < 0 else ""
                    p_str = f"{p_color}{int(p_val):+,}원\033[0m" if p_val != 0 else "-"
                    name_code = f"[{t.get('code', '')}] {t.get('name', '-')}"
                    
                    line = f"  {t.get('time', '-')} | {t_color}{align_kr(t_type, 10)}\033[0m | {align_kr(name_code, 22)} | {align_kr(f'{int(t.get('price',0)):,}', 10, 'right')} | {align_kr(str(t.get('qty',0)), 6, 'right')} | {align_kr(p_str, 12, 'right')} | {t.get('memo', '')}"
                    buf.write(truncate_log_line(line, tw - 2) + "\n")
                    
            buf.write("\n" + "  " + "=" * (tw - 4) + "\n\n")
            buf.write("\033[1;96m [시스템 설정 및 전략 변경 (CONFIG)]\033[0m\n")
            with trading_log.lock:
                configs = copy.deepcopy(trading_log.data.get("configs", []))
            if not configs:
                buf.write("  변경 이력이 없습니다.\n")
            else:
                for c in configs[:config_h]:
                    buf.write(f"  [{c.get('time', '-')}] {truncate_log_line(c.get('content', ''), tw - 25)}\n")
                    
        elif current_tab == 2:
            dm.set_busy("실시간 모니터링 중", "GLOBAL")
            with dm.data_lock:
                last_times = dict(dm.last_times); worker_status = dict(dm._worker_statuses); worker_results = dict(dm.worker_results)
            
            worker_desc = {
                "INDEX": "시황/지수 분석", "DATA": "데이터 동기화", "RANKING": "인기 종목 탐색",
                "ASSET": "계좌 정보 수집", "BILLING": "API 비용 정산", "UPDATE": "최신 버전 확인",
                "GLOBAL": "사용자 명령 처리", "TELEGRAM": "텔레그램 알림", "AI_ENGINE": "AI 전략 엔진",
                "THEME": "테마 정보 수집", "CLEANUP": "로그 자동 정리", "RETRO": "투자 복기 엔진", "TRADE": "실시간 매매"
            }
            all_workers = set(worker_desc.keys()); all_workers.update([k.upper() for k in last_times.keys()]); all_workers.update(worker_status.keys())
            
            # [수정] 설명(Task) 컬럼 너비 확장 (12 -> 18) 및 전체 레이아웃 조정
            h_name = align_kr('워커명', 12); h_desc = align_kr('설명(Task)', 18)
            h_time = align_kr('시간', 8); h_elap = align_kr('경과', 10, 'right')
            h_stat = align_kr('상태', 14); h_res  = align_kr('결과', 4, 'center')
            header = f"  {h_name} | {h_desc} | {h_time} | {h_elap} | {h_stat} | {h_res} | 마지막 행동"
            buf.write("\033[1m" + header + "\033[0m\n" + "  " + "-" * (tw - 6) + "\n")
            
            sort_order = {"INDEX": 1, "AI_ENGINE": 2, "DATA": 3, "RANKING": 4, "GLOBAL": 5, "TELEGRAM": 6, "ASSET": 7}
            def get_sort_key(x): return (sort_order.get(x, 99), x) if not x.startswith("STOCK_") else (100, x)
            sorted_workers = sorted([w for w in all_workers if w and w != "..."], key=get_sort_key)
            if "TELEGRAM" not in sorted_workers: sorted_workers.append("TELEGRAM")
            
            display_limit = max(5, available_h - 2)
            for w in sorted_workers[:display_limit]:
                ts = last_times.get(w.lower(), 0)
                # AI_ENGINE의 경우 전략의 분석 시간과 연동되어 있으나, 체크 시점 자체를 보여주기 위해 ts 사용 유지
                
                if not ts: t_str, e_str = "미갱신", "-"
                else:
                    dt = datetime.fromtimestamp(ts); t_str = dt.strftime('%H:%M:%S')
                    diff = int(curr_time - ts); e_str = f"{diff}초 전" if diff < 60 else f"{diff//60}분 {diff%60}초 전"
                
                t_fmt = align_kr(t_str, 8, 'center'); e_fmt = align_kr(e_str, 12, 'right')
                if ts: e_fmt = f"\033[96m{e_fmt}\033[0m"
                else: t_fmt = f"\033[90m{t_fmt}\033[0m"

                desc = worker_desc.get(w, "종목 상세" if w.startswith("STOCK_") else "배경 작업")
                name_col = f"[{dm.worker_names.get(w, w)}]"
                
                status = worker_status.get(w, '대기 중 (IDLE)')
                if w == "TELEGRAM" and hasattr(dm, 'notifier'): status = dm.notifier.status_msg
                if w == "AI_ENGINE": status = getattr(strategy, 'current_action', '대기 중 (IDLE)')
                if w == 'GLOBAL' and "조회 중" in status: status = '대기 중 (IDLE)'
                
                status_fmt = align_kr(status, 14)
                status_fmt = f"\033[90m{status_fmt}\033[0m" if status == '대기 중 (IDLE)' else f"\033[93m{status_fmt}\033[0m"
                
                res = worker_results.get(w, "-")
                if w == "AI_ENGINE" and strategy.is_analyzing: res = "분석중"
                elif w == "AI_ENGINE" and not ts: res = "실패" if not strategy.is_ready else "-"
                elif w == "TELEGRAM" and hasattr(dm, 'notifier'): res = getattr(dm.notifier, 'last_result', '-')
                res_color = "\033[92m" if res == "성공" else ("\033[91m" if res == "실패" else "")
                
                last_task = dm.worker_last_tasks.get(w, "-")
                if w == "TELEGRAM" and hasattr(dm, 'notifier'): last_task = getattr(dm.notifier, 'last_task', '-')
                
                # [수정] 마지막 행동 필드 내 개행 문자( \n, \r, <br> )를 공백으로 대체하여 줄바꿈 방지
                last_task = str(last_task).replace('\n', ' ').replace('\r', ' ').replace('<br>', ' ').replace('<BR>', ' ')
                
                # [수정] 데이터 행 컬럼 너비 동기화 (Desc: 18, Elap: 10) 및 가용 너비 재계산 (tw-91)
                buf.write(f"  \033[1;94m{align_kr(name_col, 12)}\033[0m | {align_kr(desc, 18)} | {t_fmt} | {e_fmt} | {status_fmt} | {res_color}{align_kr(res, 4, 'center')}\033[0m | {truncate_log_line(last_task, max(20, tw-91))}\n")
            
            skipped = len(sorted_workers) - display_limit
            if skipped > 0: buf.write(f"  \033[90m... 외 {skipped}건 생략됨 (터미널 높이 부족)\033[0m\n")

        elif current_tab == 3:
            dm.set_busy("에러 로그 분석 중", "GLOBAL")
            buf.write("\033[1;91m [최근 에러 로그 (ERROR LOG)]\033[0m\n" + "-" * tw + "\n")
            error_file = "error.log"
            try:
                if os.path.exists(error_file):
                    with open(error_file, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                    if not lines: buf.write("  기록된 에러가 없습니다.\n")
                    else:
                        lines.reverse()
                        for line in lines[:available_h-2]:
                            line_str = truncate_log_line(line.strip(), tw - 4)
                            if "ERROR" in line_str: line_str = line_str.replace("ERROR", "\033[91mERROR\033[0m")
                            buf.write(f"  {line_str}\n")
                else: buf.write("  error.log 파일이 존재하지 않습니다.\n")
            except Exception as e: buf.write(f"  로그 읽기 오류: {e}\n")

        elif current_tab == 4:
            dm.set_busy("거래 로그 분석 중", "GLOBAL")
            buf.write("\033[1;92m [최근 거래 로그 (TRADING LOG)]\033[0m\n" + "-" * tw + "\n")
            trade_log_file = "trading.log"
            try:
                if os.path.exists(trade_log_file):
                    with open(trade_log_file, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                    if not lines: buf.write("  기록된 거래 로그가 없습니다.\n")
                    else:
                        lines.reverse()
                        for line in lines[:available_h-2]:
                            line_str = truncate_log_line(line.strip(), tw - 4)
                            if "[TRADE]" in line_str: line_str = line_str.replace("[TRADE]", "\033[92m[TRADE]\033[0m")
                            elif "[CONFIG]" in line_str: line_str = line_str.replace("[CONFIG]", "\033[96m[CONFIG]\033[0m")
                            elif "[REJECT]" in line_str: line_str = line_str.replace("[REJECT]", "\033[91m[REJECT]\033[0m")
                            buf.write(f"  {line_str}\n")
                else: buf.write("  trading.log 파일이 존재하지 않습니다.\n")
            except Exception as e: buf.write(f"  로그 읽기 오류: {e}\n")

        buf.write("\n" + "-" * tw + "\n")
        buf.write(align_kr(" [1, 2, 3, 4]: 탭 전환 | Q, ESC, SPACE: 메인으로 복귀 ", tw, 'center') + "\n")
        sys.stdout.write(buf.getvalue()); sys.stdout.flush()
        
        inner_cycle = 0
        while inner_cycle < 100:
            k = get_key_immediate()
            if k:
                kl = k.lower()
                if kl == '1': current_tab = 1; break
                elif kl == '2': current_tab = 2; break
                elif kl == '3': current_tab = 3; break
                elif kl == '4': current_tab = 4; break
                elif kl in ['q', 'esc', ' ', '\r']: return
            time.sleep(0.01); inner_cycle += 1
