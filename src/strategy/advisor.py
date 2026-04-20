import os
import json
import re
import requests
import threading
from typing import List, Tuple, Optional, Callable
from concurrent.futures import ThreadPoolExecutor
from src.logger import log_error
from src.strategy.constants import PRESET_STRATEGIES

class GeminiAdvisor:
    def __init__(self, api, ai_config: dict = None):
        self.api = api
        self.config = ai_config or {}
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"
        
        # 기본 모델 설정 (사용자 검증 기반: 3.1 버전 우선순위 상향)
        self.preferred_model = self.config.get("preferred_model", "gemini-3.1-flash-lite-preview")
        self.fallback_sequence = self.config.get("fallback_sequence", [
            "gemini-3.1-flash-lite-preview",
            "gemini-3.1-pro-preview",
            "gemini-3.0-flash",
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite"
        ])

    def _safe_gemini_call(self, prompt: str, timeout: int = 60) -> Optional[str]:
        """Spec에 정의된 순서대로 모델을 교체하며 재시도 (Timeout 60초 적용)"""
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key: return None

        # 1순위 preferred_model부터 시작하여 fallback_sequence 순회 (중복 제거)
        models_to_try = [self.preferred_model] + [m for m in self.fallback_sequence if m != self.preferred_model]
        
        last_error = ""
        for model_id in models_to_try:
            endpoint = f"{self.base_url}/models/{model_id}:generateContent?key={api_key}"
            payload = {"contents": [{"parts": [{"text": prompt}]}]}
            try:
                # Spec 요구사항: 부하 시 충분한 대기 시간(60초) 확보
                res = requests.post(endpoint, json=payload, timeout=timeout)
                if res.status_code == 200:
                    result = res.json()
                    if 'candidates' in result and result['candidates']:
                        self.last_used_model_id = model_id
                        return result['candidates'][0]['content']['parts'][0]['text'].strip()
                last_error = f"HTTP {res.status_code}"
            except Exception as e:
                last_error = str(e)
            
            # 실패 시 로그 기록 후 다음 모델로 전환
            log_error(f"Gemini Fallback Triggered: Model {model_id} failed ({last_error}). Trying next...")
            
        return None

    def get_advice(self, market_data: dict, vibe: str, holdings: List[dict], current_config: dict, recs: List[dict] = None, indicators: dict = None) -> Optional[str]:
        # [Phase 3] 토큰 절감을 위한 데이터 요약
        holdings_txt = "\n".join([f"- {h['prdt_name']}({h['pdno']}): {h['evlu_pfls_rt']}%" for h in holdings[:5]]) # 상위 5개만
        recs_txt = ""
        if recs:
            recs_txt = "\n".join([f"- {r['name']}({r['code']}): {int(float(r.get('price',0)))}원, {r.get('rate',0):+.1f}%" for r in recs[:3]]) # 상위 3개만

        indicators_txt = ""
        if indicators:
            indicators_txt = "\n        [Quant Summary]"
            for code, ind in indicators.items():
                bb = ind.get('bb', {})
                indicators_txt += f" {code}: RSI {ind.get('rsi', 0):.0f}, %b {bb.get('percent_b', 0):.1f}"

        prompt_text = f"""
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
        return self._safe_gemini_call(prompt_text) or "⚠️ AI 엔진 분석 실패 (모든 모델 시도함)"

    def get_detailed_report_advice(self, recs: List[dict], vibe: str, progress_cb: Optional[Callable] = None) -> Optional[str]:
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
        [데이터]
        {"\n".join(enriched_recs)}
        [가이드라인 - 필수 준수]
        1. 종목당 **반드시 2줄 이내**로 핵심만 요약 (매우 중요).
        2. 1행: [투자근거/지표], 2행: [목표/손절/전략].
        3. 불필요한 수식어 제거, 날카로운 전문가 어조, 한국어.
        4. 전체 리포트 길이를 최대한 짧게 유지하여 터미널 한 화면에 들어오게 할 것.
        """
        return self._safe_gemini_call(prompt) or "종목별 입체 분석 의견을 가져오지 못했습니다."

    def get_stock_report_advice(self, code: str, name: str, detail: dict, news: List[str]) -> Optional[str]:
        rate = detail.get('rate', 0)
        prompt = f"""
        수석 투자 전략가로서 아래 종목에 대해 분석 리포트를 작성하세요.
        [종목 정보] {name}({code}) | {int(float(detail.get('price', 0))):,}원 ({rate:+.2f}%) | PER {detail.get('per')}, PBR {detail.get('pbr')}
        [뉴스 요약] {', '.join(news[:3]) if news else '소식 없음'}
        [필수 내용] 1.가격 변동 원인 2.모멘텀 진단 3.매수/매도 조언 4.한줄평
        전문가 어조, 한국어, 10~15줄.
        """
        return self._safe_gemini_call(prompt) or "종목 심층 분석 리포트를 생성하지 못했습니다."

    def get_holdings_report_advice(self, holdings: List[dict], vibe: str, market_data: dict, progress_cb: Optional[Callable] = None) -> Optional[str]:
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
        수석 포트폴리오 매니저로서 보유 종목 리포트를 작성하세요.
        [시장 장세] {vibe} | [지수] {json.dumps(market_data)}
        [보유 데이터]
        {"\n".join(enriched_holdings)}
        [필수 내용] 1.전체 포트폴리오 진단 2.종목별 대응전략(Hold/Sell/Add) 3.리스크 경고 4.한줄평
        한국어, 12~15줄, 날카롭고 전문적인 어조.
        """
        return self._safe_gemini_call(prompt) or "보유 종목 심층 분석 의견을 생성하지 못했습니다."

    def get_hot_stocks_report_advice(self, hot_stocks: List[dict], themes: List[dict], vibe: str, progress_cb: Optional[Callable] = None) -> Optional[str]:
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
        수석 트렌드 분석가로서 인기 테마 리포트를 작성하세요.
        [시장 장세] {vibe} | [테마] {", ".join([f"{t['name']}({t['count']})" for t in themes[:8]])}
        [상위 종목]
        {"\n".join(enriched)}
        [필수 내용] 1.오늘의 시장 테마 2.종목별 핵심 진단(Watch/Entry/Wait) 3.테마 지속성 판단 4.한줄 결론
        한국어, 12~15줄, 날카롭고 전문적인 어조.
        """
        return self._safe_gemini_call(prompt) or "인기 종목 분석 리포트를 생성하지 못했습니다."

    def simulate_preset_strategy(self, code: str, name: str, vibe: str, detail: dict = None, news: List[str] = None) -> Optional[dict]:
        preset_list = "\n".join([f"  {sid}: {s['name']} [기본 TP:{s['default_tp']}%, SL:{s['default_sl']}%]"
                                 for sid, s in PRESET_STRATEGIES.items() if sid != "00"])
        detail_txt = f"현재가: {detail.get('price', 'N/A')}, PER: {detail.get('per', 'N/A')}, PBR: {detail.get('pbr', 'N/A')}" if detail else ""
        prompt = f"""
        가장 적합한 프리셋 전략 1개와 동적 TP/SL을 제안하세요.
        [종목] {name}({code}) | {detail_txt} | 뉴스: {", ".join(news[:5]) if news else "없음"} | 장세: {vibe}
        [프리셋]
{preset_list}
        [형식]
        전략번호: XX
        익절: +X.X%
        손절: -X.X%
        유효시간: N분
        근거: 한줄 설명
        """
        answer = self._safe_gemini_call(prompt)
        if answer:
            try:
                sid_match = re.search(r"전략번호[:\s]*(\d{2})", answer)
                tp_match = re.search(r"익절[:\s]*([+-]?[\d.]+)", answer)
                sl_match = re.search(r"손절[:\s]*([+-]?[\d.]+)", answer)
                lt_match = re.search(r"유효시간[:\s]*(\d+)분", answer)
                reason_match = re.search(r"근거[:\s]*(.*)", answer)
                if sid_match and tp_match and sl_match:
                    sid = sid_match.group(1)
                    if sid not in PRESET_STRATEGIES or sid == "00": sid = "01"
                    
                    # 모델 Prefix 생성
                    model_prefix = "[AI]"
                    if hasattr(self, 'last_used_model_id') and self.last_used_model_id:
                        m_id = self.last_used_model_id.lower()
                        if "gemini-2.5-flash-lite" in m_id: prefix = "G2.5FL"
                        elif "gemini-2.5-flash" in m_id: prefix = "G2.5F"
                        elif "gemini-3.1-flash-lite" in m_id: prefix = "G3.1FL"
                        elif "gemini-3.1-pro" in m_id: prefix = "G3.1P"
                        elif "gemini-3-flash" in m_id: prefix = "G3.0F"
                        elif "gemini-3" in m_id: prefix = "G3.0"
                        elif "gemini-2" in m_id: prefix = "G2.X"
                        else: prefix = "GEMINI"
                        model_prefix = f"[{prefix}]"

                    reason = reason_match.group(1).strip() if reason_match else "AI 분석 기반 자동 선정"
                    return {
                        "preset_id": sid, "preset_name": PRESET_STRATEGIES[sid]["name"],
                        "tp": abs(float(tp_match.group(1))), "sl": -abs(float(sl_match.group(1))),
                        "lifetime_mins": int(lt_match.group(1)) if lt_match else 120,
                        "reason": f"{model_prefix} {reason}"
                    }
            except Exception as e: log_error(f"프리셋 시뮬레이션 파싱 오류: {e}")
        return None

    def final_buy_confirm(self, code: str, name: str, vibe: str, detail: dict, news: List[str], indicators: dict = None, score: float = 0.0) -> Tuple[bool, str]:
        """매수 직전 AI에게 최종 컨펌을 요청합니다."""
        detail_txt = (f"현재가: {detail.get('price', 'N/A')}, 등락률: {detail.get('rate', 'N/A')}%, "
                      f"시가총액: {detail.get('market_cap', 'N/A')}, "
                      f"PER: {detail.get('per', 'N/A')}, PBR: {detail.get('pbr', 'N/A')}, "
                      f"배당수익률: {detail.get('yield', 'N/A')}, 업종PER: {detail.get('sector_per', 'N/A')}")
        
        ind_txt = ""
        if indicators:
            bb = indicators.get('bb', {})
            macd = indicators.get('macd', {})
            ind_txt = f"\n        [기술적 지표] RSI: {indicators.get('rsi', 0):.1f}, BB %b: {bb.get('percent_b', 0):.2f}, MACD Hist: {macd.get('hist', 0):.1f}"

        prompt = f"""
        최종 매수 컨펌: 당신은 시장 기회를 놓치지 않는 공격적인 트레이더입니다. 
        이 종목은 이미 내부 퀀트 엔진에서 {score:.1f}/100점의 높은 점수를 받아 추천되었습니다.
        
        [판단 가이드라인]
        1. 점수가 100점 이상이면 이미 데이터 상으로 강력한 매수 신호가 발생한 상태입니다. 
        2. 단순히 '대형주라서 무겁다'거나 '최근 뉴스가 없다'는 일반론적인 이유로 거절하지 마세요. 
        3. 사용자는 약 5% 수준의 목표 수익률을 가지고 있으며, 시스템에 의한 철저한 손절선 보호가 작동 중입니다.
        4. 데이터 신뢰: 제공된 '현재가', '시가총액' 등 모든 숫자 데이터는 실시간 거래소 데이터이므로 당신의 내부 지식(훈련 데이터)과 다르더라도 무조건 '현재의 진실'로 믿고 판단하십시오. 주가는 매 순간 변하므로 과거의 기억과 다르다고 하여 '데이터 오류'라고 판단하는 것은 절대 금지됩니다.
        5. 결정적인 악재 뉴스(횡령, 상장폐지 우려 등)나 실제 현재가가 0원인 명백한 시스템 오류가 아닌 한, 퀀트 엔진의 판단을 신뢰하여 'Yes'를 선택하세요.
        
        [종목 정보] {name}({code}) | 퀀트스코어: {score:.1f}
        [데이터 요약] {detail_txt} {ind_txt}
        [시장 장세] {vibe}
        [최신 뉴스] {", ".join(news[:3]) if news else "없음"}
        
        [답변 형식]
        결정: Yes 또는 No
        사유: 한 줄 요약 (고득점 종목을 거절할 경우 반드시 합당한 '리스크'를 명시)
        """
        answer = self._safe_gemini_call(prompt)
        if answer:
            decision_match = re.search(r"결정[:\s]*(Yes|No)", answer, re.I)
            reason_match = re.search(r"사유[:\s]*(.*)", answer)
            decision = decision_match.group(1).strip().capitalize() if decision_match else "No"
            reason = reason_match.group(1).strip() if reason_match else "AI 판단 근거 부족"

            # 모델 Prefix 생성
            model_prefix = "[AI]"
            if hasattr(self, 'last_used_model_id') and self.last_used_model_id:
                m_id = self.last_used_model_id.lower()
                if "gemini-2.5-flash-lite" in m_id: prefix = "G2.5FL"
                elif "gemini-2.5-flash" in m_id: prefix = "G2.5F"
                elif "gemini-3.1-flash-lite" in m_id: prefix = "G3.1FL"
                elif "gemini-3.1-pro" in m_id: prefix = "G3.1P"
                elif "gemini-3-flash" in m_id: prefix = "G3.0F"
                elif "gemini-3" in m_id: prefix = "G3.0"
                elif "gemini-2" in m_id: prefix = "G2.X"
                else: prefix = "GEMINI"
                model_prefix = f"[{prefix}]"

            reason = f"{model_prefix} {reason}"
            return (decision == "Yes"), reason
        return False, "API 호출 실패"

    def verify_market_vibe(self, current_data: dict, heuristic_vibe: str) -> Optional[str]:
        prompt = f"""
        실시간 데이터를 바탕으로 현재 시장 Vibe를 한 단어로 답변하세요.
        [데이터] {json.dumps(current_data)} | [알고리즘 판단] {heuristic_vibe}
        [규칙] 1.글로벌 침체/공포 시 'Defensive' 2.하락세 시 'Bear' 3.상승세 시 'Bull' 4.보합 시 'Neutral'
        오직 Bull, Bear, Neutral, Defensive 중 한 단어만 출력하세요.
        """
        # 시장 Vibe 검증은 응답 속도가 중요하나, API 지연을 고려하여 타임아웃 30초 적용
        answer = self._safe_gemini_call(prompt, timeout=30)
        if answer:
            answer_up = answer.upper()
            for v in ["BULL", "BEAR", "NEUTRAL", "DEFENSIVE"]:
                if v in answer_up: return v.capitalize()
        return None

    def closing_sell_confirm(self, code: str, name: str, vibe: str, rt: float, detail: dict, news: List[str]) -> Tuple[bool, str]:
        """P4 장 마감 10분 전, 보유 종목의 익일 수익 전망을 AI가 판단하여 매도/유지 결정.
        Returns: (should_sell: bool, reason: str)
        """
        detail_txt = (f"현재가: {detail.get('price', 'N/A')}, 등락률: {detail.get('rate', 'N/A')}%, "
                      f"PER: {detail.get('per', 'N/A')}, PBR: {detail.get('pbr', 'N/A')}, "
                      f"배당수익률: {detail.get('yield', 'N/A')}, 업종PER: {detail.get('sector_per', 'N/A')}")

        prompt = f"""
        장 마감 10분 전입니다. 초단기 단타 관점에서 오늘 수익을 확정(Sell)할지, 내일 시초가 갭상승을 노리고 오버나이트(Hold)할지 결정하세요.
        
        [종목] {name}({code}) | 현재 수익률: {rt:+.2f}%
        [지표] {detail_txt}
        [시장 장세] {vibe}
        [최신 뉴스] {", ".join(news[:3]) if news else "없음"}

        [판단 기준]
        1. 내일 시초가에 바로 수익을 줄 만큼 압도적인 수급(상한가 근접, 역대급 거래량)이 있는가?
        2. 당일 중 강력한 호재 뉴스가 터져 내일 아침까지 모멘텀이 이어질 것인가?
        3. 단순 반등이나 불확실한 흐름이라면 즉시 현금화하여 리스크를 제거하십시오.

        [규칙]
        - 원칙적으로 'Sell'을 선호합니다. (오늘 수익 확정 및 리스크 제거)
        - 오직 압도적인 상승 에너지와 재료가 확인될 때만 리버스 'Hold'를 선택하세요.

        [답변 형식]
        결정: Sell 또는 Hold
        사유: 한 줄 요약
        """
        answer = self._safe_gemini_call(prompt, timeout=30)
        if answer:
            decision_match = re.search(r"결정[:\s]*(Sell|Hold)", answer, re.I)
            reason_match = re.search(r"사유[:\s]*(.*)", answer)
            decision = decision_match.group(1).strip().capitalize() if decision_match else "Sell"
            reason = reason_match.group(1).strip() if reason_match else "AI 판단 근거 부족"

            # 모델 Prefix 생성
            model_tag = self._get_model_tag()
            reason = f"{model_tag} {reason}"
            return (decision == "Sell"), reason
        return True, "API 호출 실패 (보수적 매도)"

    def compare_stock_superiority(self, candidate: dict, holdings_info: List[dict], vibe: str) -> Tuple[bool, Optional[str], str]:
        """새로운 추천 종목(candidate)과 현재 보유 종목들을 비교하여 교체 여부를 결정합니다.
        Returns: (should_replace: bool, sell_code: str, reason: str)
        """
        holdings_txt = "\n".join([
            f"- {h['name']}({h['code']}): 수익률 {h['rt']:+.2f}%, {h['detail']}"
            for h in holdings_info
        ])
        
        prompt = f"""
        [종목 교체 판단] 당신은 포트폴리오 회전율을 최적화하는 수석 퀀트 트레이더입니다.
        현재 계좌의 최대 보유 종목 수(8종목)가 가득 찼습니다. 
        새로운 유망 종목을 매수하기 위해, 기존 보유 종목 중 가장 전망이 나쁜 하나를 매도하고 교체할지 결정하십시오.

        [새로운 후보]
        - {candidate['name']}({candidate['code']}): 점수 {candidate['score']:.1f}, {candidate['detail']}
        - 뉴스: {", ".join(candidate['news'][:2]) if candidate['news'] else "없음"}

        [현재 보유 종목]
        {holdings_txt}

        [시장 장세] {vibe}

        [판단 기준]
        1. 후보 종목의 퀀트 점수와 모멘텀이 기존 종목들보다 압도적으로 우세합니까?
        2. 보유 종목 중 수익률이 극히 저조하거나, 모멘텀이 꺾인 종목이 있습니까?
        3. 만약 후보 종목이 기존의 어떤 종목보다도 매력적이지 않다면 'No'를 선택하세요.
        4. 교체할 가치가 있다면, 가장 매도하기 적합한 종목의 코드를 선택하세요.

        [답변 형식]
        교체여부: Yes 또는 No
        매도종목코드: (Yes일 경우에만 코드 입력, 아니면 None)
        사유: 한 줄 요약 (교체 시 어떤 면에서 우세한지 명시)
        """
        answer = self._safe_gemini_call(prompt, timeout=40)
        if answer:
            decision_match = re.search(r"교체여부[:\s]*(Yes|No)", answer, re.I)
            code_match = re.search(r"매도종목코드[:\s]*([0-9A-Z]+|None)", answer)
            reason_match = re.search(r"사유[:\s]*(.*)", answer)
            
            decision = decision_match.group(1).strip().capitalize() if decision_match else "No"
            sell_code = code_match.group(1).strip() if code_match and code_match.group(1) != "None" else None
            reason = reason_match.group(1).strip() if reason_match else "AI 판단 근거 부족"
            
            model_tag = self._get_model_tag()
            return (decision == "Yes" and sell_code is not None), sell_code, f"{model_tag} {reason}"
            
        return False, None, "API 호출 실패"

    def _get_model_tag(self) -> str:
        """마지막 사용된 Gemini 모델의 약어 태그를 반환합니다."""
        if hasattr(self, 'last_used_model_id') and self.last_used_model_id:
            m_id = self.last_used_model_id.lower()
            if "gemini-2.5-flash-lite" in m_id: prefix = "G2.5FL"
            elif "gemini-2.5-flash" in m_id: prefix = "G2.5F"
            elif "gemini-3.1-flash-lite" in m_id: prefix = "G3.1FL"
            elif "gemini-3.1-pro" in m_id: prefix = "G3.1P"
            elif "gemini-3-flash" in m_id: prefix = "G3.0F"
            elif "gemini-3" in m_id: prefix = "G3.0"
            elif "gemini-2" in m_id: prefix = "G2.X"
            else: prefix = "GEMINI"
            return f"[{prefix}]"
        return "[AI]"
