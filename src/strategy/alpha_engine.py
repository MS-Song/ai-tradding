import threading
from typing import List, Optional, Callable
from concurrent.futures import ThreadPoolExecutor

class VibeAlphaEngine:
    def __init__(self, api):
        self.api = api
        self.ai_advisor = None # To be injected by strategy for Gemini sentiment
        self._lock = threading.Lock()

    def analyze(self, themes: List[dict], hot_raw: List[dict], vol_raw: List[dict], min_score: float = 60.0, progress_cb: Optional[Callable] = None, kr_vibe: str = "Neutral", market_data: dict = None, on_item_found: Optional[Callable] = None) -> List[dict]:
        """인기/급증 테마 및 수급 분석을 통해 실시간 추천 종목/ETF 리스트 생성 (비동기 처리)"""
        from src.theme_engine import get_theme_for_stock

        # [추가] 장세에 따른 동적 최소 점수 (지키는 투자)
        v = str(kr_vibe).upper()
        dynamic_min_score = min_score
        if v == "BEAR": dynamic_min_score = max(min_score, 70.0)      # 하락장: 더 엄격하게
        elif v == "DEFENSIVE": dynamic_min_score = max(min_score, 85.0) # 방어모드: 초우량주만

        combined = hot_raw + vol_raw
        candidates = []
        seen = set()

        # 테마 카운트 맵핑 (테마점수 산정용)
        theme_count_map = {t['name']: t['count'] for t in themes}

        for item in combined:
            code = item['code']
            if code in seen: continue
            seen.add(code)
            if not (len(code) == 6 and code.isdigit()): continue

            # 해당 종목의 테마 결정
            theme_name = get_theme_for_stock(code, item.get('name', ''))
            theme_count = theme_count_map.get(theme_name, 1)
            my_theme = {"name": theme_name, "count": theme_count}

            is_hot = any(x['code'] == code for x in hot_raw)
            candidates.append((item, my_theme, is_hot))

        # 상세 데이터 수집 및 1차 점수 산정 (병렬 처리)
        current = 0
        total = len(candidates)
        lock = threading.Lock()

        stocks_pool, etfs_pool = [], []

        def fetch_detail_and_score(cand):
            nonlocal current
            item, my_theme, is_hot = cand
            code = item['code']

            # 상세 데이터 수집 (캐시 활용)
            detail = self.api.get_naver_stock_detail(code)
            
            # 입체 점수 산정 (장세 기반 보정 포함)
            item_score = self._calculate_ai_score(item, my_theme, False, kr_vibe, market_data, detail, is_hot)

            is_etf = any(ex in item['name'].upper() for ex in ["KODEX", "TIGER", "KBSTAR", "ACE", "RISE", "SOL", "HANARO"])
            is_inverse = "인버스" in item['name']

            # 하락장/방어장에선 인버스 ETF 가점, 상승장에선 페널티
            if is_inverse:
                if kr_vibe.upper() in ["BEAR", "DEFENSIVE"]: item_score += 10.0
                else: item_score -= 50.0

            with lock:
                current += 1
                if progress_cb:
                    progress_cb(current, total, f"분석 중: {item['name']}")

            if item_score >= dynamic_min_score:
                res = {**item, "score": item_score, "theme": my_theme['name'], "is_gem": False, "reason": f"{my_theme['name']} 테마 수급 및 지표 우수"}
                if not is_etf:
                    with lock: stocks_pool.append(res)
                    if on_item_found: on_item_found(res)
                else:
                    with lock: etfs_pool.append(res)
                    if on_item_found: on_item_found(res)

        # 병렬 처리로 지표와 1차 점수 수집
        with ThreadPoolExecutor(max_workers=10) as executor:
            list(executor.map(fetch_detail_and_score, candidates))

        # 1차 필터링된 종목 중 Top N개 선별
        top_stocks = sorted(stocks_pool, key=lambda x: x['score'], reverse=True)[:10]
        top_etfs = sorted(etfs_pool, key=lambda x: x['score'], reverse=True)[:3]

        # 2차: AI 감성 분석 (Gemini Advisor 연동)
        if self.ai_advisor and top_stocks:
            total_ai = len(top_stocks)
            def apply_sentiment(stock_item):
                news = self.api.get_naver_stock_news(stock_item['code'])
                if news:
                    news_txt = " ".join(news[:5])
                    # 간단한 호재/악재 키워드 매칭 (1차 필터링)
                    pos = sum(1 for n in ["공급", "계약", "수주", "흑자", "상향", "독점", "MOU", "승인", "증설", "신공장", "투자", "상승", "기대", "호실적", "돌파", "편입", "추천"] if n in news_txt)
                    neg = sum(1 for n in ["적자", "하향", "취소", "위반", "횡령", "조사", "금지", "급락", "우려", "경고", "불발", "결렬", "이탈", "매도", "축소", "중단"] if n in news_txt)
                    stock_item['score'] += (pos * 2.0) - (neg * 3.0)
                    if pos > 0: stock_item['reason'] = f"뉴스 모멘텀 포착 | {stock_item['reason']}"
                    if pos > 3: stock_item['is_gem'] = True

            with ThreadPoolExecutor(max_workers=5) as executor:
                list(executor.map(apply_sentiment, top_stocks))

        # 최종 추천 리스트 확정 (총 10개, ETF가 부족할 경우 종목으로 채움)
        final_etfs = sorted(top_etfs, key=lambda x: x['score'], reverse=True)[:2]
        needed_stocks = 10 - len(final_etfs)
        final_stocks = sorted(top_stocks, key=lambda x: x['score'], reverse=True)[:needed_stocks]

        return final_stocks + final_etfs

    def _calculate_ai_score(self, stock: dict, theme: dict, is_gem: bool, kr_vibe: str = "Neutral", market_data: dict = None, detail: dict = None, is_hot: bool = False) -> float:
        """종목별 입체 점수 산정 (테마 + 등락률 + 실시간 수급 모멘텀 + 펀더멘털 + 장세 기반 보정)"""
        score = 50.0 # 기본 베이스 점수 (핫 가점 축소에 따른 전체 점수 하락 보정)
        raw_rate = float(stock.get('rate', 0))
        rate = abs(raw_rate)
        
        # 1. 장세 기반 동적 가중치 설정
        v = str(kr_vibe).upper()
        mo_weight = 3.0   # 모멘텀 가중치 (기본)
        val_weight = 1.0  # 가치형 가중치 (기본)
        div_weight = 0.0  # 배당 가중치 (기본)
        
        if v == "BULL":
            mo_weight = 4.0      # 상승장엔 달리는 말 우선
        elif v == "BEAR":
            mo_weight = 1.5      # 하락장에선 모멘텀 신뢰도 하락
            val_weight = 2.0     # 펀더멘털 중요성 상승
            div_weight = 5.0     # 배당(방어) 메리트 추가
        elif v == "DEFENSIVE":
            mo_weight = 1.0
            val_weight = 2.5
            div_weight = 8.0
        
        # 2. 등락률/테마 점수 (모멘텀)
        if v == "BULL" and raw_rate > 0:
            # 상승장에서는 오르는 종목(최대 +8%)에 모멘텀 가점 부여 (추격 매수 일부 허용)
            score += min(8.0, raw_rate) * mo_weight
        else:
            # 하락/보합장에서는 0%에 가까울수록 선취매 매력도 상승
            score += (5.0 - min(5.0, rate)) * mo_weight
        
        # 테마 내 밀집도 반영
        score += min(15, theme['count'] * (mo_weight / 2.0))
        
        # 검색 상위 (핫 리스트) 종목 특별 가점 대폭 축소 (저평가 가치주 위주 편향 방지 및 모멘텀 편입, 기존 15.0 -> 5.0)
        if is_hot:
            score += 5.0 * mo_weight
        
        # 3. 펀더멘털 지표 보정 및 상대 가치 평가 (업종 PER 비교)
        if not detail:
            detail = self.api.get_naver_stock_detail(stock['code'])
            
        try:
            # PBR 보정
            pbr_val = float(detail.get('pbr', '0').replace(',', '')) if detail.get('pbr') != 'N/A' else 1.0
            if pbr_val <= 1.0: score += (15.0 * val_weight)
            elif pbr_val <= 3.0: score += (8.0 * val_weight)
            elif pbr_val >= 10.0: score -= (15.0 * val_weight)
            
            # PER 보정
            per_val = float(detail.get('per', '0').replace(',', '')) if detail.get('per') != 'N/A' else 20.0
            if per_val <= 10.0: score += (10.0 * val_weight)
            elif per_val <= 20.0: score += (5.0 * val_weight)
            elif per_val >= 50.0: score -= (10.0 * val_weight)
            
            # 업종 상대 PER 보정 (종목 PER가 업종 평균보다 낮을 경우 가산점)
            sector_per_str = str(detail.get('sector_per', '0')).replace(',', '').replace('%', '')
            sector_per = float(sector_per_str) if sector_per_str != 'N/A' else 0.0
            if sector_per > 0 and per_val > 0 and per_val < sector_per:
                score += (8.0 * val_weight) # 업종 대비 저평가 보너스
            
            # 배당률(Yield) 보정 (하락장 방어주 발굴)
            yld_val = float(str(detail.get('yield', '0')).replace(',', '').replace('%', '')) if detail.get('yield') != 'N/A' else 0.0
            if yld_val >= 4.0: score += div_weight
            if yld_val >= 7.0: score += div_weight * 1.5
                
        except: pass
        
        # 4. 인버스 ETF 가점 부여 (방어/하락장 전용)
        is_inverse = "인버스" in stock.get('name', ' ')
        if is_inverse:
            if v in ["BEAR", "DEFENSIVE"]: score += 20.0
            else: score -= 50.0 # 평소에는 인버스 추천 배제
        
        # 5. 거시 지표 기반 기본 컷오프 패널티 (지수 폭락 시 전체 점수 삭감)
        if market_data:
            usd_krw = market_data.get("FX_USDKRW")
            if usd_krw and usd_krw.get('rate', 0) >= 1.0: score -= 3.0 # 환율 급등 시 패널티
            
        if is_gem: score += 10.0
        
        return round(score, 1)
