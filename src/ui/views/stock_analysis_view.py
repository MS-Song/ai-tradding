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

def draw_stock_analysis(strategy, dm, code, tw, th):
    """특정 종목에 대한 AI 심층 분석 리포트 화면을 렌더링합니다.

    사용자가 입력한 종목 코드 또는 순번을 바탕으로 실시간 시세, 재무 지표(PER/PBR), 
    최신 뉴스, 그리고 분봉 차트를 수집하여 AI의 종합적인 투자 의견을 제시합니다.

    Args:
        strategy: 트레이딩 전략 객체 (AI 심층 분석 로직 포함).
        dm: 데이터 매니저 객체 (UI 상태 및 워커 제어용).
        code (str): 분석할 종목의 6자리 코드.
        tw (int): 터미널 너비.
        th (int): 터미널 높이.

    Logic:
        - `run_bg_analysis`: 별도 스레드에서 종목 상세 데이터, 뉴스, 차트 데이터를 수집한 후 AI 리포트를 생성합니다.
        - `입체 분석`: 단순 가격뿐만 아니라 펀더멘털 지표와 최신 뉴스 모멘텀을 결합하여 분석합니다.
        - `기술적 분석`: `ChartRenderer`를 통해 해당 종목의 최근 분봉 흐름을 시각화합니다.

    Controls:
        - [아무 키]: 분석 화면을 닫고 메인 대시보드로 복귀.
    """
    import io
    import threading
    
    _is_running = False
    _report = None
    _detail = None
    _news = None
    _candles = None
    
    def run_bg_analysis(t_code):
        nonlocal _is_running, _report, _detail, _news, _candles
        _is_running = True
        dm.set_busy(f"{t_code} 심층 분석 중", "UI")
        try:
            _detail = strategy.api.get_naver_stock_detail(t_code)
            _news = strategy.api.get_naver_stock_news(t_code)
            _candles = strategy.api.get_minute_chart_price(t_code)
            name = _detail.get('name', '알 수 없는 종목')
            _report = strategy.ai_advisor.get_stock_report_advice(t_code, name, _detail, _news)
        finally:
            _is_running = False
            dm.clear_busy("UI")

    threading.Thread(target=run_bg_analysis, args=(code,), daemon=True).start()

    while True:
        try:
            size = os.get_terminal_size()
            tw, th = size.columns, size.lines
        except: tw, th = 80, 24
        
        buf = io.StringIO()
        buf.write("\033[42;30m" + align_kr(f" [AI STOCK ANALYSIS REPORT: {code}] ", tw, 'center') + "\033[0m\n\n")
        
        if _detail:
            name = _detail.get('name', '알 수 없는 종목')
            color = "\033[91m" if _detail.get('rate', 0) >= 0 else "\033[94m"
            buf.write(f"\033[1;93m [종목 정보] {name} ({code})\033[0m\n")
            buf.write(f"  * 실시간시세: {int(float(_detail.get('price',0))):,}원 ({color}{_detail.get('rate',0):+.2f}%\033[0m)\n")
            buf.write(f"  * 시가총액  : {_detail.get('market_cap')}\n")
            buf.write(f"  * 펀더멘털  : PER {_detail.get('per')} | PBR {_detail.get('pbr')} | 배당 {_detail.get('yield')} | 업종PER {_detail.get('sector_per')}\n")
            
            buf.write("\n\033[1;96m [최신 소식 및 공시]\033[0m\n")
            if _news:
                for n in _news[:3]: buf.write(f"  - {n}\n")
            else: buf.write("  - 최근 소식 없음\n")
            
            if _candles:
                from src.strategy.chart_renderer import ChartRenderer
                chart_txt = ChartRenderer.render_candle_chart(_candles, width=tw-15, height=min(12, th-20), title=f"[{name}] 기술적 흐름 (분봉)")
                buf.write("\n" + chart_txt + "\n")
        else:
            buf.write(f"\033[93m 🚀 {code} 종목 분석을 시작합니다. 잠시만 기다려주세요...\033[0m\n")
            buf.write(f" 🔍 상세 데이터를 수집 중입니다...\n")

        buf.write("-" * tw + "\n")
        if _is_running:
            buf.write("\033[1;95m 🤖 AI가 확인 중입니다... (리포트 생성 중)\033[0m\n")
        elif _report:
            buf.write("\033[1;92m [Gemini AI 심층 분석 의견]\033[0m\n")
            cleaned_report = clean_ai_text(_report)
            for line in cleaned_report.split('\n'):
                if line.strip(): buf.write(f"  {line.strip()}\n")
        else:
            if not _is_running:
                buf.write("  ⚠️ 리포트를 생성할 수 없습니다. API 키 또는 네트워크 상태를 확인하세요.\n")

        buf.write("\n" + "-" * tw + "\n" + align_kr(" 아무 키나 누르면 메인 화면으로 돌아갑니다. ", tw, 'center') + "\n")
        
        sys.stdout.write("\033[H")
        content_lines = buf.getvalue().split('\n')
        for i in range(min(th, len(content_lines))):
            sys.stdout.write(content_lines[i] + "\033[K" + ("\n" if i < th-1 else ""))
        sys.stdout.write("\033[J")
        sys.stdout.flush()
        buf.close()

        inner_cycle = 0
        while inner_cycle < 10:
            k = get_key_immediate()
            if k: return
            time.sleep(0.1)
            inner_cycle += 1

