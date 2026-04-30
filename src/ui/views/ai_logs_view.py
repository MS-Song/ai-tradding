import os
import sys
import time
import threading
import io
import re
from datetime import datetime
from src.utils import *
from src.theme_engine import get_cached_themes, get_theme_for_stock
from src.strategy import PRESET_STRATEGIES
from src.ui.renderer import truncate_log_line
from src.logger import trading_log

def draw_ai_logs_report(strategy, dm):
    import io
    import os
    import copy
    from src.logger import trading_log
    
    current_tab = 1
    while True:
        try:
            size = os.get_terminal_size()
            tw, th = size.columns, size.lines
        except:
            tw, th = 80, 24
        buf = io.StringIO()

        is_v = getattr(strategy.api.auth, 'is_virtual', True)
        header_bg = "45" if is_v else "44"
        buf.write(f"\033[{header_bg};37m" + align_kr(" [AI DECISION & LOG REPORT] ", tw, 'center') + "\033[0m\n")
        
        # 탭 메뉴 바
        tab1_s = "\033[7m" if current_tab == 1 else ""
        tab2_s = "\033[7m" if current_tab == 2 else ""
        tab3_s = "\033[7m" if current_tab == 3 else ""
        tab4_s = "\033[7m" if current_tab == 4 else ""
        
        menu_bar = f" {tab1_s} 1.매수거절 \033[0m | {tab2_s} 2.종목교체 \033[0m | {tab3_s} 3.매수사유 \033[0m | {tab4_s} 4.전략수립근거(보유) \033[0m "
        buf.write(align_kr(menu_bar, tw, 'center') + "\n")
        buf.write("=" * tw + "\n\n")

        if current_tab == 1:
            buf.write("\033[1;91m" + " [AI 매수 거절 히스토리 (오늘)]" + "\033[0m\n")
            buf.write("-" * tw + "\n")
            rejections = trading_log.data.get("rejections", [])
            today = datetime.now().strftime('%Y-%m-%d')
            today_rejections = [r for r in rejections if r.get('time', '').startswith(today)]
            
            if not today_rejections:
                buf.write("  오늘 기록된 매수 거절 내역이 없습니다.\n")
            else:
                buf.write("\033[1m" + f" {align_kr('시간', 10)} | {align_kr('코드', 8)} | {align_kr('종목명', 14)} | {align_kr('모델', 8)} | 거절 사유" + "\033[0m\n")
                buf.write("-" * tw + "\n")
                max_items = max(3, th - 13)
                for item in today_rejections[:max_items]:
                    t_str = item['time'].split(' ')[-1]
                    m_id = item.get('model_id', '')
                    m_name = trading_log._normalize_model_name(m_id)
                    reason = item['reason'].replace('\n', ' ')
                    
                    # [Architect 개선] 사유 내 모델 식별자([...]) 추출 및 모델 컬럼 이동
                    match = re.match(r'^\[([^\]]+)\]\s*(.*)', reason)
                    if match:
                        extracted_model = match.group(1)
                        reason = match.group(2)
                        # AI가 명시한 모델이 있으면 m_name(TP/SL) 대신 사용
                        if m_name == "TP/SL" or not m_name:
                            m_name = extracted_model

                    # 가용 너비 계산 (시간 10 + 코드 8 + 종목명 14 + 모델 8 + 구분자 12 = 52)
                    avail_w = max(20, tw - 55)
                    if get_visual_width(reason) > avail_w:
                        while get_visual_width(reason) > avail_w - 2: reason = reason[:-1]
                        reason += ".."
                    buf.write(f" {align_kr(t_str, 10)} | {align_kr(item['code'], 8)} | {align_kr(item['name'], 14)} | {align_kr(m_name, 8)} | {reason}\n")

        elif current_tab == 2:
            buf.write("\033[1;92m" + " [종목 한도(8개) 초과에 따른 당일 교체 히스토리]" + "\033[0m\n")
            buf.write("-" * tw + "\n")
            today = datetime.now().strftime('%Y-%m-%d')
            today_replacements = [r for r in strategy.replacement_logs if r.get('time', '').startswith(today)]
            
            if not today_replacements:
                buf.write("  오늘 기록된 종목 교체 내역이 없습니다.\n")
            else:
                buf.write("\033[1m" + f" {align_kr('시간', 10)} | {align_kr('OUT(매도)', 22)} | {align_kr('IN(매수)', 22)} | 교체 사유" + "\033[0m\n")
                buf.write("-" * tw + "\n")
                max_items = max(3, th - 13)
                for item in today_replacements[:max_items]:
                    t_str = item['time'].split(' ')[-1]
                    out_info = f"[{item.get('out_code','?')}] {item.get('out_name','?')[:12]}"
                    in_info = f"[{item.get('in_code','?')}] {item.get('in_name','?')[:12]}"
                    reason = item['reason'].replace('\n', ' ')
                    # 가용 너비 계산 (10 + 22 + 22 + 9 = 63)
                    avail_w = max(20, tw - 66)
                    if get_visual_width(reason) > avail_w:
                        while get_visual_width(reason) > avail_w - 2: reason = reason[:-1]
                        reason += ".."
                    buf.write(f" {align_kr(t_str, 10)} | {align_kr(out_info, 22)} | {align_kr(in_info, 22)} | {reason}\n")

        elif current_tab == 3:
            buf.write("\033[1;93m" + " [AI 당일 매수 승인 및 진입 근거]" + "\033[0m\n")
            buf.write("-" * tw + "\n")
            reasons = trading_log.data.get("buy_reasons", [])
            today = datetime.now().strftime('%Y-%m-%d')
            today_reasons = [r for r in reasons if r.get('time', '').startswith(today)]
            
            if not today_reasons:
                buf.write("  오늘 기록된 매수 승인 사유가 없습니다.\n")
            else:
                buf.write("\033[1m" + f" {align_kr('시간', 10)} | {align_kr('코드', 8)} | {align_kr('종목명', 14)} | {align_kr('모델', 8)} | 매수 승인 사유" + "\033[0m\n")
                buf.write("-" * tw + "\n")
                max_items = max(3, th - 13)
                for item in today_reasons[:max_items]:
                    t_str = item['time'].split(' ')[-1]
                    m_id = item.get('model_id', '')
                    m_name = trading_log._normalize_model_name(m_id)
                    reason = item['reason'].replace('\n', ' ')
                    
                    # [Architect 개선] 사유 내 모델 식별자([...]) 추출 및 모델 컬럼 이동
                    match = re.match(r'^\[([^\]]+)\]\s*(.*)', reason)
                    if match:
                        extracted_model = match.group(1)
                        reason = match.group(2)
                        # AI가 명시한 모델이 있으면 m_name(TP/SL) 대신 사용
                        if m_name == "TP/SL" or not m_name:
                            m_name = extracted_model

                    avail_w = max(20, tw - 55)
                    if get_visual_width(reason) > avail_w:
                        while get_visual_width(reason) > avail_w - 2: reason = reason[:-1]
                        reason += ".."
                    buf.write(f" {align_kr(t_str, 10)} | {align_kr(item['code'], 8)} | {align_kr(item['name'], 14)} | {align_kr(m_name, 8)} | {reason}\n")

        elif current_tab == 4:
            buf.write("\033[1;96m" + " [현재 보유 종목별 AI 전략 수립 근거]" + "\033[0m\n")
            buf.write("-" * tw + "\n")
            presets = strategy.preset_eng.preset_strategies
            active_presets = {k: v for k, v in presets.items() if v.get('preset_id') != '00'}
            
            if not active_presets:
                buf.write("  현재 AI 프리셋 전략이 할당된 종목이 없습니다.\n")
            else:
                buf.write("\033[1m" + f" {align_kr('시간', 10)} | {align_kr('코드', 8)} | {align_kr('종목명', 14)} | {align_kr('전략명', 12)} | 분석 근거" + "\033[0m\n")
                buf.write("-" * tw + "\n")
                with dm.data_lock:
                    p_items = copy.deepcopy(active_presets)
                
                p_list = []
                for code, p in p_items.items():
                    # 실제로 현재 잔고에 있는 종목만 보여줌
                    if any(h['pdno'] == code for h in dm.cached_holdings):
                        buy_time = p.get('buy_time', '1970-01-01 00:00:00')
                        p_list.append({"code": code, "p": p, "buy_time": buy_time})
                
                p_list.sort(key=lambda x: x['buy_time'] if x['buy_time'] else '0000', reverse=True)
                
                max_items = max(3, th - 13)
                for item in p_list[:max_items]:
                    code = item["code"]
                    p = item["p"]
                    b_time_str = p.get('buy_time', '??').split(' ')[-1] if p.get('buy_time') else '??'
                    detail = strategy.api.get_naver_stock_detail(code)
                    name = detail.get('name', code)
                    reason = p.get('reason', '').replace('\n', ' ')
                    # 가용 너비 계산 (10 + 8 + 14 + 12 + 15 = 59)
                    avail_w = max(20, tw - 62)
                    if get_visual_width(reason) > avail_w:
                        while get_visual_width(reason) > avail_w - 2: reason = reason[:-1]
                        reason += ".."
                    buf.write(f" {align_kr(b_time_str, 10)} | {align_kr(code, 8)} | {align_kr(name, 14)} | {align_kr(p['name'], 12)} | {reason}\n")

        buf.write("\n" + "-" * tw + "\n")
        buf.write(align_kr(" [1, 2, 3, 4]: 탭 전환 | Q, ESC, SPACE: 종료 ", tw, 'center') + "\n")
        
        # [수정] 부드러운 화면 갱신
        sys.stdout.write("\033[H")
        content_lines = buf.getvalue().split('\n')
        for i in range(min(th, len(content_lines))):
            sys.stdout.write(content_lines[i] + "\033[K" + ("\n" if i < th-1 else ""))
        sys.stdout.write("\033[J")
        sys.stdout.flush()

        
        while True:
            k = get_key_immediate()
            if k:
                kl = k.lower()
                if kl == '1': current_tab = 1; break
                elif kl == '2': current_tab = 2; break
                elif kl == '3': current_tab = 3; break
                elif kl == '4': current_tab = 4; break
                elif kl in ['q', 'esc', ' ']:
                    buf.close()
                    return
            time.sleep(0.01)

