import json
import re
import threading
import time
from abc import ABC, abstractmethod
from typing import List, Tuple, Optional, Callable
from concurrent.futures import ThreadPoolExecutor
from src.logger import log_error
from src.strategy.constants import PRESET_STRATEGIES
from src.utils import get_now


class BaseAdvisor(ABC):
    """트레이딩 엔진의 두뇌 역할을 하는 AI 어드바이저의 추상 인터페이스.
    
    시장 상황 분석, 개별 종목 진단, 포트폴리오 전략 수립, 매매 최종 컨펌 등 
    의사결정에 필요한 핵심 메서드들을 정의합니다.
    """
    @abstractmethod
    def get_advice(self, market_data: dict, vibe: str, holdings: List[dict], current_config: dict, recs: List[dict] = None, indicators: dict = None) -> Optional[str]:
        """시황 및 추천 종목을 바탕으로 전반적인 투자 전략 제언을 생성합니다."""
        pass

    @abstractmethod
    def get_detailed_report_advice(self, recs: List[dict], vibe: str, progress_cb: Optional[Callable] = None) -> Optional[str]:
        """추천 종목들에 대한 심층 분석 리포트를 생성합니다."""
        pass

    @abstractmethod
    def get_stock_report_advice(self, code: str, name: str, detail: dict, news: List[str]) -> Optional[str]:
        """특정 개별 종목에 대한 정밀 진단 및 대응 전략을 생성합니다."""
        pass

    @abstractmethod
    def get_holdings_report_advice(self, holdings: List[dict], vibe: str, market_data: dict, progress_cb: Optional[Callable] = None) -> Optional[str]:
        """현재 보유 중인 포트폴리오 전체에 대한 건강도 진단 및 종목별 의견을 생성합니다."""
        pass

    @abstractmethod
    def get_hot_stocks_report_advice(self, hot_stocks: List[dict], themes: List[dict], vibe: str, progress_cb: Optional[Callable] = None) -> Optional[str]:
        """당일 실시간 인기 검색 종목 및 테마에 대한 트렌드 분석을 수행합니다."""
        pass

    @abstractmethod
    def simulate_preset_strategy(self, code: str, name: str, vibe: str, detail: dict = None, news: List[str] = None) -> Optional[dict]:
        """종목의 특성과 시황을 고려하여 최적의 프리셋 전략(TP/SL/유효시간)을 도출합니다."""
        pass

    @abstractmethod
    def final_buy_confirm(self, code: str, name: str, vibe: str, detail: dict, news: List[str], indicators: dict = None, score: float = 0.0, phase: dict = None) -> Tuple[bool, str, int]:
        """매수 집행 직전, 기술적 지표와 뉴스를 2차 검증하여 최종 승인 여부를 결정합니다."""
        pass

    @abstractmethod
    def verify_market_vibe(self, current_data: dict, heuristic_vibe: str) -> Optional[str]:
        """알고리즘이 판정한 시장 장세를 AI 관점에서 재검증하여 확정합니다."""
        pass

    @abstractmethod
    def closing_sell_confirm(self, code: str, name: str, vibe: str, rt: float, detail: dict, news: List[str]) -> Tuple[bool, str]:
        """장 마감 직전, 오버나이트 리스크를 고려하여 보유 종목의 청산 여부를 결정합니다."""
        pass

    @abstractmethod
    def get_rebalance_advice(self, portfolio_summary: List[dict]) -> Optional[str]:
        """자산 비중 및 수익률을 고려하여 포트폴리오 리밸런싱 전략을 제안합니다."""
        pass

    @abstractmethod
    def compare_stock_superiority(self, candidate: dict, holdings_info: List[dict], vibe: str) -> Tuple[bool, Optional[str], str, int]:
        """신규 후보 종목과 기존 보유 종목을 비교하여 종목 교체(Replacement) 여부를 결정합니다."""
        pass

    @abstractmethod
    def get_portfolio_strategic_review(self, holdings_data: List[dict], vibe: str, market_data: dict) -> Optional[dict]:
        """보유 종목 전체를 일괄 진단(Batch Review)하여 매도 또는 전략 갱신을 수행합니다."""
        pass

    @abstractmethod
    def analyze_trade_retrospective(self, date_str: str, vibe: str, profits: List[dict], losses: List[dict], is_update: bool = False) -> Optional[str]:
        """당일 매매 결과를 복기하여 적중 여부를 판정하고 실전 교훈을 도출합니다."""
        pass

