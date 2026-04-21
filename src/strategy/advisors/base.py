import json
import re
import threading
import time
from abc import ABC, abstractmethod
from typing import List, Tuple, Optional, Callable
from concurrent.futures import ThreadPoolExecutor
from src.logger import log_error
from src.strategy.constants import PRESET_STRATEGIES

class BaseAdvisor(ABC):
    @abstractmethod
    def get_advice(self, market_data: dict, vibe: str, holdings: List[dict], current_config: dict, recs: List[dict] = None, indicators: dict = None) -> Optional[str]:
        pass

    @abstractmethod
    def get_detailed_report_advice(self, recs: List[dict], vibe: str, progress_cb: Optional[Callable] = None) -> Optional[str]:
        pass

    @abstractmethod
    def get_stock_report_advice(self, code: str, name: str, detail: dict, news: List[str]) -> Optional[str]:
        pass

    @abstractmethod
    def get_holdings_report_advice(self, holdings: List[dict], vibe: str, market_data: dict, progress_cb: Optional[Callable] = None) -> Optional[str]:
        pass

    @abstractmethod
    def get_hot_stocks_report_advice(self, hot_stocks: List[dict], themes: List[dict], vibe: str, progress_cb: Optional[Callable] = None) -> Optional[str]:
        pass

    @abstractmethod
    def simulate_preset_strategy(self, code: str, name: str, vibe: str, detail: dict = None, news: List[str] = None) -> Optional[dict]:
        pass

    @abstractmethod
    def final_buy_confirm(self, code: str, name: str, vibe: str, detail: dict, news: List[str], indicators: dict = None, score: float = 0.0) -> Tuple[bool, str]:
        pass

    @abstractmethod
    def verify_market_vibe(self, current_data: dict, heuristic_vibe: str) -> Optional[str]:
        pass

    @abstractmethod
    def closing_sell_confirm(self, code: str, name: str, vibe: str, rt: float, detail: dict, news: List[str]) -> Tuple[bool, str]:
        pass

    @abstractmethod
    def compare_stock_superiority(self, candidate: dict, holdings_info: List[dict], vibe: str) -> Tuple[bool, Optional[str], str]:
        pass

