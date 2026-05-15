import json
import time
import threading
import traceback
import websocket
from src.workers.base import BaseWorker
from src.logger import logger, log_error

class KiwoomWSWorker(BaseWorker):
    """키움증권 실시간 웹소켓(시세/체결) 수신 워커.
    
    키움 REST API의 웹소켓 엔드포인트에 연결하여 보유 종목 및 관심 종목의
    실시간 체결 데이터를 수신합니다. 연결 끊김 시 자동 재연결하며,
    지수적 백오프(Exponential Backoff)를 적용하여 서버 부하를 방지합니다.
    """
    
    def __init__(self, state, api, strategy):
        # BaseWorker 초기화: 간격을 10초로 설정 (연결 상태 모니터링 주기)
        super().__init__("WS_KIWOOM", state, 10.0)
        self.api = api
        self.strategy = strategy
        self.ws = None
        self.ws_thread = None
        self.subscribed_codes = set()
        self.is_connected = False
        self._reconnect_count = 0
        self._max_reconnect_delay = 120  # 최대 재연결 대기 2분
        self._last_connect_attempt = 0
        self._intentional_close = False  # 의도적 종료 구분 플래그
        
    def run(self):
        """웹소켓 연결 상태를 모니터링하고 필요시 재연결합니다."""
        # API 인증 정보가 준비되지 않았다면 대기
        if not hasattr(self.api, "auth") or not self.api.auth.is_token_valid():
            self.set_busy("인증 대기중", "웹소켓")
            return
            
        if not self.is_connected or not self.ws or (self.ws_thread and not self.ws_thread.is_alive()):
            # 재연결 백오프: 반복 연결 시도 간격을 점진적으로 늘림
            delay = min(10 * (2 ** self._reconnect_count), self._max_reconnect_delay)
            elapsed = time.time() - self._last_connect_attempt
            if elapsed < delay:
                remaining = int(delay - elapsed)
                self.set_busy(f"재연결 대기 ({remaining}초)", "웹소켓")
                return
            
            self.set_busy("연결 중", "웹소켓")
            self._connect()
        else:
            self._reconnect_count = 0  # 연결 유지 중이면 카운터 리셋
            self.set_result("수신 중", last_task="실시간 시세 수신 대기", friendly_name="웹소켓")
            self._check_and_subscribe()

    def _connect(self):
        """웹소켓 서버에 연결합니다."""
        self._last_connect_attempt = time.time()
        
        # 기존 연결이 살아있으면 정리
        if self.ws:
            try:
                self._intentional_close = True
                self.ws.close()
            except:
                pass
            self.ws = None
            self._intentional_close = False
        
        ws_domain = getattr(self.api.auth, "ws_domain", "wss://api.kiwoom.com:10000")
        url = f"{ws_domain}/api/dostk/websocket"
        
        # 키움 REST API 웹소켓은 Authorization 헤더로 인증 (auth 객체에서 통합 관리되는 헤더 사용)
        headers = self.api.auth.get_auth_headers()
        
        def on_open(ws):
            logger.info("✅ 키움증권 실시간 웹소켓 연결 성공")
            self.is_connected = True
            self._reconnect_count = 0  # 연결 성공 시 백오프 카운터 리셋
            self.subscribed_codes.clear()  # 재연결 시 구독 초기화
            with self.state.lock:
                self.state.indicator_updates["KIWOOM_WS"] = {
                    "time": time.time(),
                    "status": "성공",
                    "value": "연결됨",
                    "remark": "웹소켓 서버 정상 연결"
                }
            # 연결 성공 직후 즉시 종목 구독 시도 (유휴 연결 방지)
            self._check_and_subscribe()

        def on_message(ws, message):
            try:
                data = json.loads(message)
                trnm = data.get("trnm", "")
                
                if trnm == "REAL":
                    # REG 요청 시 보낸 type에 따라 0B(체결) 또는 1B(예상체결)가 옴
                    for d in data.get("data", []):
                        if d.get("type") == "0B":
                            self._handle_real_data(d)
                        elif d.get("type") == "1B":
                            self._handle_auction_data(d)
                elif trnm == "PINGPONG":
                    # 서버 측 PINGPONG 메시지에 응답 (JSON 형태)
                    try:
                        ws.send(json.dumps({"trnm": "PINGPONG"}))
                    except:
                        pass
                elif trnm == "REG":
                    # 구독 응답 확인
                    ret_code = data.get("return_code", "")
                    if str(ret_code) != "0":
                        logger.warning(f"WS 구독 응답 오류: code={ret_code}, msg={data.get('return_msg', '')}")
                else:
                    # 기타 메시지 (디버그 로그)
                    logger.debug(f"WS 수신 (trnm={trnm}): {str(message)[:200]}")
            except json.JSONDecodeError:
                # 비-JSON 메시지(바이너리 등) 무시
                pass
            except Exception as e:
                logger.debug(f"WS 메시지 처리 오류: {e}")

        def on_error(ws, error):
            err_str = str(error)
            # 정상적인 종료 관련 에러는 무시
            if any(k in err_str for k in ["opcode=8", "Bye", "Connection to remote host was lost", "Connection is already closed", "socket is already closed"]):
                return
            log_error(f"Kiwoom WS Error: {err_str}")
            with self.state.lock:
                self.state.indicator_updates["KIWOOM_WS"] = {
                    "time": time.time(),
                    "status": "실패",
                    "value": "에러",
                    "remark": err_str[:100]
                }

        def on_close(ws, close_status_code, close_msg):
            # 의도적 종료가 아닌 경우에만 로깅
            if not self._intentional_close:
                logger.info(f"키움증권 웹소켓 연결 종료 (code={close_status_code}, msg={close_msg})")
                # 비정상 종료 시 원인 파악을 위한 추가 로그 (DEBUG)
                if close_status_code is None:
                    logger.debug("WS 연결이 서버에 의해 강제 종료되었거나 네트워크 타임아웃이 발생했을 수 있습니다.")
                self._reconnect_count += 1
            self.is_connected = False

        self.ws = websocket.WebSocketApp(
            url, 
            header=headers,
            on_open=on_open, 
            on_message=on_message, 
            on_error=on_error, 
            on_close=on_close
        )
        self.ws_thread = threading.Thread(
            target=self.ws.run_forever, 
            kwargs={
                "ping_interval": 0,    # 클라이언트 측 자동 핑 비활성화 (서버 핑 대응으로 충분)
                "reconnect": 0,        # 자체 워커 루프에서 재연결 관리
                "skip_utf8_validation": True
            },
            daemon=True
        )
        self.ws_thread.start()

    def _check_and_subscribe(self):
        """보유 종목, 실시간 인기, 거래량/거래대금 상위, AI 추천 등 필요한 모든 종목 코드를 추출하여 웹소켓 구독을 갱신합니다."""
        if not self.is_connected or not self.ws:
            return
            
        current_codes = set()
        
        # 1. 보유 종목
        for h in self.state.holdings:
            code = h.get("pdno", "").strip().replace("A", "")
            if code: current_codes.add(code)
            
        # 2. AI 추천 종목
        recs = getattr(self.strategy, "ai_recommendations", [])
        for r in recs:
            code = r.get("code", "").strip().replace("A", "")
            if code: current_codes.add(code)
            
        # 3. 실시간 랭킹 종목 (인기, 거래량, 거래대금)
        # rankings 리스트에서 상위 종목들을 추출하여 실시간 시세 보장
        for item_list in [self.state.hot_raw, self.state.vol_raw, self.state.amt_raw]:
            for item in (item_list or [])[:10]: # 각 리스트 상위 10개 (기존 20개에서 축소)
                code = item.get("code", "").strip().replace("A", "")
                if code: current_codes.add(code)
            
        # 새로 추가된 코드 구독 (중복 제거된 set 활용)
        new_codes = current_codes - self.subscribed_codes
        if new_codes:
            # 키움 REST API 웹소켓은 한 번에 여러 종목 REG 가능
            self._subscribe_items(list(new_codes))
            self.subscribed_codes.update(new_codes)

    def _subscribe_items(self, codes: list):
        """특정 종목들에 대해 실시간 체결(0B) 데이터를 구독합니다."""
        if not self.ws or not codes: return
        try:
            # 키움 REST API 웹소켓 REG 요청 형식
            # item은 세미콜론(;) 구분 문자열로 전달
            req = {
                "trnm": "REG",
                "grp_no": "1",
                "refresh": "1",  # 1:기존 등록 유지 후 추가
                "data": [
                    {
                        "item": ";".join(codes),
                        "type": "0B" # 주식체결
                    },
                    {
                        "item": ";".join(codes),
                        "type": "1B" # 주식예상체결
                    }
                ]
            }
            self.ws.send(json.dumps(req))
            logger.info(f"✅ [WS_KIWOOM] {len(codes)}종목 구독 추가 (총 {len(self.subscribed_codes) + len(codes)}종목)")
        except Exception as e:
            log_error(f"Kiwoom WS 구독 실패: {e}")

    def _handle_auction_data(self, d: dict):
        """수신된 동시호가 예상체결 데이터를 전역 상태에 반영합니다."""
        code = d.get("item", "").replace("A", "")
        vals = d.get("values", {})
        
        # 10: 예상체결가
        price_str = vals.get("10")
        if not price_str: return
        price = abs(float(price_str))
        
        # 12: 등락률
        rate = float(vals.get("12", 0))
        
        with self.state.lock:
            if code not in self.state.stock_info:
                self.state.stock_info[code] = {}
            
            info = self.state.stock_info[code]
            info["price"] = price
            info["day_rate"] = rate
            info["is_socket"] = True
            info["is_antc"] = True
            
            # 워커 상태 업데이트
            self.state.indicator_updates["WS_KIWOOM"] = {
                "time": time.time(), "status": "성공", "value": "동시호가 수신 중", "remark": f"최근: {code}"
            }

    def _handle_real_data(self, d: dict):
        """수신된 실시간 데이터를 상태 객체에 갱신합니다."""
        code = d.get("item", "").replace("A", "")
        vals = d.get("values", {})
        
        # 10: 현재가 (부호가 있을 수 있으므로 절대값 처리)
        price_str = vals.get("10")
        if not price_str: return
        price = abs(float(price_str))
        
        # 12: 등락률
        rate = float(vals.get("12", 0))
        # 13: 누적거래량
        vol = float(vals.get("13", 0))
        
        with self.state.lock:
            # 상세 정보 갱신
            if code in self.state.stock_info:
                self.state.stock_info[code]["price"] = price
                self.state.stock_info[code]["day_rate"] = rate
                self.state.stock_info[code]["is_socket"] = True
                self.state.stock_info[code]["is_antc"] = False
                if vol > 0:
                    self.state.stock_info[code]["vol"] = vol
            else:
                self.state.stock_info[code] = {"price": price, "day_rate": rate, "vol": vol, "is_socket": True, "is_antc": False}
                
            # 워커 상태 업데이트
            self.state.indicator_updates["WS_KIWOOM"] = {
                "time": time.time(), "status": "성공", "value": "실시간 시세 수신 중", "remark": f"최근: {code}"
            }
            
            # 보유 종목 현재가 및 평가금액 즉시 갱신
            for h in self.state.holdings:
                if h.get("pdno", "").replace("A", "") == code:
                    h["prpr"] = str(price)
                    qty = float(h.get("hldg_qty", 0))
                    avg_p = float(h.get("pchs_avg_pric", 0))
                    
                    h["evlu_amt"] = str(price * qty)
                    if avg_p > 0:
                        h["evlu_pfls_rt"] = str(round((price - avg_p) / avg_p * 100, 2))
                        h["evlu_pfls_amt"] = str((price - avg_p) * qty)
                    break

    def stop(self):
        """워커를 정지하고 웹소켓 연결을 정리합니다."""
        super().stop()
        self._intentional_close = True
        if self.ws:
            try:
                self.ws.close()
            except:
                pass