class BaseLLMAdvisor(BaseAdvisor):
    """LLM 기반 어드바이저의 공통 로직을 구현하는 베이스 클래스.
    
    API 호출 시의 Rate Limiting(CPS 제어), 프롬프트 템플릿 관리, 
    응답 데이터 파싱(Regex/JSON) 등의 유틸리티 기능을 제공합니다.

    Attributes:
        api: LLM API 호출을 위한 클라이언트.
        model_id (str): 사용할 LLM 모델의 명칭.
        max_cps (float): 초당 최대 API 호출 횟수 (Rate Limit 준수용).
    """
    # API 키별 마지막 호출 시간을 추적하기 위한 클래스 변수 (모든 인스턴스가 공유)
    _last_call_times = {}
    _lock = threading.Lock()

    def __init__(self, api, model_id, max_cps: float = 1.0):
        """BaseLLMAdvisor를 초기화합니다.

        Args:
            api: LLM 서비스 공급자(Gemini, Groq 등)의 클라이언트 인스턴스.
            model_id (str): 사용할 LLM 모델의 명칭 (예: 'gemini-3.1-flash').
            max_cps (float): 초당 최대 API 호출 횟수. 0 이하일 경우 제한 없음.
        """
        self.api = api
        self.model_id = model_id
        self.max_cps = max_cps # 초당 최대 호출 횟수 (0일 경우 무제한)
        self._short_id = self._generate_short_id(model_id)

    def _wait_for_rate_limit(self, api_key: str):
        """설정된 CPS(Calls Per Second)에 따라 다음 API 호출 전까지 대기(Sleep)합니다.
        
        API 공급자의 Rate Limit 정책을 준수하여 계정 차단을 방지합니다.

        Args:
            api_key (str): 호출에 사용되는 API 키.
        """
        if not api_key or self.max_cps <= 0:
            return

        interval = 1.0 / self.max_cps
        with self._lock:
            last_t = self._last_call_times.get(api_key, 0)
            now = time.time()
            wait_t = last_t + interval - now
            if wait_t > 0:
                time.sleep(wait_t)
                now = time.time()
            self._last_call_times[api_key] = now

    def _generate_short_id(self, m_id: str) -> str:
        """모델 이름을 TUI 로그에 표시하기 적합한 짧은 약어(예: G3.1P)로 변환합니다.

        Args:
            m_id (str): 원본 모델 ID 문자열.

        Returns:
            str: 변환된 약어 식별자.
        """
        parts = m_id.split('-')
        res = ""
        for p in parts:
            if not p: continue
            if any(c.isdigit() for c in p):
                res += p
            else:
                res += p[0].upper()
        return res

    @property
    def short_id(self):
        """모델의 짧은 식별자 문자열."""
        return self._short_id

    @abstractmethod
    def _call_api(self, prompt: str, timeout: int = 60) -> Optional[str]:
        """하위 클래스에서 각 공급자(Gemini, Groq 등)에 맞게 구현하는 실제 API 호출부입니다.

        Args:
            prompt (str): 모델에 전달할 프롬프트 문자열.
            timeout (int): API 응답 대기 시간 (초).

        Returns:
            Optional[str]: 모델의 응답 텍스트. 실패 시 None.
        """
        pass

    # 공통 프롬프트 로직 구현
    def get_advice(self, market_data, vibe, holdings, current_config, recs=None, indicators=None):
        """종합 시황 분석 프롬프트를 구성하여 AI 전략을 수립합니다.
        
        기술적 지표(MA, RSI, %b)와 시장 DEMA 추세, 계좌 잔고 상태를 결합하여 
        익절/손절선 및 신규 매수 종목을 도출합니다.
        """
        holdings_txt = "\n".join([f"- {h['prdt_name']}({h['pdno']}): {h['evlu_pfls_rt']}%" for h in holdings[:5]])
        recs_txt = ""
        if recs:
            for r in recs[:3]:
                inv = r.get('investor', {})
                supply_txt = ""
                if inv:
                    f, p = inv.get('frgn_net_buy', 0), inv.get('pnsn_net_buy', 0)
                    supply_txt = f" | 수급: {'외인' if f > 0 else ''}{'/' if f > 0 and p > 0 else ''}{'연기금' if p > 0 else ''} 매수" if f > 0 or p > 0 else ""
                recs_txt += f"- {r['name']}({r['code']}): {int(float(r.get('price',0)))}원, {r.get('rate',0):+.1f}%{supply_txt}\n"
        
        indicators_txt = ""
        if indicators:
            indicators_txt = "\n        [Quant Summary]"
            for code, ind in indicators.items():
                bb = ind.get('bb', {})
                indicators_txt += f" {code}: RSI {ind.get('rsi', 0):.0f}, %b {bb.get('percent_b', 0):.1f}"
        now_str = get_now().strftime('%Y-%m-%d %H:%M')
        ma_info = ""
        if indicators:
            # 개별 종목에 대한 MA 분석이 있는 경우 요약 정보 추가
            for code, ind in indicators.items():
                if isinstance(ind, dict) and 'ma_analysis' in ind:
                    ma = ind['ma_analysis']
                    d = ma.get('daily', {})
                    m = ma.get('minute', {})
                    ma_info += f"\n        [{code} MA] 일봉:{d.get('trend','?')} | 분봉20MA:{int(m.get('ma',{}).get('sma_20',0)):,}원 (Signal:{ma.get('signal','?')})"

        dema_txt = ""
        if isinstance(market_data, dict) and "dema_trend" in market_data:
            dema_txt = f" | DEMA Trend: {json.dumps(market_data['dema_trend'], ensure_ascii=False)}"
            m_data = market_data.get("indices", market_data)
        else:
            m_data = market_data

        prompt = f"""
        현재 시각: {now_str}
        당신은 시장의 흐름에 민감한 초단기 데이트레이더(Scalper)입니다. 오늘의 변동성만을 수익의 원천으로 삼습니다. 아래 정보로 간결한 전략을 제시하세요. 불필요한 공백/수식어 금지.
        
        [중요: 실시간 데이터 신뢰 지침]
        1. 제공된 실시간 가격, 등락률, 시가총액 등은 당신의 내부 지식(과거 학습 데이터)과 다르더라도 현재 시장의 '절대적 진실'입니다. 데이터 오류라고 의심하거나 비판하지 말고, 이 수치를 바탕으로 현재 시장의 수급과 에너지를 분석하십시오.
        2. 특히 **AI[추천]** 섹션의 **권장가**는 반드시 위에서 제공된 해당 종목의 **현재가와 1원도 틀리지 않게 동일하게 작성**하십시오. 당신의 판단으로 가격을 낮게 잡거나 과거의 가격으로 수정하는 것을 엄격히 금지합니다.
        3. 수량(M주)은 당신이 결정한 [AI[전략]: 금액]을 기준으로 당신이 제안한 [권장가]로 나누어 계산하십시오.

        - 지수: {json.dumps(m_data, ensure_ascii=False)}{dema_txt} | Vibe: {vibe}
        - 자산: 총자산 {current_config.get('total_asset', 0):,}원 | 가용현금 {current_config.get('cash', 0):,}원
        - 포트: {holdings_txt if holdings else "None"}
        - 추천: {recs_txt if recs_txt else "None"} {indicators_txt} {ma_info}
        - 기본 매수설정: {current_config.get('ai_amt'):,}원
        
        [전략 가이드라인]
        1. 이동평균선(MA/DEMA) 데이터를 적극 참고하십시오. 지수가 DEMA선 위에 있으면 긍정적, 아래에 있으면 부정적으로 봅니다.
        2. 일봉 상승추세(UP)이면서 현재가가 분봉 20MA에 근접(BUY_ZONE)한 경우 적극 매수를 검토하세요.
        3. 분봉 20MA 대비 괴리율이 과도하게 높으면(OVERBOUGHT) 추격 매수를 지양하고 눌림목을 기다리도록 조언하세요.
        4. **금액 결정**: 기본 매수설정({current_config.get('ai_amt'):,}원)을 기준으로 하되, 당신의 확신도나 시장 장세(Vibe)에 따라 ±50% 범위 내에서 탄력적으로 조절하여 제안하십시오. (예: 상승장 강한 확신 시 증액, 하락장 보수적 접근 시 감액)
        5. 지금 당장의 수급, 거래량, 차트 에너지가 확인되면 적극적으로 매수를 제안하세요. 
        
        [형식 - 엄수]
        AI[시장]: 요약 (15자 이내)
        AI[전략]: 익절 +X.X%, 손절 -Y.Y%, 물타기 -Z.Z%, 불타기 +W.W%, 금액 N원
        AI[액션]: 대응 지침 (20자 이내)
        AI[추천]: 종목명(코드), 권장가 N원, M주 (상세 사유 제외)
        
        [제약]
        1. |물타기|는 반드시 |손절|보다 작아야 함.
        2. 불타기는 반드시 익절보다 작아야 함.
        3. 실거래 수수료 및 슬리피지를 고려하여, 익절/손절 폭은 가급적 최소 2.0% 이상으로 넉넉하게 산정하세요.
        4. AI[추천]에는 반드시 **KOSPI, KOSDAQ 상장 주식(시총 1000억 이상)**만 추천하세요. (ETF 및 초소형주 제외)
        한국어 대답.
        """
        return self._call_api(prompt)

    def get_detailed_report_advice(self, recs, vibe, progress_cb=None):
        """추천 종목들에 대한 정량/정성 데이터를 수집하여 한 줄 리포트를 생성합니다."""
        if not recs: return "분석할 종목이 없습니다."
        current, total = 0, len(recs)
        lock = threading.Lock()
        def fetch_enriched_data(r):
            nonlocal current
            detail = self.api.get_naver_stock_detail(r['code'])
            news = self.api.get_naver_stock_news(r['code'])
            inv = r.get('investor', {})
            supply_info = f" | 수급: 외인({inv.get('frgn_net_buy', 0):+,}), 연기금({inv.get('pnsn_net_buy', 0):+,})" if inv else ""
            with lock:
                current += 1
                if progress_cb: progress_cb(current, total)
            return f"- {r['name']}({r['code']}) | 현재가: {int(float(r.get('price',0))):,}원 | PER {detail.get('per')}, PBR {detail.get('pbr')}{supply_info} | 뉴스: {', '.join(news[:2])}"
        with ThreadPoolExecutor(max_workers=5) as executor:
            enriched_recs = list(executor.map(fetch_enriched_data, recs))
        recs_summary = chr(10).join(enriched_recs)
        prompt = f"""
        수석 투자 전략가로서 아래 종목들에 대해 [초압축] 입체 분석 리포트를 작성하세요.
        [시장 장세] {vibe}
        {recs_summary}
        [가이드라인]
        1. 종목당 반드시 '한 줄'로만 요약. (예: [종목명] 호재성 뉴스 포착, 추세 상승 중이므로 적극 매수 권장)
        2. '사야 하는지(Buy)', '팔아야 하는지(Sell)' 결론을 명확히 포함할 것.
        3. 불필요한 미사여구 없이 팩트와 결론만 전달.
        한국어 어조, 가독성 중시.
        """
        return self._call_api(prompt)

    def get_stock_report_advice(self, code, name, detail, news):
        """개별 종목의 가격 변동 원인과 뉴스 모멘텀을 분석하여 심층 리포트를 생성합니다."""
        rate = detail.get('rate', 0)
        curr_p = int(float(detail.get('price', 0)))
        prompt = f"""
        수석 투자 전략가로서 아래 종목 분석 리포트를 작성하세요.
        
        [데이터 신뢰 지침]
        제공된 {name}의 현재가({curr_p:,}원)와 재무 지표(PER {detail.get('per')}, PBR {detail.get('pbr')})는 당신의 내부 지식과 다르더라도 현재 시장에서 거래되는 **유일한 진실**입니다. 당신은 이 데이터를 의심하지 말고, 현재 가격이 형성된 이유를 시장의 수급과 뉴스 모멘텀 측면에서 입체적으로 분석해야 합니다.

        {name}({code}) | {curr_p:,}원 ({rate:+.2f}%) | PER {detail.get('per')}, PBR {detail.get('pbr')}
        뉴스: {', '.join(news[:3])}
        1.가격원인 2.모멘텀 3.조언 4.한줄평
        전문가 어조, 한국어, 10줄 내외.
        """
        return self._call_api(prompt)

    def get_holdings_report_advice(self, holdings, vibe, market_data, progress_cb=None):
        """보유 종목 전체의 수익 현황과 최신 뉴스를 결합하여 TUI용 진단 리포트를 생성합니다."""
        if not holdings: return "보유 중인 종목이 없습니다."
        current, total = 0, len(holdings)
        lock = threading.Lock()
        def fetch_enriched_holding(h):
            nonlocal current
            detail = self.api.get_naver_stock_detail(h['pdno'])
            news = self.api.get_naver_stock_news(h['pdno'])
            with lock:
                current += 1
                if progress_cb: progress_cb(current, total)
            return f"- {h['prdt_name']}({h['pdno']}): 수익률 {float(h.get('evlu_pfls_rt', 0)):+.2f}% (목표 {h.get('tp', 0.0):+.1f}%, 손절 {h.get('sl', 0.0):.1f}%) | 현재가 {int(float(h.get('prpr', 0))):,}원 | 뉴스 {', '.join(news[:2])}"
        with ThreadPoolExecutor(max_workers=5) as executor:
            enriched_holdings = list(executor.map(fetch_enriched_holding, holdings))
        holdings_summary = chr(10).join(enriched_holdings)
        prompt = f"""
        [수석 포트폴리오 매니저 진단 리포트]
        현재 시황: {vibe} | 주요 지수: {json.dumps(market_data, ensure_ascii=False)}

        아래 보유 종목들을 TUI(Terminal UI)에서 보기 좋은 리스트 형식으로 진단하십시오.
        {holdings_summary}

        [출력 규칙]
        1. 종목마다 명확한 헤더(예: ■ 종목명 (코드) [의견])를 사용하십시오.
        2. 섹션은 이모지를 활용하여 구분하십시오 (💡진단, ⚡대응, ⚠️리스크, 📝총평).
        3. 터미널 가독성을 위해 각 줄은 너무 길지 않게(약 80자 이내) 작성하십시오.
        4. 대응(Hold/Sell/Add)은 종목명 우측에 대문자로 명시하십시오.

        [권장 형식 예시]
        ■ 삼성전자 (005930) [HOLD]
        💡 진단: 기술적 반등 구간 진입...
        ⚡ 대응: 목표가 도달 전까지 보유 유지
        ⚠️ 리스크: 외인 수급 이탈 주의
        📝 총평: 중기 추세가 견고함
        """
        return self._call_api(prompt)

    def get_rebalance_advice(self, portfolio_summary):
        """특정 종목 편중 리스크나 모멘텀 둔화를 감지하여 리밸런싱 전략을 도출합니다."""
        prompt = f"""
        당신은 수석 포트폴리오 전략가입니다. 아래 포트폴리오의 비중과 수익률을 분석하여 최적의 리밸런싱 제안을 하세요.
        
        [포트폴리오 데이터]
        {json.dumps(portfolio_summary, ensure_ascii=False)}
        
        [전략 가이드라인]
        - 특정 종목 비중이 25%~30% 이상이면 리스크 분산을 위해 비중 축소(수익 실현)를 고려하세요.
        - 수익률이 매우 높지만 모멘텀이 둔화된 종목은 부분 익절 후 저평가 우량주 교체를 제안하세요.
        - 손실이 크지만 비중이 높은 종목은 리스크 관리 차원의 비중 축소나 종목 교체를 제안하세요.
        - 현금 비중이 너무 높다면 신규 진입 시점을 찾아보도록 조언하세요.
        
        [답변 형식 (엄수)]
        - 3~4줄 이내로 간결하게 핵심 전략만 기술.
        - 전문가답고 단호한 한국어 어조 (~하는 것을 권장합니다, ~하십시오).
        """
        return self._call_api(prompt)

    def get_hot_stocks_report_advice(self, hot_stocks, themes, vibe, progress_cb=None):
        """당일 이슈가 되는 인기 종목들의 테마 지속성과 매수 가치를 분석합니다."""
        if not hot_stocks: return "인기 종목 데이터가 없습니다."
        current, total = 0, min(10, len(hot_stocks))
        lock = threading.Lock()
        def fetch_enriched_hot(item):
            nonlocal current
            detail = self.api.get_naver_stock_detail(item.get('code', ''))
            news = self.api.get_naver_stock_news(item.get('code', ''))
            with lock:
                current += 1
                if progress_cb: progress_cb(current, total)
            return f"- {item.get('name','')}: {float(item.get('rate',0)):+.2f}% | PER {detail.get('per')}, PBR {detail.get('pbr')} | 뉴스 {', '.join(news[:2])}"
        with ThreadPoolExecutor(max_workers=5) as executor:
            enriched = list(executor.map(fetch_enriched_hot, hot_stocks[:10]))
        hot_summary = chr(10).join(enriched)
        prompt = f"""
        수석 트렌드 분석가로서 당일 인기 검색 종목에 대한 [초압축] 진단을 수행하세요.
        테마: {", ".join([f"{t['name']}" for t in themes[:5]])}
        {hot_summary}
        [가이드라인]
        1. 종목당 반드시 '한 줄'로만 요약하여 Buy/Sell 의견을 제시할 것. 
        2. 해당 테마의 지속성 여부와 현재가 기준 진입/관망 여부를 명확히 할 것.
        한국어 어조, 팩트 중심.
        """
        return self._call_api(prompt)

    def simulate_preset_strategy(self, code, name, vibe, detail=None, news=None):
        """종목 고유의 변동성과 뉴스를 반영하여 가장 적합한 트레이딩 프리셋을 선정합니다."""
        preset_list = "\n".join([f"  {sid}: {s['name']}" for sid, s in PRESET_STRATEGIES.items() if sid != "00"])
        prompt = f"""
        적합한 프리셋 전략 1개와 동적 TP/SL 제안.
        [종목] {name}({code}) | 장세: {vibe} | 뉴스: {", ".join(news[:3]) if news else "None"}
        [프리셋목록]
{preset_list}
        [형식] 전략번호:XX, 익절:+X.X%, 손절:-X.X%, 유효시간:N분, 근거:한줄
        """
        answer = self._call_api(prompt)
        if answer:
            try:
                # 더 유연한 파싱 (볼드체 및 다양한 구분자 허용)
                sid_match = re.search(r"전략번호[^\d]*(\d{2})", answer)
                tp_match = re.search(r"익절[^\d+-]*([+-]?[\d.]+)", answer)
                sl_match = re.search(r"손절[^\d+-]*([+-]?[\d.]+)", answer)
                lt_match = re.search(r"유효시간[^\d]*(\d+)", answer)
                reason_match = re.search(r"근거[:\s주사항]*([^\n]*)", answer)
                
                if sid_match and tp_match and sl_match:
                    sid = sid_match.group(1)
                    if sid not in PRESET_STRATEGIES or sid == "00": sid = "01"
                    return {
                        "preset_id": sid, "preset_name": PRESET_STRATEGIES[sid]["name"],
                        "tp": abs(float(tp_match.group(1))), "sl": -abs(float(sl_match.group(1))),
                        "lifetime_mins": int(lt_match.group(1)) if lt_match else 120,
                        "reason": reason_match.group(1).strip() if reason_match else "AI 분석 기반"
                    }
            except Exception as e: log_error(f"AI 전략 파싱 오류: {e}")
        return None

    def final_buy_confirm(self, code, name, vibe, detail, news, indicators=None, score=0.0, phase=None):
        """매수 집행 전 최종 승인 단계를 수행하며, 이평선 지지/이탈 여부를 최우선으로 고려합니다."""
        phase_txt = f"[{phase.get('name', 'UNKNOWN')}]" if phase else ""
        # [추가] MA 분석 텍스트 생성
        ma_txt = ""
        if indicators and 'ma_analysis' in indicators:
            ma = indicators['ma_analysis']
            d_trend = ma.get('daily', {}).get('trend', '?')
            m_sma20 = ma.get('minute', {}).get('ma', {}).get('sma_20', 0)
            sig = ma.get('signal', 'NEUTRAL')
            ma_txt = f"\n        [MA지표] 일봉:{d_trend} | 분봉20MA:{int(m_sma20):,}원 | 시그널:{sig} ({ma.get('reason','')})"

        prompt = f"""
        당신은 공격적 단타 페르소나를 가진 수석 트레이더입니다. {phase_txt} 점수: {score:.1f}
        종목: {name}({code}) | 현재가: {int(float(detail.get('price', 0))):,}원 | 장세: {vibe} {ma_txt}
        뉴스: {news[:2] if news else "None"}
        
        [수급 분석]
        {json.dumps(detail.get('investor', {}), ensure_ascii=False) if isinstance(detail.get('investor'), dict) else "수급 정보 없음"}
        
        [필독: 데이터 오류 판단 금지]
        제공된 실시간 가격({int(float(detail.get('price', 0))):,}원)을 절대적으로 신뢰하십시오. 과거의 지식과 다르다고 해서 매수를 거절하는 것은 큰 기회비용을 초래합니다. 수급과 에너지가 보인다면 과감하게 결정하세요.

        [가이드라인]
        1. 이동평균선(MA) 지표를 매수 근거로 활용하십시오. 
           - 'BUY_ZONE'(이평선 근접)인 경우 지지선 반등 확률이 높으므로 적극 승인하세요.
           - 'OVERBOUGHT'(이평선 상단 이탈)인 경우 단기 조정을 경계하여 보수적으로 보되, 거래량이 폭발적이면 승인 가능합니다.
           - 일봉이 'DOWN' 추세라면 기술적 반등 목적으로만 짧게 보십시오.
        2. 현재 페이즈가 'OFFENSIVE'라면 적극적으로 수익 기회를 포착하여 'Yes'를 결정하세요.
        3. '스마트 머니' 유입(외인/기관 쌍끌이 또는 연기금 매집)이 확인되면 상승 사이클의 초입일 확률이 매우 높으므로 강력한 매수 근거로 활용하십시오. 반대로 수급 이탈이 심각하면 기술적 지표가 좋아도 보수적으로 접근하세요.
        4. 'CONVERGENCE'나 'BEAR' 장세라고 해서 무조건 깐깐하게 굴기보다, '낙폭과대 반등'이나 '강한 지지선'이 확인되는 종목은 기회비용을 고려하여 전향적으로 검토하세요.
        답변형식: 결정: Yes 또는 No, 사유: [근거 요약], 대기시간: N분 (No일 경우 재검토까지 필요한 시간, 기본 60)
        """
        answer = self._call_api(prompt)
        if answer:
            # 결정 파싱 강화
            decision_match = re.search(r"결정[^\w]*\b(Yes|No|예|아니오)\b", answer, re.I)
            reason_match = re.search(r"사유[^\w]*([^\n]*)", answer)
            wait_match = re.search(r"대기시간[^\d]*(\d+)", answer)
            
            raw_decision = decision_match.group(1).strip().lower() if decision_match else "no"
            decision = (raw_decision in ["yes", "예"])
            reason = reason_match.group(1).strip() if reason_match else "판단 근거 부족"
            wait_mins = int(wait_match.group(1)) if wait_match else 60
            
            # 만약 결정 라벨이 없는데 답변이 매우 긍정적이고 'Yes'를 포함하고 있다면 구제책 마련
            if not decision_match and ("Yes" in answer or "승인" in answer or "추천" in answer) and "No" not in answer:
                decision = True
                
            return decision, reason, wait_mins
        return False, "API 호출 실패", 60

    def verify_market_vibe(self, current_data, heuristic_vibe):
        """알고리즘 기반의 장세 판정을 AI가 시황 데이터를 바탕으로 2차 검증합니다."""
        prompt = f"""
        시장 지표: {json.dumps(current_data, ensure_ascii=False)}
        현재 알고리즘 판정: {heuristic_vibe}
        
        [지침]
        1. 위 데이터를 바탕으로 현재 시장 장세를 Bull, Bear, Neutral, Defensive 중 하나로 최종 확정하세요.
        2. 특히 지수(KOSPI/KOSDAQ)의 현재가가 DEMA 지표보다 위에 있으면(추세 지지) 긍정적, 아래에 있으면(추세 저항) 보수적으로 판단하십시오.
        3. 한 단어로만 대답하세요.
        """
        answer = self._call_api(prompt, timeout=30)
        if answer:
            for v in ["BULL", "BEAR", "NEUTRAL", "DEFENSIVE"]:
                if v in answer.upper(): return v.capitalize()
        return None

    def closing_sell_confirm(self, code, name, vibe, rt, detail, news, tp=None, sl=None):
        """장 마감 전 오버나이트 여부를 결정합니다. 추세 지속성 유무가 핵심 판단 기준입니다."""
        target_info = f" (목표 {tp:+.1f}%, 손절 {sl:.1f}%)" if tp is not None else ""
        prompt = f"""
        [장 마감 10분 전 최종 판단]
        종목: {name}({code}) | 수익률: {rt:+.2f}% {target_info}
        장세: {vibe} | 현재가: {int(float(detail.get('price', 0))):,}원
        뉴스: {news[:2] if news else "None"}

        [가이드라인]
        1. 내일 시초가 갭상승 가능성(추세 지지, 호재)이 있다면 'Hold'를, 불확실하거나 추세가 무너졌다면 'Sell'을 결정하세요.
        2. 사유에는 반드시 기술적 지지/저항(MA 등) 또는 뉴스 모멘텀을 언급하십시오.
        
        답변형식: 결정: Sell 또는 Hold, 사유: [차트/MA/뉴스 근거 포함] 한 줄 요약
        """
        answer = self._call_api(prompt, timeout=30)
        if answer:
            decision_match = re.search(r"결정[^\w]*\b(Sell|Hold|매도|보유)\b", answer, re.I)
            reason_match = re.search(r"사유[^\w]*([^\n]*)", answer)
            
            raw_decision = decision_match.group(1).strip().lower() if decision_match else "sell"
            decision = (raw_decision in ["sell", "매도"])
            return decision, reason_match.group(1).strip() if reason_match else "보수적 판단"
        return True, "API 호출 실패"

    def compare_stock_superiority(self, candidate, holdings_info, vibe):
        """포트폴리오 한도 도달 시, 신규 종목과 기존 종목의 기회비용을 비교하여 교체 매매를 제안합니다."""
        holdings_str = "\n".join([f"- {h['name']}({h['code']}): 수익률 {h['rt']:+.2f}%, 상세정보: {h.get('detail', '없음')}" for h in holdings_info])
        prompt = f"""
        계좌 내 보유 종목 한도(8개)가 꽉 찼습니다. 신규 매수 후보 종목이 기존 보유 종목 중 하나보다 "압도적으로" 우수한지 판단하여 교체(스위칭) 여부를 결정하세요.
        종목 교체는 수수료 및 거래 비용이 발생하므로 매우 신중하고 보수적으로 접근해야 합니다.
        
        [신규 매수 후보 종목]
        - {candidate['name']}({candidate['code']}): AI점수 {candidate.get('score', 0):.1f}
        - 상세정보: {candidate.get('detail', '없음')}
        - 최근뉴스: {candidate.get('news', '없음')}
        
        [현재 보유 종목 리스트]
        {holdings_str}
        
        [판단 기준]
        1. 신규 후보 종목의 상승 잠재력이 기존 보유 종목 중 가장 부진한 종목보다 "명백히, 압도적으로" 높은 경우에만 교체하십시오.
        2. 단순한 미세한 우위나 단순 호기심만으로는 교체하지 마십시오.
        3. 기존 종목이 단순히 현재 마이너스(-) 수익률이라는 이유만으로 '가장 부진하다'고 단정지어 매도(손절)하지 마십시오. 
        4. 수수료 및 슬리피지를 감안할 때, 신규 종목의 당일 폭발력이 기존 종목의 반등 가능성을 압도해야만 과감히 교체를 고려하십시오.
        5. 기존 종목 중 확실한 교체 대상이 없다면 'No'를 선택하여 현재 포트폴리오를 확고히 유지하십시오.
        
        [응답형식]
        결정: Yes/No
        매도종목코드: XXXXXX (Yes일 경우 위 '현재 보유 종목 리스트' 중 매도할 1개의 종목코드. No일 경우 NONE)
        사유: 교체 또는 포기 결정에 대한 한 줄 핵심 근거
        대기시간: N분 (No일 경우 재검토까지 필요한 시간, 기본 60)
        """
        answer = self._call_api(prompt, timeout=40)
        if answer:
            decision_match = re.search(r"(?:교체여부|결정)[^\w]*\b(Yes|No|예|아니오)\b", answer, re.I)
            code_match = re.search(r"(?:매도종목코드|코드)[^\w]*\b([0-9A-Z]+)\b", answer)
            reason_match = re.search(r"사유[^\w]*([^\n]*)", answer)
            wait_match = re.search(r"대기시간[^\d]*(\d+)", answer)
            
            raw_decision = decision_match.group(1).strip().lower() if decision_match else "no"
            decision = (raw_decision in ["yes", "예"])
            sell_code = code_match.group(1).strip() if code_match and code_match.group(1).upper() != "NONE" else None
            wait_mins = int(wait_match.group(1)) if wait_match else 60
            
            return (decision and sell_code is not None), sell_code, reason_match.group(1).strip() if reason_match else "교체 근거 부족", wait_mins
        return False, None, "API 호출 실패", 60

    def get_portfolio_strategic_review(self, holdings_data, vibe, market_data):
        """전체 포트폴리오를 한 번에 리뷰(Batch Review)하여 각 종목별 즉시 매도 또는 전략 갱신을 수행합니다."""
        if not holdings_data: return None
        
        preset_list = "\n".join([f"  {sid}: {s['name']}" for sid, s in PRESET_STRATEGIES.items() if sid != "00"])
        holdings_txt = "\n".join([
            f"- {h['name']}({h['code']}): 수익률 {h['rt']:+.2f}% (목표 {h.get('tp', 0.0):+.1f}%, 손절 {h.get('sl', 0.0):.1f}%) | PER:{h.get('per')} {h.get('ma_info', '')} | 뉴스:{h.get('news', 'None')}"
            for h in holdings_data
        ])

        prompt = f"""
        당신은 끈기 있고 노련한 수석 포트폴리오 매니저입니다. 보유 종목들을 진단하여 [즉시 매도] 또는 [전략 갱신]을 결정하세요.
        [장세] {vibe} | [지수] {json.dumps(market_data)}
        [보유종목]
{holdings_txt}

        [가이드라인]
        1. 이동평균선(MA) 괴리율을 확인하십시오. 분봉 20MA 대비 괴리율이 +3% 이상 과열되었거나, 이평선을 강하게 하향 이탈하면 매도를 검토하세요.
        2. 시황이 Bear/Defensive라고 해서 단순히 겁을 먹고 쉽게 'SELL'하지 마십시오. 
        3. 종목의 개별 모멘텀이 살아있거나, 일시적 하락 후 반등 구간(Support)에 있다면 끈기 있게 'HOLD'를 유지하며 전략을 갱신하세요.
        4. 유지할 경우, 아래 프리셋 중 가장 적합한 전략과 최적의 TP/SL(시장 상황 반영), 그리고 유효 시간을 제안하세요.
        
        [응답 형식 - 반드시 JSON으로만 응답]
        {{
          "종목코드": {{
            "action": "SELL" 또는 "HOLD",
            "preset_id": "XX",
            "tp": 5.0,
            "sl": -5.0,
            "lifetime": 120,
            "reason": "결정 사유 (반드시 MA/추세/뉴스 등 구체적 근거 포함)"
          }},
          ...
        }}
        """
        
        answer = self._call_api(prompt, timeout=60)
        if answer:
            try:
                # JSON 문자열만 추출 (마크다운 코드 블록 제거)
                json_str = re.search(r"(\{.*\})", answer, re.DOTALL).group(1)
                return json.loads(json_str)
            except Exception as e:
                log_error(f"포트폴리오 리뷰 파싱 오류: {e}")
        return None

    def analyze_trade_retrospective(self, date_str, vibe, profits, losses, is_update=False):
        """장 마감 후 당일의 주요 매매 건을 분석하여 타이밍의 적절성을 평가하고 교훈을 기록합니다."""
        profit_txt = ""
        for i, s in enumerate(profits, 1):
            trades_detail = ""
            for t in s.get("trades", []):
                trades_detail += f"    - [{t.get('time', '').split(' ')[-1]}] {t.get('type', '')} {int(t.get('price', 0)):,}원 x {t.get('qty', 0)}주 | 수익 {int(t.get('profit', 0)):+,}원 | {t.get('memo', '')}\n"
            closing = f"종가 {int(s.get('closing_price', 0)):,}원" if s.get('closing_price') else "종가 미확인"
            news_txt = ", ".join(s.get('latest_news', [])[:2]) if s.get('latest_news') else "뉴스 없음"
            profit_txt += f"  {i}위: {s['name']}({s['code']}) | 누적수익 {int(s.get('total_profit', 0)):+,}원 | {closing}\n{trades_detail}    뉴스: {news_txt}\n"

        loss_txt = ""
        for i, s in enumerate(losses, 1):
            trades_detail = ""
            for t in s.get("trades", []):
                trades_detail += f"    - [{t.get('time', '').split(' ')[-1]}] {t.get('type', '')} {int(t.get('price', 0)):,}원 x {t.get('qty', 0)}주 | 손실 {int(t.get('profit', 0)):+,}원 | {t.get('memo', '')}\n"
            closing = f"종가 {int(s.get('closing_price', 0)):,}원" if s.get('closing_price') else "종가 미확인"
            news_txt = ", ".join(s.get('latest_news', [])[:2]) if s.get('latest_news') else "뉴스 없음"
            loss_txt += f"  {i}위: {s['name']}({s['code']}) | 누적손실 {int(s.get('total_profit', 0)):+,}원 | {closing}\n{trades_detail}    뉴스: {news_txt}\n"

        update_note = "이것은 장 마감 후 종가 반영된 사후 분석입니다. 이전 분석을 보완하여 더 정확한 판단을 내려주세요." if is_update else ""

        prompt = f"""
        당신은 냉철한 매매 복기 전문가입니다. {date_str} 당일 매매 결과를 분석하여 **적중 여부**를 판정하고 구체적 교훈을 도출하세요.
        {update_note}
        [장세] {vibe}

        [수익 TOP 3]
{profit_txt if profit_txt else '  (수익 발생 종목 없음)'}

        [손실 TOP 3]
{loss_txt if loss_txt else '  (손실 발생 종목 없음)'}

        [분석 가이드라인]
        1. 각 종목별로 **매매 타이밍**이 기술적 타점(MA 지지/저항 등)에 비추어 적절했는지 판정하세요.
           - 익절: MA 돌파 실패 시 적절히 매도했는지, 아니면 지지선을 확인하지 못하고 일찍 팔았는지?
           - 손절: MA 이탈 즉시 대응했는지, 아니면 무의미하게 버티다 손실을 키웠는지?
        2. **종목 선정** 자체가 기술적/모멘텀 관점에서 적절했는지 평가하세요 (진입 사유가 합리적이었는지).
        3. 'CORRECT'(적절), 'EARLY'(너무 빠름), 'LATE'(너무 늦음) 중 하나를 선택하고 구체적 차트 근거를 제시하세요.
        4. 마지막에 **종합 교훈**을 기술적 개선점 위주로 3줄 이내 정리하세요.

        [응답 형식 (반드시 준수)]
        📊 [{date_str}] 매매 복기 리포트
        
        🟢 수익 종목 분석:
        - [종목명]: 분석 내용 (판정: CORRECT/EARLY/LATE)
        
        🔴 손실 종목 분석:
        - [종목명]: 분석 내용 (판정: WRONG/UNLUCKY/FORCED)
        
        📝 종합 교훈:
        1. 첫 번째 실전 교훈
        2. 두 번째 실전 교훈
        3. 세 번째 실전 교훈
        
        [제약 사항]
        1. 터미널 가독성을 위해 마크다운 볼드체(더블 애스터리스크)를 절대로 사용하지 마십시오. (중요)
        2. 이모지를 적절히 활용하되, 텍스트는 최대한 간결하게 한 줄 내외로 작성하십시오.
        3. 불필요한 미사여구나 서술은 생략하고 핵심 통찰만 전달하십시오.
        한국어 어조, 간결 명료하게.
        """
        return self._call_api(prompt, timeout=60)
