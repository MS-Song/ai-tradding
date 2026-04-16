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
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"
        
        # 기본 모델 설정 (사용자 검증 기반: Group 1 수정 반영)
        self.config = ai_config or {}
        self.preferred_model = self.config.get("preferred_model", "gemini-2.5-flash")
        self.fallback_sequence = self.config.get("fallback_sequence", [
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
            "gemini-3-flash-preview",
            "gemini-3.1-flash-lite-preview",
            "gemini-3.1-pro-preview"
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

    def get_advice(self, market_data: dict, vibe: str, holdings: List[dict], current_config: dict, recs: List[dict] = None) -> Optional[str]:
        holdings_txt = "\n".join([f"- {h['prdt_name']}({h['pdno']}): 수익률 {h['evlu_pfls_rt']}%" for h in holdings])
        recs_txt = ""
        if recs:
            recs_txt = "\n".join([f"- {r['name']}({r['code']}): 1주당 현재가 {int(float(r.get('price',0))):,}원, 금일 등락 {r.get('rate',0):+.1f}%" for r in recs[:5]])

        prompt_text = f"""
        당신은 월스트리트 수석 퀀트 트레이더입니다. 아래의 **[실시간 데이터]**만을 근거로 전략을 브리핑하세요.
        [실시간 데이터]
        - 시장Vibe: {vibe}
        - 현재 지수 상태: {json.dumps(market_data)}
        - 현재 포트폴리오: {holdings_txt if holdings else "보유 종목 없음"}
        - 신규 추천 후보: {recs_txt if recs_txt else "추천 후보 없음"}
        - 시스템 매수 설정 금액: {current_config.get('ai_amt'):,}원
        [필수 규칙]
        1. 추천주의 매수가격은 '1주당 현재가'의 ±3% 이내에서만 제안.
        2. (매수 권장 금액)이 (추천주 1주당 현재가)보다 작으면 추천 불가.
        3. 추가매수(물타기) 지점 > 손절선(SL), 불타기지점 < 익절선(TP).
        4. AI[액션]과 AI[추천]은 각각 단 1줄로 요약.
        [답변 형식]
        AI[시장]: 요약
        AI[전략]: 익절 +X.X%, 손절 -Y.Y%, 물타기 -Z.Z%, 불타기 +W.W%, 금액 N원
        AI[액션]: 요약 (1줄)
        AI[추천]: 종목명(코드), 권장매수가 N원, 예상매수주수 M주 (1줄)
        한국어로 대답하세요.
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
        prompt = f"""
        수석 투자 전략가로서 아래 종목에 대해 분석 리포트를 작성하세요.
        [종목 정보] {name}({code}) | {int(float(detail.get('price', 0))):,}원 | PER {detail.get('per')}, PBR {detail.get('pbr')}
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
                    return {
                        "preset_id": sid, "preset_name": PRESET_STRATEGIES[sid]["name"],
                        "tp": abs(float(tp_match.group(1))), "sl": -abs(float(sl_match.group(1))),
                        "lifetime_mins": int(lt_match.group(1)) if lt_match else 120,
                        "reason": reason_match.group(1).strip() if reason_match else "AI 분석 기반 자동 선정"
                    }
            except Exception as e: log_error(f"프리셋 시뮬레이션 파싱 오류: {e}")
        return None

    def final_buy_confirm(self, code: str, name: str, vibe: str, detail: dict, news: List[str]) -> Tuple[bool, str]:
        """매수 직전 AI에게 최종 컨펌을 요청합니다."""
        detail_txt = (f"현재가: {detail.get('price', 'N/A')}, 등락률: {detail.get('rate', 'N/A')}%, "
                      f"시가총액: {detail.get('market_cap', 'N/A')}, "
                      f"PER: {detail.get('per', 'N/A')}, PBR: {detail.get('pbr', 'N/A')}, "
                      f"배당수익률: {detail.get('yield', 'N/A')}, 업종PER: {detail.get('sector_per', 'N/A')}")
        
        prompt = f"""
        최종 매수 결정: 아래 종목을 지금 바로 매수해야 할까요?
        ⚠️주의⚠️: 제공된 '현재가'는 과거 학습 데이터가 아닌 방금 조회한 가장 최신 실시간 시장 가격입니다. 
        모델이 알고 있는 과거 데이터와 괴리가 있더라도 절대 데이터 오류나 가치평가 불가로 판단하지 말고, 주어진 실시간 가격을 신뢰하여 매수 여부를 결정하세요.

        [종목] {name}({code}) | {detail_txt}
        [시장 장세] {vibe}
        [최신 뉴스] {", ".join(news[:3]) if news else "없음"}
        
        [답변 형식]
        결정: Yes 또는 No
        사유: 한 줄 요약 (No인 경우 필수)
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
        # 시장 Vibe 검증은 응답 속도가 중요하므로 짧은 타임아웃(10초) 적용하여 Fallback 전환 가속화
        answer = self._safe_gemini_call(prompt, timeout=10)
        if answer:
            answer_up = answer.upper()
            for v in ["BULL", "BEAR", "NEUTRAL", "DEFENSIVE"]:
                if v in answer_up: return v.capitalize()
        return None
