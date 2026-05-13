import os
import time
import concurrent.futures
from typing import List, Dict
from src.workers.base import BaseWorker
from src.logger import trading_log, log_error, logger
from src.utils import safe_cast_float, get_now


class DataSyncWorker(BaseWorker):
    """시스템의 데이터 무결성을 유지하기 위해 계좌와 시장 데이터를 동기화하는 워커.
    
    KIS API를 통한 실시간 잔고/자산 정보 패치, Naver API를 활용한 벌크 시세 업데이트, 
    일일 손익 및 수익률 재계산, 기술적 지표(MA20) 캐싱 등 핵심 데이터 수급을 담당합니다.

    Attributes:
        api: 자산 및 시세 조회를 위한 API 클라이언트.
        strategy: 수익률 계산 및 임계치 결정을 위한 VibeStrategy 인스턴스.
        force_sync (bool): 즉시 동기화 요청 플래그.
    """
    def __init__(self, state, api, strategy):
        """DataSyncWorker를 초기화합니다.

        Args:
            state (DataManager): 시스템 전역 상태 인스턴스.
            api: 자산 및 시세 조회를 위한 API 클라이언트.
            strategy (VibeStrategy): 수익률 계산 및 지표 분석을 위한 전략 엔진.
        """
        super().__init__("DATA", state, interval=1.0)
        self.api = api
        self.strategy = strategy
        self.last_heavy_sync = 0
        self.first_run = True
        self.last_balance_sync = 0
        self.force_sync = False # 즉시 동기화 요청 플래그

    def run(self):
        """데이터 동기화 루틴을 주기적으로 실행합니다.
        
        1. KIS API를 통해 계좌 잔고 및 총 자산을 동기화합니다 (5초 주기 또는 강제 요청).
        2. Naver 벌크 API로 보유 종목 및 추천/인기 종목의 실시간 시세를 갱신합니다 (1초 주기).
        3. 실시간 가격을 바탕으로 계좌 평가액과 일일 손익을 즉시 재계산하여 반영합니다.
        """
        curr_t = time.time()
        
        # 1. 잔고 및 자산 정보 패치 (KIS API 호출) - 5초 주기로 제한 (단, force_sync 시 즉시 실행)
        should_fetch_balance = curr_t - getattr(self, "last_balance_sync", 0) > 5.0 or self.first_run or self.force_sync
        
        try:
            if should_fetch_balance:
                self.state.update_worker_status("ASSET", status="잔고 동기화")
                h, a = self.api.get_full_balance()
                self.last_balance_sync = curr_t
                self.force_sync = False # 플래그 초기화
                
                if h or a.get('total_asset', 0) > 0:
                    # [개선] KIS API의 자산 총계가 가끔 캐시+주식 합계와 맞지 않는 경우가 있어 직접 재계산하여 정정함
                    # 특히 모의투자 환경에서 tot_evlu_amt가 구버전 데이터를 반환하는 경우가 많음
                    actual_stock_eval = sum(float(item.get('evlu_amt', 0)) for item in h)
                    a['stock_eval'] = actual_stock_eval
                    a['total_asset'] = a.get('cash', 0) + actual_stock_eval
                    
                    self._update_asset_metrics(a)
                    with self.state.lock:
                        self.state.holdings = h
                        self.state.asset = a
                        self.state.holdings_fetched = True
                        if a.get('total_asset', 0) > 0:
                            self.strategy.last_known_asset = float(a['total_asset'])
                    
                    self.state.update_worker_status("ASSET", status="대기중", result="성공", last_task="계좌 및 평가액 동기화 완료")
            
            # 2. 관련 종목 시세 동기화 (네이버 벌크 API 활용 - 이건 Rate Limit 없음)
            # 잔고 데이터가 없는 초기 상태가 아니라면 항상 실행
            current_holdings = self.state.holdings
            if current_holdings or self.first_run:
                self._sync_stock_prices(current_holdings, curr_t)
                self.set_result("성공", last_task="전체 잔고 및 시세 동기화 완료")
                self.first_run = False
                
        except Exception as e:
            if "초당 거래건수를 초과" in str(e):
                self.state.update_worker_status("ASSET", status="대기중", result="대기", last_task="API 속도 제한으로 대기 중")
            else:
                log_error(f"DataSyncWorker Run Error: {e}")
            self.set_result("실패", last_task=f"동기화 오류: {e}")

    def _update_asset_metrics(self, a: dict):
        """총 자산 및 일일 손익 지표를 재계산하여 업데이트합니다.
        
        입출금 내역과 관계없이 순수한 투자 성과를 측정하기 위해 
        [실현손익 + 미실현손익 변동분] 공식을 사용하여 일일 수익금을 산출합니다.
        프로그램 시작 시 당일 기준 자산과 기초 미실현 손익을 고정하여 상대적 성과를 추적합니다.

        Args:
            a (dict): KIS API로부터 수집된 자산 정보 딕셔너리.
        """
        if not a or a.get('total_asset', 0) <= 0: return
        today_str = get_now().strftime('%Y-%m-%d')
        
        # [핵심] 일일 수익률 기준점(start_day_asset) 강제 동기화
        # 파일에서 로드된 과거의 잘못된 기준점(stale data)을 방지하기 위해 프로그램 시작 후 첫 실행 시 강제 재설정
        is_first_init = (
            self.strategy.start_day_asset <= 0 or 
            self.strategy.last_asset_date != today_str or
            self.strategy.start_day_pnl == -999999999.0
        )
        
        if is_first_init:
            p_asset = a.get('prev_day_asset', 0)
            if p_asset > 0:
                # KIS 전일 평가액이 있으면 기준점으로 사용 (API 신뢰)
                self.strategy.start_day_asset = p_asset
            else:
                # 전일 데이터가 없거나 0이면 현재 자산을 시작점으로 설정 (오늘 수익 0%부터 시작)
                self.strategy.start_day_asset = a['total_asset']
            
            # [수정] 일일 수익률 계산을 위한 초기 미실현 손익 저장
            self.strategy.start_day_pnl = a.get('pnl', 0)
            self.strategy.last_asset_date = today_str
            self.first_run = False # 초기화 완료
            with self.state.lock:
                self.state.last_log_msg = f"\033[96m[LOG] 📅 당일 수익률 기준점 초기화: {self.strategy.start_day_asset:,.0f}원 (초기 미실현: {self.strategy.start_day_pnl:,.0f}원)\033[0m"
                self.state.last_log_time = time.time()

        # [개선] KIS 모의투자에서만 사용자 입력 시드머니를 원금으로 사용
        # 실전거래(KIS/키움)에서는 API가 정확한 원금(매입원금+예수금)을 반환하므로 자동 계산
        seed = getattr(self.strategy, "base_seed_money", 0)
        is_virtual = getattr(self.api.auth, 'is_virtual', True)
        is_kis = 'kis' in self.api.auth.__class__.__name__.lower()
        if seed > 0 and is_kis and is_virtual:
            a['total_principal'] = seed
        
        if self.strategy.start_day_asset > 0:
            # [개선] 입출금에 영향받지 않는 정확한 일일 수익 계산 로직 적용 (요구사항 반영)
            # 공식: 일일 수익 = 당일 실현손익(순수익) + (현재 미실현손익 - 기초 미실현손익)
            from src.logger import trading_log
            realized_p = trading_log.get_daily_profit()
            fees = trading_log.get_daily_trading_fees()
            curr_unrealized = a.get('pnl', 0)
            init_unrealized = self.strategy.start_day_pnl
            
            # 순 실현 수익 = 실현 - 수수료
            net_realized = realized_p - fees
            # 미실현 수익 변동분
            unrealized_delta = curr_unrealized - init_unrealized
            
            a['daily_pnl_amt'] = net_realized + unrealized_delta
            a['daily_pnl_rate'] = (a['daily_pnl_amt'] / self.strategy.start_day_asset * 100)

    def _sync_stock_prices(self, holdings: List[Dict], curr_t: float):
        """보유 종목, 당일 매매 종목 및 주요 관심 종목의 실시간 시세를 병렬로 동기화합니다.

        Args:
            holdings (List[dict]): 현재 잔고 리스트.
            curr_t (float): 현재 시각 (timestamp).

        Logic:
            1. Naver 벌크 API를 사용하여 전 종목 시세를 1회 호출로 수집.
            2. ThreadPoolExecutor를 통해 종목별 기술적 지표(MA20) 및 동적 임계치(TP/SL) 병렬 계산.
            3. 분석 완료된 데이터를 전역 상태(`stock_info`, `ma_20_cache`)에 업데이트.
        """
        today_str = get_now().strftime('%Y-%m-%d')
        all_codes = set([s.get('pdno', '').strip() for s in holdings if s.get('pdno')])
        
        with trading_log.lock:
            for t in trading_log.data.get("trades", []):
                if t.get("time", "").startswith(today_str):
                    all_codes.add(t["code"].strip())
        
        # [추가] AI 추천 종목도 동기화 대상에 포함 (매수 시 병목 방지 및 지표 수급용)
        recs = getattr(self.strategy, "ai_recommendations", [])
        for r in recs[:10]: # 상위 10개 종목 우선 수급
            if r.get('code'):
                all_codes.add(r['code'].strip())
        
        # [추가] 대시보드에 표시되는 인기/거래량 상위 종목도 실시간 가격 갱신 대상에 포함
        for item_list in [self.state.hot_raw, self.state.vol_raw]:
            for item in (item_list or [])[:20]:
                if item.get('code'):
                    all_codes.add(item['code'].strip())
        
        all_codes = list(all_codes)
        if not all_codes: return

        bulk_data = self.api.get_naver_stocks_realtime(all_codes)
        is_heavy_cycle = (curr_t - self.last_heavy_sync > 60)
        if is_heavy_cycle:
            self.last_heavy_sync = curr_t
        if is_heavy_cycle:
            self.last_heavy_sync = curr_t
        
        temp_info = {}
        
        def fetch_stock_task(code):
            task_id = f"STOCK_{code}"
            n_data = bulk_data.get(code)
            # 보유 종목 여부 확인 (미보유 종목은 실시간 시세만 갱신하고 무거운 분석은 제외)
            is_holding = any(s.get('pdno') == code for s in holdings)
            
            # [수정] 캐시된 이름이 있으면 즉시 표시하여 'STOCK_' 코드 노출 최소화
            cached_name = self.state.stock_info.get(code, {}).get('name')
            f_name = f"{code}_{cached_name}" if cached_name else task_id
            
            # 보유 종목일 때만 UI 워커 목록에 표시
            if is_holding:
                self.state.update_worker_status(task_id, status="분석 중", friendly_name=f_name)
            
            # 종목명 찾기 (우선순위: 잔고명 -> Naver 실시간명 -> KIS 상세명 -> 기존 캐시명)
            s_name = next((s.get('prdt_name') for s in holdings if s.get('pdno')==code), None)
            
            p_data = None
            investor_data = None
            # [최적화] 보유 종목일 때만 KIS 상세 시세(Hoga 등) 및 수급 데이터 조회
            if is_holding and (is_heavy_cycle or code not in self.state.stock_info):
                # [제거] BrokerRateLimiter가 대기를 관리하므로 수동 sleep 불필요
                p_data = self.api.get_inquire_price(code)
                
                # [신규] 수급 데이터(외인/기관/연기금) 동기화
                investor_data = self.api.get_investor_trading_trend(code)
            
            if n_data:
                curr_p, day_rate, day_val = n_data['price'], n_data['rate'], n_data['cv']
                if not s_name: s_name = n_data.get('name')
                
                old_info = self.state.stock_info.get(code, {})
                p_data_fallback = {
                    "price": curr_p, "vrss": day_val, "ctrt": day_rate,
                    "vol": n_data.get('aq', 0), "high": n_data.get('hv', curr_p), "low": n_data.get('lv', curr_p),
                    "prev_vol": p_data.get("prev_vol", 0) if p_data else old_info.get("prev_vol", 0)
                }
                tp, sl, spike = self.strategy.get_dynamic_thresholds(code, self.state.vibe.lower(), p_data_fallback)
                p_vol = p_data_fallback["prev_vol"]
            else:
                if not p_data: p_data = self.api.get_inquire_price(code)
                tp, sl, spike = self.strategy.get_dynamic_thresholds(code, self.state.vibe.lower(), p_data)
                curr_p = p_data.get('price', 0) if p_data else 0
                day_val = p_data.get('vrss', 0) if p_data else 0
                day_rate = p_data.get('ctrt', 0) if p_data else 0
                p_vol = p_data.get('prev_vol', 0) if p_data else 0
            
            if not s_name: 
                s_name = self.state.stock_info.get(code, {}).get('name')
                if not s_name or s_name == "Unknown":
                    # 마지막 수단: KIS 데이터나 캐시된 정보 활용
                    if p_data: s_name = p_data.get('name', code)
                    else: s_name = code

            # [수정] 분석 완료된 명칭으로 최종 업데이트 (보유 종목만)
            if is_holding:
                f_name = f"{code}_{s_name}" if s_name else task_id
                self.state.update_worker_status(task_id, friendly_name=f_name)

            # MA20 계산 (보유 종목에 대해서만 수행하여 리소스 절약)
            # 매도된 종목은 매매 시점에 이미 기록된 MA20 값을 사용하므로 실시간 동기화 제외
            ma_20 = self.state.ma_20_cache.get(code, 0.0)
            ma_source = "캐시"  # 기본값: 이미 캐시에 있는 경우
            if is_holding and (ma_20 == 0 or is_heavy_cycle):
                try:
                    # [최적화] 모의투자는 KIS API를 아끼기 위해 Naver를 우선 시도
                    is_v = getattr(self.api.auth, 'is_virtual', True)
                    m_candles = None
                    if is_v:
                        m_candles = self.api.get_naver_minute_chart(code)
                        _used_fallback = bool(m_candles)
                    
                    if not m_candles:
                        # [제거] BrokerRateLimiter가 대기를 관리하므로 수동 sleep 불필요
                        m_candles = self.api.get_minute_chart_price(code)
                        _used_fallback = False

                    if m_candles:
                        closes = [safe_cast_float(c.get('stck_prpr') or c.get('stck_clpr')) for c in m_candles if (c.get('stck_prpr') or c.get('stck_clpr'))]
                        if len(closes) >= 20:
                            ma_vals = self.strategy.indicator_eng.calculate_sma(closes, [20])
                            ma_20 = ma_vals.get("sma_20", 0.0)
                            ma_source = "Naver" if _used_fallback else "KIS"
                        else:
                            ma_source = "데이터부족"
                            # 데이터 부족은 에러가 아닌 정보성 로그로 처리
                            if is_heavy_cycle: logger.debug(f"MA20 데이터 부족 ({code}): {len(closes)}개")
                    else:
                        ma_source = "취득실패"
                        # 빈 데이터는 에러가 아닌 정보성 로그로 처리하여 error.log 비대화 방지
                        if is_heavy_cycle: logger.debug(f"MA20 차트 데이터 수신 실패 (Empty) ({code})")
                except Exception as e:
                    ma_source = "오류"
                    logger.debug(f"MA20 Calculation Exception ({code}): {e}")
                    pass

            return code, {
                "tp": tp if is_holding else 0, "sl": sl if is_holding else 0, "spike": spike if is_holding else False,
                "day_val": day_val, "day_rate": day_rate,
                "ma_20": ma_20, "price": curr_p, "prev_vol": p_vol, "name": s_name, "ma_source": ma_source,
                "investor": investor_data if is_holding else old_info.get("investor")
            }, task_id, ma_20, is_holding, ma_source

        # [최적화] 실거래에서는 큐의 동시성을 늘려 병렬 처리 가속
        is_v = getattr(self.api.auth, 'is_virtual', True)
        if is_v:
            m_workers = 1 
        else:
            # 실거래 시 증권사별 RPS 수준에 맞춰 워커 수 조정
            broker_type = os.getenv("BROKER_TYPE", "KIS").upper()
            m_workers = 15 if broker_type == "KIS" else 8
            
        with concurrent.futures.ThreadPoolExecutor(max_workers=m_workers) as executor:
            futures = [executor.submit(fetch_stock_task, c) for c in all_codes]
            for f in concurrent.futures.as_completed(futures):
                try:
                    c, info, tid, ma, is_h, ma_src = f.result()
                    temp_info[c] = info
                    with self.state.lock:
                        if ma > 0: self.state.ma_20_cache[c] = ma

                    if is_h:
                        # [개선] MA20 소스를 마지막 행동 텍스트에 () 안에 표기
                        ma_src_tag = f" (MA:{ma_src})" if ma_src not in ("캐시", "") else ""
                        self.state.update_worker_status(
                            tid, status="대기 중 (IDLE)", result="성공",
                            last_task=f"{info['name']} 동기화 완료{ma_src_tag}",
                            friendly_name=f"{c}_{info['name']}"
                        )
                except Exception as e:
                    logger.warning(f"종목 시세 동기화 실패: {e}")

        # 3.5 [신규] 보유 종목이 아닌 STOCK_ 워커 정리 (상태 제거)
        if self.state.holdings_fetched: # 잔고 데이터가 로드된 상태에서만 정리 수행
            with self.state.lock:
                holding_codes = [s.get('pdno') for s in holdings if s.get('pdno')]
                active_stock_ids = [f"STOCK_{c}" for c in holding_codes]
                for w_id in list(self.state.last_times.keys()):
                    if w_id.upper().startswith("STOCK_") and w_id.upper() not in active_stock_ids:
                        # 해당 워커의 모든 흔적 제거
                        self.state.last_times.pop(w_id, None)
                        self.state.worker_statuses.pop(w_id.upper(), None)
                        self.state.worker_results.pop(w_id.upper(), None)
                        self.state.worker_last_tasks.pop(w_id.upper(), None)
                        self.state.worker_names.pop(w_id.upper(), None)

        # 4. 실시간 가격 기반 수익률 및 자산 재계산 (KIS API 지연 대응)
        with self.state.lock:
            eval_delta = 0
            for h in self.state.holdings:
                c = h.get('pdno')
                if c in temp_info:
                    info = temp_info[c]
                    curr_p = float(info['price'])
                    avg_p = float(h.get('pchs_avg_pric', 0))
                    qty = int(float(h.get('hldg_qty', 0)))
                    
                    # 기존 평가금액과 실시간 평가금액 차이 계산
                    old_eval = float(h.get('evlu_amt', 0))
                    new_eval = curr_p * qty
                    eval_delta += (new_eval - old_eval)
                    
                    if avg_p > 0 and curr_p > 0:
                        pnl_amt = (curr_p - avg_p) * qty
                        pnl_rt = ((curr_p / avg_p) - 1) * 100
                        h['evlu_pfls_rt'] = f"{pnl_rt:.2f}"
                        h['evlu_pfls_amt'] = str(int(pnl_amt))
                        h['prpr'] = str(int(curr_p))
                        h['evlu_amt'] = str(int(new_eval)) # 평가금액 업데이트

            # 총자산 및 일일 수익률 즉시 갱신 (지연 방지)
            if eval_delta != 0 and self.state.asset:
                self.state.asset['total_asset'] = float(self.state.asset.get('total_asset', 0)) + eval_delta
                self.state.asset['stock_eval'] = float(self.state.asset.get('stock_eval', 0)) + eval_delta
                self._update_asset_metrics(self.state.asset)

            self.state.stock_info.update(temp_info)
            self.state.last_update_time = get_now().strftime('%H:%M:%S')

            # [Fix] 실시간 시세를 추천 종목 및 인기/거래량 리스트에 반영하여 TUI 가격 최신화
            # ai_recommendations, hot_raw, vol_raw는 최초 수집 시점의 스냅샷 가격을 갖고 있으므로
            # bulk_data(Naver 실시간 API)로 가격/등락률을 덮어씌워 대시보드 표시 정확성 보장
            if bulk_data:
                for rec in getattr(self.strategy, 'ai_recommendations', []):
                    rt = bulk_data.get(rec.get('code'))
                    if rt:
                        rec['price'] = rt['price']
                        rec['rate'] = rt['rate']
                for item_list in [self.state.hot_raw, self.state.vol_raw]:
                    for item in item_list:
                        rt = bulk_data.get(item.get('code'))
                        if rt:
                            item['price'] = rt['price']
                            item['rate'] = rt['rate']

        if is_heavy_cycle:
            self.last_heavy_sync = curr_t