class BaseLLMAdvisor(BaseAdvisor):
    # API 키별 마지막 호출 시간을 추적하기 위한 클래스 변수 (모든 인스턴스가 공유)
    _last_call_times = {}
    _lock = threading.Lock()

    def __init__(self, api, model_id, max_cps: float = 1.0):
        self.api = api
        self.model_id = model_id
        self.max_cps = max_cps # 초당 최대 호출 횟수 (0일 경우 무제한)
        self._short_id = self._generate_short_id(model_id)

    def _wait_for_rate_limit(self, api_key: str):
        """API 키별로 설정된 CPS(Calls Per Second)를 준수하도록 대기"""
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
        return self._short_id

    @abstractmethod
    def _call_api(self, prompt: str, timeout: int = 60) -> Optional[str]:
        pass

    # 공통 프롬프트 로직 구현
    def get_advice(self, market_data, vibe, holdings, current_config, recs=None, indicators=None):
        holdings_txt = "\n".join([f"- {h['prdt_name']}({h['pdno']}): {h['evlu_pfls_rt']}%" for h in holdings[:5]])
        recs_txt = ""
        if recs:
            recs_txt = "\n".join([f"- {r['name']}({r['code']}): {int(float(r.get('price',0)))}원, {r.get('rate',0):+.1f}%" for r in recs[:3]])
        indicators_txt = ""
        if indicators:
            indicators_txt = "\n        [Quant Summary]"
            for code, ind in indicators.items():
                bb = ind.get('bb', {})
                indicators_txt += f" {code}: RSI {ind.get('rsi', 0):.0f}, %b {bb.get('percent_b', 0):.1f}"
        prompt = f"""
        당신은 시장의 흐름에 민감한 초단기 데이트레이더(Scalper)입니다. 오늘의 변동성만을 수익의 원천으로 삼습니다. 아래 정보로 간결한 전략을 제시하세요. 불필요한 공백/수식어 금지.
        - 지수: {json.dumps(market_data)} | Vibe: {vibe}
        - 포트: {holdings_txt if holdings else "None"}
        - 추천: {recs_txt if recs_txt else "None"} {indicators_txt}
        - 매수: {current_config.get('ai_amt'):,}원
        [전략 가이드라인]
        1. 장기적 기업 가치나 모호한 불확실성에 매몰되지 마세요. 
        2. 지금 당장의 수급, 거래량, 차트 에너지가 확인되면 적극적으로 매수를 제안하세요. 
        3. 리스크는 타이트한 손절선으로 방어하면 되므로, 진입 기회를 놓치지 않는 것이 중요합니다.
        [형식 - 엄수]
        AI[시장]: 요약 (15자 이내)
        AI[전략]: 익절 +X.X%, 손절 -Y.Y%, 물타기 -Z.Z%, 불타기 +W.W%, 금액 N원
        AI[액션]: 대응 지침 (20자 이내)
        AI[추천]: 종목명(코드), 권장가 N원, M주 (상세 사유 제외)
        [제약]
        1. |물타기|는 반드시 |손절|보다 작아야 함.
        2. 불타기는 반드시 익절보다 작아야 함.
        3. 실거래 수수료 및 슬리피지를 고려하여, 익절/손절 폭은 가급적 최소 2.0% 이상으로 넉넉하게 산정하세요.
        한국어 대답.
        """
        return self._call_api(prompt)

    def get_detailed_report_advice(self, recs, vibe, progress_cb=None):
        if not recs: return "분석할 종목이 없습니다."
        current, total = 0, len(recs)
        lock = threading.Lock()
        def fetch_enriched_data(r):
            nonlocal current
            detail = self.api.get_naver_stock_detail(r['code'])
            news = self.api.get_naver_stock_news(r['code'])
            with lock:
                current += 1
                if progress_cb: progress_cb(current, total)
            return f"- {r['name']}({r['code']}) | 현재가: {int(float(r.get('price',0))):,}원 | PER {detail.get('per')}, PBR {detail.get('pbr')} | 뉴스: {', '.join(news[:2])}"
        with ThreadPoolExecutor(max_workers=5) as executor:
            enriched_recs = list(executor.map(fetch_enriched_data, recs))
        prompt = f"""
        수석 투자 전략가로서 아래 종목들에 대해 [초압축] 입체 분석 리포트를 작성하세요.
        [시장 장세] {vibe}
        {"\n".join(enriched_recs)}
        1. 종목당 반드시 2줄 이내로 요약. 1행:[투자근거/지표], 2행:[목표/손절/전략].
        한국어 어조, 가독성 중시.
        """
        return self._call_api(prompt)

    def get_stock_report_advice(self, code, name, detail, news):
        rate = detail.get('rate', 0)
        prompt = f"""
        수석 투자 전략가로서 아래 종목 분석 리포트를 작성하세요.
        {name}({code}) | {int(float(detail.get('price', 0))):,}원 ({rate:+.2f}%) | PER {detail.get('per')}, PBR {detail.get('pbr')}
        뉴스: {', '.join(news[:3])}
        1.가격원인 2.모멘텀 3.조언 4.한줄평
        전문가 어조, 한국어, 10줄 내외.
        """
        return self._call_api(prompt)

    def get_holdings_report_advice(self, holdings, vibe, market_data, progress_cb=None):
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
            return f"- {h['prdt_name']}({h['pdno']}): 수익률 {float(h.get('evlu_pfls_rt', 0)):+.2f}% | 현재가 {int(float(h.get('prpr', 0))):,}원 | 뉴스 {', '.join(news[:2])}"
        with ThreadPoolExecutor(max_workers=5) as executor:
            enriched_holdings = list(executor.map(fetch_enriched_holding, holdings))
        prompt = f"""
        수석 포트폴리오 매니저 진단 리포트.
        장세: {vibe} | 지수: {json.dumps(market_data)}
        {"\n".join(enriched_holdings)}
        1.진단 2.대응(Hold/Sell/Add) 3.리스크 4.한줄평. 한국어.
        """
        return self._call_api(prompt)

    def get_hot_stocks_report_advice(self, hot_stocks, themes, vibe, progress_cb=None):
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
        prompt = f"""
        수석 트렌드 분석가 인기 테마 리포트.
        테마: {", ".join([f"{t['name']}" for t in themes[:5]])}
        {"\n".join(enriched)}
        당일 트렌드 분석 및 종목별 진단. 한국어.
        """
        return self._call_api(prompt)

    def simulate_preset_strategy(self, code, name, vibe, detail=None, news=None):
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

    def final_buy_confirm(self, code, name, vibe, detail, news, indicators=None, score=0.0):
        prompt = f"""
        최종 매수 컨펌 (공격적 트레이더). 점수: {score:.1f}
        종목: {name}({code}) | 장세: {vibe} | 뉴스: {news[:2] if news else "None"}
        답변형식: 결정: Yes 또는 No, 사유: 한 줄 요약
        """
        answer = self._call_api(prompt)
        if answer:
            # 결정 파싱 강화: 마크다운 강조, 한글 답변, 다양한 구분자 대응
            decision_match = re.search(r"결정[^\w]*\b(Yes|No|예|아니오)\b", answer, re.I)
            reason_match = re.search(r"사유[^\w]*([^\n]*)", answer)
            
            raw_decision = decision_match.group(1).strip().lower() if decision_match else "no"
            decision = (raw_decision in ["yes", "예"])
            reason = reason_match.group(1).strip() if reason_match else "판단 근거 부족"
            
            # 만약 결정 라벨이 없는데 답변이 매우 긍정적이고 'Yes'를 포함하고 있다면 구제책 마련
            if not decision_match and ("Yes" in answer or "승인" in answer or "추천" in answer) and "No" not in answer:
                decision = True
                
            return decision, reason
        return False, "API 호출 실패"

    def verify_market_vibe(self, current_data, heuristic_vibe):
        prompt = f"Data: {json.dumps(current_data)} | Heuristic: {heuristic_vibe}. One word: Bull, Bear, Neutral, Defensive."
        answer = self._call_api(prompt, timeout=30)
        if answer:
            for v in ["BULL", "BEAR", "NEUTRAL", "DEFENSIVE"]:
                if v in answer.upper(): return v.capitalize()
        return None

    def closing_sell_confirm(self, code, name, vibe, rt, detail, news):
        prompt = f"Close in 10m. {name}({code}) Profit: {rt:+.2f}%. Sell or Hold? Reason: one line."
        answer = self._call_api(prompt, timeout=30)
        if answer:
            decision_match = re.search(r"결정[^\w]*\b(Sell|Hold|매도|보유)\b", answer, re.I)
            reason_match = re.search(r"사유[^\w]*([^\n]*)", answer)
            
            raw_decision = decision_match.group(1).strip().lower() if decision_match else "sell"
            decision = (raw_decision in ["sell", "매도"])
            return decision, reason_match.group(1).strip() if reason_match else "보수적 판단"
        return True, "API 호출 실패"

    def compare_stock_superiority(self, candidate, holdings_info, vibe):
        prompt = f"Limit 8 reached. Candidate: {candidate['name']}. Better than anyone in holdings? Yes/No, SellID: XXXXXX, Reason: one line."
        answer = self._call_api(prompt, timeout=40)
        if answer:
            decision_match = re.search(r"(?:교체여부|결정)[^\w]*\b(Yes|No|예|아니오)\b", answer, re.I)
            code_match = re.search(r"(?:매도종목코드|코드)[^\w]*\b([0-9A-Z]+)\b", answer)
            reason_match = re.search(r"사유[^\w]*([^\n]*)", answer)
            
            raw_decision = decision_match.group(1).strip().lower() if decision_match else "no"
            decision = (raw_decision in ["yes", "예"])
            sell_code = code_match.group(1).strip() if code_match and code_match.group(1).upper() != "NONE" else None
            return (decision and sell_code is not None), sell_code, reason_match.group(1).strip() if reason_match else "교체 근거 부족"
        return False, None, "API 호출 실패"
