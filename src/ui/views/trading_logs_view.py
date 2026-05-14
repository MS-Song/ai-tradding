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
from src.logger import trading_log

def draw_trading_logs(strategy, dm):
    """시스템의 원시 로그와 실시간 워커 상태를 모니터링하는 통합 로그 대시보드를 렌더링합니다.

    이 뷰는 거래 내역, 설정 변경 이력, 백그라운드 스레드들의 실시간 동작 상태, 
    그리고 실제 로그 파일(error.log, trading.log)의 내용을 5개의 탭으로 시각화합니다.

    Args:
        strategy: 트레이딩 전략 객체 (엔진 상태 참조용).
        dm: 데이터 매니저 객체 (워커 상태 및 지표 갱신 현황 참조용).

    Tabs:
        0. 주요지표: KOSPI, 환율, 비트코인 등 주요 외부 지표의 실시간 수집 성공 여부와 갱신 시점.
        1. 시스템로그: 최근 체결된 거래 내역과 사용자에 의한 설정 변경(TP/SL 등) 히스토리.
        2. 모니터링: 마켓, AI, 텔레그램 등 모든 백그라운드 워커의 현재 Task, 경과 시간, 마지막 결과.
        3. 에러로그: `error.log` 파일의 최근 내용을 역순으로 읽어 런타임 오류 확인.
        4. TRADING LOG: `trading.log` 파일의 상세 실행 기록 확인.

    Logic:
        - `워커 감시`: 각 워커의 마지막 동작 시각(ts)을 기반으로 'N초 전' 형태로 지연 여부를 표시합니다.
        - `로그 가공`: ANSI 색상 코드를 사용하여 에러는 빨간색, 성공은 초록색 등으로 하이라이팅합니다.
        - `동적 레이아웃`: 터미널 높이에 따라 표시되는 로그의 줄 수를 자동으로 조정합니다.

    Controls:
        - [0~4]: 각 모니터링 탭으로 전환.
        - [Q, ESC, SPACE, ENTER]: 로그 화면을 닫고 메인 대시보드로 복귀.
    """
    import io
    import os
    import copy
    import threading
    import time
    from src.logger import trading_log
    
    current_tab = 1
    total_tabs = 5
    
    while True:
        try:
            size = os.get_terminal_size()
            tw, th = size.columns, size.lines
        except:
            tw, th = 80, 24
        buf = io.StringIO()

        is_v = getattr(strategy.api.auth, 'is_virtual', True)
        header_bg = "45" if is_v else "44"
        buf.write(f"\033[{header_bg};37m" + align_kr(" [SYSTEM LOGS & MONITORING DASHBOARD] ", tw, 'center') + "\033[0m\n")
        
        # 탭 메뉴 바
        t0 = "\033[7m" if current_tab == 0 else ""
        t1 = "\033[7m" if current_tab == 1 else ""
        t2 = "\033[7m" if current_tab == 2 else ""
        t3 = "\033[7m" if current_tab == 3 else ""
        t4 = "\033[7m" if current_tab == 4 else ""
        
        menu = f" {t0} 0.주요지표 \033[0m | {t1} 1.시스템로그(거래/설정) \033[0m | {t2} 2.모니터링(워커/상태) \033[0m | {t3} 3.에러로그(error.log) \033[0m | {t4} 4.TRADING LOG \033[0m "
        buf.write(align_kr(menu, tw, 'center') + "\n")
        buf.write("=" * tw + "\n\n")

        available_h = max(5, th - 10)
        curr_time = time.time()

        if current_tab == 0:
            dm.set_busy("주요 지표 조회 중", "UI")
            buf.write("\033[1;96m [주요 지표 갱신 현황 (중요도순)]\033[0m\n")
            with dm.data_lock:
                indicator_updates = dict(dm.state.indicator_updates)
            
            if not indicator_updates:
                buf.write("  아직 갱신된 주요 지표가 없습니다.\n")
            else:
                h_name = align_kr('명칭', 12); h_desc = align_kr('설명', 16); h_time = align_kr('갱신 시간', 10)
                h_stat = align_kr('상태', 6); h_val = align_kr('결과 값', 22)
                h_rem = '비고'
                header = f"  {h_name} | {h_desc} | {h_time} | {h_stat} | {h_val} | {h_rem}"
                buf.write("\033[1m" + header + "\033[0m\n" + "  " + "-" * (tw - 4) + "\n")
                
                # 중요도 순으로 정렬
                sort_order = {
                    "한국장": 0, "KOSPI": 1, "KOSDAQ": 2, "KPI200": 3, "VOSPI": 4,
                    "DOW": 5, "NASDAQ": 6, "S&P500": 7, "NAS_FUT": 8, "SPX_FUT": 9,
                    "FX_USDKRW": 10, "BTC_KRW": 11, "BTC_USD": 12
                }
                desc_map = {
                    "한국장": "장 개장 상태", "KOSPI": "코스피 종합", "KOSDAQ": "코스닥 종합", 
                    "KPI200": "코스피 200", "VOSPI": "코스피 변동성", "DOW": "다우존스", 
                    "NASDAQ": "나스닥 종합", "S&P500": "S&P 500", "NAS_FUT": "나스닥 선물", 
                    "SPX_FUT": "S&P 선물", "FX_USDKRW": "원/달러 환율", "BTC_KRW": "비트코인(원)", 
                    "BTC_USD": "비트코인($)", "지수통합수집": "API 수집상태"
                }
                def get_sort_key(item):
                    name, data = item
                    return (sort_order.get(name, 99), -data.get('time', 0))
                
                sorted_inds = sorted(indicator_updates.items(), key=get_sort_key)
                for name, data in sorted_inds[:available_h-2]:
                    desc = desc_map.get(name, '-')
                    t_str = datetime.fromtimestamp(data.get('time', 0)).strftime('%H:%M:%S')
                    stat = data.get('status', '-')
                    stat_color = "\033[92m" if stat == "성공" else "\033[91m" if stat == "실패" else ""
                    
                    val = data.get('value', '-')
                    rate = data.get('rate', 0.0)
                    if val != "-" and val != "오픈" and val != "마감":
                        val_color = "\033[91m" if rate > 0 else "\033[94m" if rate < 0 else ""
                        val_display = f"{val_color}{align_kr(val, 22)}\033[0m" if val_color else align_kr(val, 22)
                    else:
                        val_display = align_kr(val, 22)

                    rem = data.get('remark', '')
                    
                    line = f"  \033[1;94m{align_kr(name, 12)}\033[0m | \033[90m{align_kr(desc, 16)}\033[0m | {align_kr(t_str, 10, 'center')} | {stat_color}{align_kr(stat, 6, 'center')}\033[0m | {val_display} | {truncate_log_line(rem, max(10, tw-85))}"
                    buf.write(line + "\n")

        elif current_tab == 1:
            dm.set_busy("시스템 로그 조회 중", "UI")
            log_area_h = max(4, th - 15)
            trade_h = int(log_area_h * 0.7)
            config_h = max(1, log_area_h - trade_h)
            
            buf.write("\033[1;93m [최근 거래 내역 (TRADE)]\033[0m\n")
            with trading_log.lock:
                trades = copy.deepcopy(trading_log.data.get("trades", [])[:trade_h])

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
                    # AI 매매는 보라색(95), 매수는 빨간색(91), 매도는 파란색(94)
                    if "AI" in t_type or "🤖" in t_type:
                        t_color = "\033[95m"
                    elif "매수" in t_type:
                        t_color = "\033[91m"
                    elif any(k in t_type for k in ["매도", "익절", "손절", "청산"]):
                        t_color = "\033[94m"
                    else:
                        t_color = ""
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
            dm.set_busy("실시간 모니터링 중", "UI")
            with dm.data_lock:
                last_times = dict(dm.last_times); worker_status = dict(dm._worker_statuses); worker_results = dict(dm.worker_results)
            
            worker_desc = {
                "INDEX": "지수 데이터 수집", "MARKET": "마켓 엔진 (수집)", "VIBE": "Vibe 분석 (AI)",
                "RANKING": "인기/테마 (랭킹)", "HOT_RANKING": "인기 종목 수집", "VOL_RANKING": "거래량 랭킹 수집", "AMT_RANKING": "거래대금 랭킹 수집",
                "THEME_ANAL": "테마 종목 분석",
                "DATA": "데이터 동기화", "ASSET": "계좌 정보 수집", "BILLING": "API 비용 정산", 
                "UPDATE": "최신 버전 확인", "GLOBAL": "사용자 명령 처리", "TELEGRAM": "텔레그램 발신", "TG_RECEIVE": "텔레그램 수신",
                "AI_ENGINE": "AI 전략 엔진", "CLEANUP": "로그 자동 정리", "RETRO": "투자 복기 엔진",
                "TRADE": "실시간 매매", "TRADE_EXECUTION": "실시간 매매", "RECOMMENDATION": "AI 추천 수집", "UI": "실시간 모니터링",
                "REPORT": "정기 리포트 발송",
                "WS_KIWOOM": "실시간 웹소켓",
                "WS_KIS": "실시간 웹소켓",
                "THEME_SYNC": "테마 DB 갱신"
            }
            # [수정] 현재 구동 중인 워커(dm.workers) 또는 실제 실행 이력(last_times)이 있는 워커만 필터링하여 표시
            # 무분별하게 모든 정의된 워커(worker_desc)를 노출하지 않음
            active_ids = {k.upper() for k in dm.workers.keys()}
            run_ids = {w.upper() for w in last_times.keys()}
            all_workers = sorted(list(active_ids | run_ids))
            
            # [중복 제거 로직] 동일한 friendly name을 가진 워커가 여러 ID로 존재할 경우,
            # 가장 최근에 갱신(ts)된 ID 하나만 남깁니다. (미갱신 고스트 행 제거)
            worker_map = {}
            for w in all_workers:
                if not w or w == "...": continue
                friendly = dm.worker_names.get(w, w)
                ts = last_times.get(w.lower(), 0)
                if friendly not in worker_map:
                    worker_map[friendly] = w
                else:
                    prev_w = worker_map[friendly]
                    if ts > last_times.get(prev_w.lower(), 0):
                        worker_map[friendly] = w
            
            display_workers = list(worker_map.values())
            
            # [수정] 워커명 너비 확장 (15 -> 20) 및 경과 시간 너비 동기화 (12)
            h_name = align_kr('워커명', 20); h_desc = align_kr('설명(Task)', 18)
            h_time = align_kr('시간', 8); h_elap = align_kr('경과', 12, 'right')
            h_stat = align_kr('상태', 14); h_res  = align_kr('결과', 4, 'center')
            header = f"  {h_name} | {h_desc} | {h_time} | {h_elap} | {h_stat} | {h_res} | 마지막 행동"
            buf.write("\033[1m" + header + "\033[0m\n" + "  " + "-" * (tw - 6) + "\n")
            
            sort_order = {"MARKET": 0, "VIBE": 1, "RANKING": 2, "AI_ENGINE": 3, "DATA": 4, "GLOBAL": 5, "TELEGRAM": 6, "TG_RECEIVE": 7, "ASSET": 8}
            def get_sort_key(x): return (sort_order.get(x, 99), x) if not x.startswith("STOCK_") else (100, x)
            sorted_workers = sorted(display_workers, key=get_sort_key)
            if "TELEGRAM" not in sorted_workers and "TELEGRAM" in all_workers: sorted_workers.append("TELEGRAM")
            
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
                
                last_task = dm.worker_last_tasks.get(w, "-").replace('\n', ' ')
                if w == "TELEGRAM" and hasattr(dm, 'notifier'): 
                    last_task = getattr(dm.notifier, 'last_task', '-').replace('\n', ' ')
                
                # [수정] 실패 시 마지막 행동을 빨간색으로 강조
                last_task_fmt = f"\033[91m{last_task}\033[0m" if res == "실패" else last_task
                
                # [수정] 데이터 행 컬럼 너비 동기화 (Name: 20, Desc: 18, Elap: 12) 및 가용 너비 재계산 (tw-101)
                buf.write(f"  \033[1;94m{align_kr(name_col, 20)}\033[0m | {align_kr(desc, 18)} | {t_fmt} | {e_fmt} | {status_fmt} | {res_color}{align_kr(res, 4, 'center')}\033[0m | {truncate_log_line(last_task_fmt, max(20, tw-101))}\n")
            
            skipped = len(sorted_workers) - display_limit
            if skipped > 0: buf.write(f"  \033[90m... 외 {skipped}건 생략됨 (터미널 높이 부족)\033[0m\n")

        elif current_tab == 3:
            dm.set_busy("에러 로그 분석 중", "UI")
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
            dm.set_busy("거래 로그 분석 중", "UI")
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
        buf.write(align_kr(" [0, 1, 2, 3, 4]: 탭 전환 | Q, ESC, SPACE: 메인으로 복귀 ", tw, 'center') + "\n")
        
        # [수정] 버퍼 내용을 한 줄씩 출력하면서 각 줄을 소거 (\033[K) 하고 남은 영역 소거 (\033[J)
        # 드래그나 스크롤 시 화면이 밀리는 현상 방지
        sys.stdout.write("\033[H")
        content_lines = buf.getvalue().split('\n')
        for i in range(min(th, len(content_lines))):
            sys.stdout.write(content_lines[i] + "\033[K" + ("\n" if i < th-1 else ""))
        sys.stdout.write("\033[J")
        sys.stdout.flush()
        
        inner_cycle = 0
        while inner_cycle < 100:
            k = get_key_immediate()
            if k:
                kl = k.lower()
                if kl == '0': current_tab = 0; break
                elif kl == '1': current_tab = 1; break
                elif kl == '2': current_tab = 2; break
                elif kl == '3': current_tab = 3; break
                elif kl == '4': current_tab = 4; break
                elif kl in ['q', 'esc', ' ', '\r']: return
            time.sleep(0.01); inner_cycle += 1

