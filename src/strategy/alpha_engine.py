import threading
from typing import List, Optional, Callable
from concurrent.futures import ThreadPoolExecutor
from src.utils import safe_cast_float

class VibeAlphaEngine:
    """시장 데이터와 펀더멘털을 결합하여 실시간 유망 종목 및 ETF를 발굴하는 퀀트 엔진.
    
    테마 밀집도, 수급 현황, 펀더멘털 지표(PER/PBR/Yield)를 결합한 3D 입체 분석을 수행합니다.
    시장 장세(VIBE)에 따라 평가지표 가중치를 동적으로 변경하여 최적의 추천 리스트를 도출합니다.

    Attributes:
        api: KIS API 및 Naver Finance 데이터 수집용 API 인스턴스.
        ai_advisor: 뉴스 기반 감성 분석을 수행할 AI Advisor.
    """
    def __init__(self, api):
        self.api = api
        self.ai_advisor = None # Strategy에서 Gemini Advisor 주입
        self._lock = threading.Lock()

    def analyze(self, themes: List[dict], hot_raw: List[dict], vol_raw: List[dict], min_score: float = 60.0, progress_cb: Optional[Callable] = None, kr_vibe: str = "Neutral", market_data: dict = None, on_item_found: Optional[Callable] = None) -> List[dict]:
        """시장 데이터와 펀더멘털을 통합 분석하여 최적의 추천 종목 및 ETF 리스트를 생성합니다.

        이 메서드는 실시간 테마, 인기 검색어, 거래량 급증 데이터를 바탕으로 후보군을 선정하고, 
        병렬 처리를 통해 퀀트 스코어를 산정합니다. 이후 상위 종목에 대해 AI 감성 분석을 수행하여 
        최종 리스트를 확정합니다.

        Args:
            themes (List[dict]): 실시간 테마 정보 리스트 (ThemeEngine 제공).
            hot_raw (List[dict]): 실시간 인기 검색 종목 리스트.
            vol_raw (List[dict]): 실시간 거래량 폭발 종목 리스트.
            min_score (float, optional): 추천을 위한 최소 점수 기본값. 기본값 60.0.
            progress_cb (Callable, optional): 분석 진행률(현재, 전체, 메시지) 업데이트 콜백.
            kr_vibe (str, optional): 현재 시장 장세 (Bull/Bear/Defensive/Neutral). 기본값 "Neutral".
            market_data (dict, optional): 지수 및 환율 등 거시 경제 데이터. 기본값 None.
            on_item_found (Callable, optional): 추천 종목 발견 시 즉시 실행할 콜백 함수.

        Returns:
            List[dict]: 점수순으로 정렬된 최종 추천 종목 및 ETF 리스트 (최대 10개).
        """
        from src.theme_engine import get_theme_for_stock

        # [Logic Link: GEMINI.md 2.A - 지키는 투자] 장세에 따른 동적 최소 점수
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
            
            # 1차 입체 점수 산정 (장세 기반 보정 포함, 수급 데이터 제외)
            item_score = self._calculate_ai_score(item, my_theme, False, kr_vibe, market_data, detail, is_hot)

            # [신규] 수급 데이터 추가 분석 (점수가 유망한 종목에 한해 KIS API 호출)
            # 1차 점수가 dynamic_min_score - 10점 이상인 경우에만 정밀 수급 분석 수행 (API 부하 방지)
            investor_data = None
            if item_score >= (dynamic_min_score - 10.0):
                investor_data = self.api.get_investor_trading_trend(code)
                if investor_data:
                    # 수급 기반 점수 보정 (2차)
                    supply_bonus = self._calculate_supply_demand_bonus(investor_data, kr_vibe)
                    item_score += supply_bonus
                    item['investor'] = investor_data # AI Advisor 전달용

            is_etf = any(ex in item['name'].upper() for x in ["KODEX", "TIGER", "KBSTAR", "ACE", "RISE", "SOL", "HANARO"] if (ex:=x) in item['name'].upper())
            is_inverse = "인버스" in item['name']

            # 하락장/방어장에선 인버스 ETF 가점, 상승장에선 페널티
            if is_inverse:
                if kr_vibe.upper() in ["BEAR", "DEFENSIVE"]: item_score += 10.0
                else: item_score -= 50.0

            with lock:
                current += 1
                if progress_cb and (current % 5 == 0 or current == total):
                    progress_cb(current, total, f"분석 중: {item['name']}")

            # 자동 매수 가능 여부 판정 (±8.0% 제한)
            raw_rate = float(item.get('rate', 0))
            auto_eligible = -8.0 <= raw_rate <= 8.0

            if item_score >= dynamic_min_score:
                supply_msg = ""
                if investor_data:
                    f, p = investor_data.get('frgn_net_buy', 0), investor_data.get('pnsn_net_buy', 0)
                    if f > 0 and p > 0: supply_msg = " | 외인/연기금 쌍끌이"
                    elif f > 0: supply_msg = " | 외인 매수 우위"
                    elif p > 0: supply_msg = " | 연기금 매집"

                res = {**item, "score": item_score, "theme": my_theme['name'], "is_gem": False, "reason": f"{my_theme['name']} 테마 수급 및 지표 우수{supply_msg}", "auto_eligible": auto_eligible}
                if not is_etf:
                    with lock: stocks_pool.append(res)
                    if on_item_found: on_item_found(res)
                else:
                    with lock: etfs_pool.append(res)
                    if on_item_found: on_item_found(res)

        # 병렬 처리로 지표와 1차 점수 수집
        with ThreadPoolExecutor(max_workers=30) as executor:
            list(executor.map(fetch_detail_and_score, candidates))

        # 1차 필터링된 종목 중 Top N개 선별
        top_stocks = sorted(stocks_pool, key=lambda x: x['score'], reverse=True)[:10]
        top_etfs = sorted(etfs_pool, key=lambda x: x['score'], reverse=True)[:3]

        # 2차: AI 감성 분석 (뉴스 모멘텀 체크)
        if self.ai_advisor and top_stocks:
            def apply_sentiment(stock_item):
                news = self.api.get_naver_stock_news(stock_item['code'])
                if news:
                    news_txt = " ".join(news[:5])
                    # 간단한 호재/악재 키워드 매칭
                    pos = sum(1 for n in ["공급", "계약", "수주", "흑자", "상향", "독점", "MOU", "승인", "증설", "신공장", "투자", "상승", "기대", "호실적", "돌파", "편입", "추천"] if n in news_txt)
                    neg = sum(1 for n in ["적자", "하향", "취소", "위반", "횡령", "조사", "금지", "급락", "우려", "경고", "불발", "결렬", "이탈", "매도", "축소", "중단"] if n in news_txt)
                    stock_item['score'] += (pos * 2.0) - (neg * 3.0)
                    if pos > 0: stock_item['reason'] = f"뉴스 모멘텀 포착 | {stock_item['reason']}"
                    if pos > 3: stock_item['is_gem'] = True

            with ThreadPoolExecutor(max_workers=10) as executor:
                list(executor.map(apply_sentiment, top_stocks))

        # 최종 추천 리스트 확정
        final_etfs = sorted(top_etfs, key=lambda x: x['score'], reverse=True)[:2]
        needed_stocks = 10 - len(final_etfs)
        final_stocks = sorted(top_stocks, key=lambda x: x['score'], reverse=True)[:needed_stocks]

        return final_stocks + final_etfs

    def _calculate_ai_score(self, stock: dict, theme: dict, is_gem: bool, kr_vibe: str = "Neutral", market_data: dict = None, detail: dict = None, is_hot: bool = False) -> float:
        """종목별 입체 퀀트 스코어를 산출합니다.

        장세(VIBE)에 따라 모멘텀, 가치(PBR/PER), 배당률, 상대강도(RS) 가중치를 
        동적으로 조절합니다. 하락장에서는 우량 대형주 위주로, 상승장에서는 
        돌파/추세 종목 위주로 점수를 가산합니다.

        Args:
            stock (dict): 기본 시세 및 등락률 데이터.
            theme (dict): 해당 종목이 속한 테마 정보.
            is_gem (bool): 보석 종목(AI 가점 대상) 여부.
            kr_vibe (str, optional): 현재 시장 장세. 기본값 "Neutral".
            market_data (dict, optional): 지수 수익률 정보. 기본값 None.
            detail (dict, optional): 재무 및 상세 지표 (PER, PBR, 시총 등). 기본값 None.
            is_hot (bool, optional): 인기 검색 종목 포함 여부. 기본값 False.

        Returns:
            float: 최종 산정된 퀀트 점수.
        """
        score = 50.0 # 기본 베이스 점수
        raw_rate = float(stock.get('rate', 0))
        rate = abs(raw_rate)
        code = stock.get('code', '')
        
        # 1. 장세 기반 동적 가중치 설정
        v = str(kr_vibe).upper()
        mo_weight, val_weight, div_weight, rs_weight = 3.0, 1.0, 0.0, 2.0
        
        if v == "BULL":
            mo_weight, rs_weight = 4.0, 1.5      # 상승장: 달리는 말 중심
        elif v == "BEAR":
            mo_weight, val_weight, div_weight, rs_weight = 1.5, 2.5, 6.0, 4.0 # 하락장: 펀더멘털/RS 중심
        elif v == "DEFENSIVE":
            mo_weight, val_weight, div_weight, rs_weight = 1.0, 3.5, 10.0, 5.0 # 방어모드: 극단적 보수성
        
        # 2. 지수 대비 상대 강도(RS) 반영
        if market_data:
            market_type = detail.get('market_type', 'KOSPI') if detail else 'KOSPI'
            idx_key = 'KOSDAQ' if 'KOSDAQ' in market_type.upper() else 'KOSPI'
            index_rate = float(market_data.get(idx_key, {}).get('rate', 0))
            
            rs_value = raw_rate - index_rate
            if rs_value > 0: score += rs_value * rs_weight
            elif v in ["BEAR", "DEFENSIVE"] and rs_value < -1.0:
                score -= abs(rs_value) * 3.0 # 지수보다 약한 종목 페널티


        # 3. 등락률 기반 진입 필터 (소프트 페널티)
        # 정상 범위 내 모멘텀 점수 가산
        if v == "BULL" and raw_rate > 0:
            # [수정] 달리는 말 추격 시, +4.0% 까지는 비례해서 점수를 주되
            # +4.0% 를 초과하여 +8.0% 에 가까워질수록 점수를 깎아 상투 방지
            if raw_rate <= 4.0:
                score += raw_rate * mo_weight
            else:
                score += (4.0 - (raw_rate - 4.0)) * mo_weight
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
            pbr_val = safe_cast_float(detail.get('pbr'), default=1.0)
            if pbr_val <= 0.8: score += (20.0 * val_weight) # 극심한 저평가 우량주
            elif pbr_val <= 1.2: score += (12.0 * val_weight)
            elif pbr_val >= 5.0: score -= (10.0 * val_weight)
            
            # PER 보정
            per_val = safe_cast_float(detail.get('per'), default=20.0)
            if per_val <= 8.0: score += (15.0 * val_weight)
            elif per_val <= 15.0: score += (8.0 * val_weight)
            
            # 시가총액 파싱 (페널티 계산에도 공용 사용)
            mkt_cap_raw = detail.get('market_cap')
            mkt_cap = safe_cast_float(mkt_cap_raw)
            if mkt_cap >= 10000: # 시총 1조 이상 우량주
                score += 5.0 * val_weight
            
            # [복기반영 #3] Bear/Defensive 장세에서 고PER 대형주 복합 감점
            if v in ["BEAR", "DEFENSIVE"] and per_val > 25.0 and mkt_cap >= 10000:
                large_cap_penalty = min(20.0, (per_val - 25.0) * 0.8)
                score -= large_cap_penalty
            
            # 업종 상대 PER 보정
            sector_per = safe_cast_float(detail.get('sector_per'))
            if sector_per > 0 and per_val > 0 and per_val < sector_per * 0.7:
                score += (10.0 * val_weight)
            
            # 배당률(Yield) 보정 (하락장 핵심 방어 지표)
            yld_val = safe_cast_float(detail.get('yield'))
            if yld_val >= 3.0: score += div_weight
            if yld_val >= 5.0: score += div_weight * 1.5
                
        except Exception as e:
            from src.logger import logger
            logger.error(f"펀더멘털 지표 계산 중 예외 발생 ({code}): {e}")
        
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

    def _calculate_supply_demand_bonus(self, investor: dict, kr_vibe: str) -> float:
        """외인, 기관, 연기금 등의 수급 데이터를 분석하고, 과거 이력을 통한 '매집 사이클' 가점을 산출합니다."""
        bonus = 0.0
        f_net = investor.get('frgn_net_buy', 0)
        i_net = investor.get('inst_net_buy', 0)
        p_net = investor.get('pnsn_net_buy', 0)
        t_net = investor.get('thst_net_buy', 0)
        history = investor.get('history', [])
        
        v = str(kr_vibe).upper()
        
        # [A] 실시간(당일) 수급 분석
        # 1. 외인/기관 쌍끌이 매수 (강력한 상승 시그널)
        if f_net > 0 and i_net > 0:
            bonus += 12.0
            if v == "BULL": bonus += 3.0
        
        # 2. 연기금 매집 (하방 지지 및 중장기 우상향)
        if p_net > 0:
            bonus += 8.0
            if v in ["BEAR", "DEFENSIVE"]: bonus += 5.0
            
        # 3. 투신 매수 (단기 모멘텀)
        if t_net > 0:
            bonus += 5.0
            
        # 4. 수급 이탈 페널티 (외인/기관 동시 대량 매도)
        if f_net < 0 and i_net < 0:
            bonus -= 15.0

        # [B] 수급 사이클 분석 (과거 10거래일 기반) - 상승 시점 예측
        investor['cycle'] = "" # 초기화
        if history and len(history) >= 5:
            # 1. 매집(Accumulation) 연속성 체크: 최근 5일 중 순매수 일수
            frgn_buy_days = sum(1 for h in history[:5] if h['frgn_net_buy'] > 0)
            inst_buy_days = sum(1 for h in history[:5] if h['inst_net_buy'] > 0)
            
            if frgn_buy_days >= 4 or inst_buy_days >= 4:
                bonus += 10.0 # '매집 사이클' 확인
                investor['cycle'] = "매집"
                
            # 2. 수급 가속도(Acceleration) 분석: 최근 2일 평균 vs 그 전 3일 평균
            f_recent = sum(h['frgn_net_buy'] for h in history[:2]) / 2
            f_prev = sum(h['frgn_net_buy'] for h in history[2:5]) / 3
            if f_recent > f_prev and f_recent > 0:
                bonus += 5.0
                if not investor['cycle']: investor['cycle'] = "가속"
                
            i_recent = sum(h['inst_net_buy'] for h in history[:2]) / 2
            i_prev = sum(h['inst_net_buy'] for h in history[2:5]) / 3
            if i_recent > i_prev and i_recent > 0:
                bonus += 5.0
                if not investor['cycle']: investor['cycle'] = "가속"
                
            # 3. '쌍끌이 전환' 초입 (최근 5일간 매도 우위였다가 오늘 동시 매수 전환)
            was_selling = any(h['frgn_net_buy'] < 0 for h in history[1:4])
            if was_selling and f_net > 0 and i_net > 0:
                bonus += 7.0
                investor['cycle'] = "전환"
                
        return bonus
