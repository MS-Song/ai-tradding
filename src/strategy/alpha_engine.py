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

        # [최적화] 모든 후보 종목의 실시간 데이터를 벌크로 미리 가져와 캐시 채우기
        all_candidate_codes = [c[0]['code'] for c in candidates]
        self.api.get_naver_stocks_realtime(all_candidate_codes)
        
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
                if progress_cb and (current % 5 == 0 or current == total):
                    progress_cb(current, total, f"분석 중: {item['name']}")

            if item_score >= dynamic_min_score:
                res = {**item, "score": item_score, "theme": my_theme['name'], "is_gem": False, "reason": f"{my_theme['name']} 테마 수급 및 지표 우수"}
                if not is_etf:
                    with lock: stocks_pool.append(res)
                    if on_item_found: on_item_found(res)
                else:
                    with lock: etfs_pool.append(res)
                    if on_item_found: on_item_found(res)

        # 병렬 처리로 지표와 1차 점수 수집 (워커 수 대폭 증가: 20 -> 30)
        with ThreadPoolExecutor(max_workers=30) as executor:
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

            with ThreadPoolExecutor(max_workers=10) as executor:
                list(executor.map(apply_sentiment, top_stocks))

        # 최종 추천 리스트 확정 (총 10개, ETF가 부족할 경우 종목으로 채움)
        final_etfs = sorted(top_etfs, key=lambda x: x['score'], reverse=True)[:2]
        needed_stocks = 10 - len(final_etfs)
        final_stocks = sorted(top_stocks, key=lambda x: x['score'], reverse=True)[:needed_stocks]

        return final_stocks + final_etfs

    def _calculate_ai_score(self, stock: dict, theme: dict, is_gem: bool, kr_vibe: str = "Neutral", market_data: dict = None, detail: dict = None, is_hot: bool = False) -> float:
        """종목별 입체 점수 산정 (테마 + 등락률 + 상대 강도(RS) + 실시간 수급 + 펀더멘털 + 장세 기반 보정)"""
        score = 50.0 # 기본 베이스 점수
        raw_rate = float(stock.get('rate', 0))
        rate = abs(raw_rate)
        code = stock.get('code', '')
        
        # 1. 장세 기반 동적 가중치 설정
        v = str(kr_vibe).upper()
        mo_weight = 3.0   # 모멘텀 가중치 (기본)
        val_weight = 1.0  # 가치형 가중치 (기본)
        div_weight = 0.0  # 배당 가중치 (기본)
        rs_weight = 2.0   # 상대 강도 가중치 (기본)
        
        if v == "BULL":
            mo_weight = 4.0      # 상승장엔 달리는 말 우선
            rs_weight = 1.5
        elif v == "BEAR":
            mo_weight = 1.5      # 하락장에선 모멘텀 신뢰도 하락
            val_weight = 2.5     # 펀더멘털 중요성 대폭 상승
            div_weight = 6.0     # 배당(방어) 메리트 추가
            rs_weight = 4.0      # 하락장일수록 지수보다 강한 종목(RS)이 진짜 우량주
        elif v == "DEFENSIVE":
            mo_weight = 1.0
            val_weight = 3.5
            div_weight = 10.0
            rs_weight = 5.0      # 방어모드에선 RS가 최우선 지표
        
        # 2. 지수 대비 상대 강도(RS) 계산 및 반영
        if market_data:
            # 종목 코드나 시장 구분(KSP/KDQ) 정보를 통해 적절한 지수 선택
            # (여기서는 단순화하여 KOSPI/KOSDAQ 평균 또는 상세 데이터의 시장 구분 활용)
            market_type = detail.get('market_type', 'KOSPI') if detail else 'KOSPI'
            index_rate = 0.0
            if 'KOSDAQ' in market_type.upper():
                index_rate = float(market_data.get('KOSDAQ', {}).get('rate', 0))
            else:
                index_rate = float(market_data.get('KOSPI', {}).get('rate', 0))
            
            rs_value = raw_rate - index_rate # 지수보다 얼마나 더 강한가?
            if rs_value > 0:
                score += rs_value * rs_weight
            elif v in ["BEAR", "DEFENSIVE"] and rs_value < -1.0:
                # 하락장에서 지수보다 더 많이 빠지는 종목은 강하게 페널티
                score -= abs(rs_value) * 3.0

        # 3. 등락률 기반 진입 필터 (GEMINI.md 준수: -8.0% ~ +8.0%)
        # [CRITICAL] 범위를 벗어난 종목은 점수를 대폭 삭감하여 추천 대상에서 원천 배제
        if raw_rate > 8.0:
            return -100.0  # 과열 종목 진입 원천 차단
        elif raw_rate < -8.0:
            return -100.0  # 과매도/급락 종목 진입 차단
        
        # 정상 범위 내 모멘텀 점수 가산
        if v == "BULL" and raw_rate > 0:
            score += min(8.0, raw_rate) * mo_weight
        else:
            score += (5.0 - min(5.0, rate)) * mo_weight
        
        # 테마 내 밀집도 반영
        score += min(15, theme['count'] * (mo_weight / 2.0))
        
        if is_hot:
            score += 5.0 * mo_weight
        
        # 4. 펀더멘털 지표 보정 (우량주 발굴 핵심)
        if not detail:
            detail = self.api.get_naver_stock_detail(code)
            
        try:
            # PBR 보정 (저PBR 우량주 가중치)
            pbr_val = float(detail.get('pbr', '0').replace(',', '')) if detail.get('pbr') != 'N/A' else 1.0
            if pbr_val <= 0.8: score += (20.0 * val_weight) # 극심한 저평가 우량주
            elif pbr_val <= 1.2: score += (12.0 * val_weight)
            elif pbr_val >= 5.0: score -= (10.0 * val_weight)
            
            # PER 보정
            per_val = float(detail.get('per', '0').replace(',', '')) if detail.get('per') != 'N/A' else 20.0
            if per_val <= 8.0: score += (15.0 * val_weight)
            elif per_val <= 15.0: score += (8.0 * val_weight)
            
            # 시가총액 파싱 (페널티 계산에도 공용 사용)
            mkt_cap = float(str(detail.get('market_cap', '0')).replace(',', '').replace('억', '')) if detail.get('market_cap') else 0
            if mkt_cap >= 10000: # 시총 1조 이상 우량주
                score += 5.0 * val_weight
            
            # [복기반영 #3] Bear/Defensive 장세에서 고PER 대형주 복합 감점
            # 하락장에서는 지수 영향이 큰 고PER 대형주보다 지수 영향이 적은 개별 모멘텀 종목이 유리
            if v in ["BEAR", "DEFENSIVE"] and per_val > 25.0 and mkt_cap >= 10000:
                large_cap_penalty = min(20.0, (per_val - 25.0) * 0.8)
                score -= large_cap_penalty
                logger.debug(f"하락장 고PER대형주 페널티: PER={per_val:.1f} 시총={mkt_cap:.0f}억 → -{large_cap_penalty:.1f}pt")
            
            # 업종 상대 PER 보정
            sector_per_str = str(detail.get('sector_per', '0')).replace(',', '').replace('%', '')
            sector_per = float(sector_per_str) if sector_per_str != 'N/A' else 0.0
            if sector_per > 0 and per_val > 0 and per_val < sector_per * 0.7:
                score += (10.0 * val_weight)
            
            # 배당률(Yield) 보정 (하락장 핵심 방어 지표)
            yld_val = float(str(detail.get('yield', '0')).replace(',', '').replace('%', '')) if detail.get('yield') != 'N/A' else 0.0
            if yld_val >= 3.0: score += div_weight
            if yld_val >= 5.0: score += div_weight * 1.5
                
        except: pass
        
        # 5. 인버스 ETF 가점 (하락장 헷지)
        is_inverse = "인버스" in stock.get('name', ' ')
        if is_inverse:
            if v in ["BEAR", "DEFENSIVE"]: score += 25.0
            else: score -= 60.0
        
        # 6. 거시 지표 패널티 (환율 급등 등 리스크 반영)
        if market_data:
            usd_krw = market_data.get("FX_USDKRW")
            if usd_krw and usd_krw.get('price', 0) >= 1380: score -= 5.0 # 환율 리스크 반영
            
        if is_gem: score += 10.0
        
        return round(score, 1)
