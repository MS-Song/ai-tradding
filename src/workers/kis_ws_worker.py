import json
import time
import threading
import websocket
import requests
from src.workers.base import BaseWorker
from src.logger import logger, log_error
from src.utils import get_now

class KISWSWorker(BaseWorker):
    """한국투자증권(KIS) 실시간 웹소켓(시세/체결) 수신 워커.
    
    KIS 웹소켓 서버에 연결하여 보유 종목 및 관심 종목의 실시간 체결 데이터를 수신합니다.
    인증을 위해 전용 Approval Key를 발급받아 사용하며, 연결 유지 및 자동 재연결을 지원합니다.
    """
    
    def __init__(self, state, api, strategy):
        super().__init__("WS_KIS", state, 15.0)
        self.api = api
        self.strategy = strategy
        self.ws = None
        self.ws_thread = None
        self.subscribed_codes = set()
        self.is_connected = False
        self._reconnect_count = 0
        self._max_reconnect_delay = 120
        self._last_connect_attempt = 0
        self._intentional_close = False
        self._approval_key = None
        
    def run(self):
        """웹소켓 연결 상태를 모니터링하고 필요시 재연결합니다."""
        if not hasattr(self.api, "auth") or not self.api.auth.is_token_valid():
            self.set_busy("인증 대기중", "웹소켓")
            return
            
        if not self.is_connected or not self.ws or (self.ws_thread and not self.ws_thread.is_alive()):
            delay = min(10 * (2 ** self._reconnect_count), self._max_reconnect_delay)
            elapsed = time.time() - self._last_connect_attempt
            if elapsed < delay:
                remaining = int(delay - elapsed)
                self.set_busy(f"재연결 대기 ({remaining}초)", "웹소켓")
                return
            
            self.set_busy("연결 중", "웹소켓")
            self._connect()
        else:
            self._reconnect_count = 0
            self.set_result("수신 중", last_task="실시간 시세 수신 대기", friendly_name="웹소켓")
            self._check_and_subscribe()

    def _get_approval_key(self):
        """실시간 웹소켓 접속용 Approval Key를 발급받습니다."""
        try:
            url = f"{self.api.domain}/uapi/hashkey" # KIS는 hashkey 엔드포인트와 별도로 approval 발급 가능하나 uapi/hashkey와 형식이 유사함
            # 실제 KIS Approval Key 발급 API: /oauth2/Approval
            url = f"{self.api.domain}/oauth2/Approval"
            headers = {"content-type": "application/json; charset=utf-8"}
            body = {
                "grant_type": "client_credentials",
                "appkey": self.api.auth.appkey,
                "secretkey": self.api.auth.secret
            }
            res = requests.post(url, headers=headers, json=body, timeout=10)
            data = res.json()
            if "approval_key" in data:
                return data["approval_key"]
            else:
                log_error(f"KIS Approval Key 발급 실패: {data}")
                return None
        except Exception as e:
            log_error(f"KIS Approval Key 발급 중 예외: {e}")
            return None

    def _connect(self):
        """웹소켓 서버에 연결합니다."""
        self._last_connect_attempt = time.time()
        
        # Approval Key 발급
        self._approval_key = self._get_approval_key()
        if not self._approval_key:
            self._reconnect_count += 1
            return

        if self.ws:
            try:
                self._intentional_close = True
                self.ws.close()
            except:
                pass
            self.ws = None
            self._intentional_close = False
        
        # KIS 웹소켓 도메인 (모의/실전 구분)
        is_v = getattr(self.api.auth, "is_virtual", True)
        url = "ws://ops.koreainvestment.com:31000" if not is_v else "ws://ops.koreainvestment.com:21000"
        
        def on_open(ws):
            logger.info("✅ KIS 실시간 웹소켓 연결 성공")
            self.is_connected = True
            self._reconnect_count = 0
            self.subscribed_codes.clear()
            with self.state.lock:
                self.state.indicator_updates["KIS_WS"] = {
                    "time": time.time(), "status": "성공", "value": "연결됨", "remark": "웹소켓 정상"
                }
            self._check_and_subscribe()

        def on_message(ws, message):
            try:
                if message.startswith("{") or message.startswith("["):
                    # 제어 메시지 (JSON)
                    data = json.loads(message)
                    header = data.get("header", {})
                    if header.get("tr_id") == "PINGPONG":
                        ws.send(message) # PONG 응답
                else:
                    # 실시간 데이터 (Pipe separated)
                    # 형식: 수신구분(0:실시간, 1:암호화)|TR_ID|단축횟수|TR_KEY(코드)|데이터부
                    parts = message.split("|")
                    if len(parts) >= 5:
                        tr_id = parts[1]
                        code = parts[3]
                        data_body = parts[4]
                        if tr_id == "H0STCNT0":
                            self._handle_real_data(code, data_body)
                        elif tr_id == "H0STANT0":
                            self._handle_auction_data(code, data_body)
            except Exception as e:
                logger.debug(f"KIS WS Message Process Error: {e}")

        def on_error(ws, error):
            log_error(f"KIS WS Error: {error}")
            self.is_connected = False

        def on_close(ws, status, msg):
            if not self._intentional_close:
                logger.info(f"KIS 웹소켓 종료 (code={status}, msg={msg})")
                self._reconnect_count += 1
            self.is_connected = False

        self.ws = websocket.WebSocketApp(
            url, 
            on_open=on_open, on_message=on_message, on_error=on_error, on_close=on_close
        )
        self.ws_thread = threading.Thread(
            target=self.ws.run_forever, 
            kwargs={"ping_interval": 30, "ping_timeout": 10},
            daemon=True
        )
        self.ws_thread.start()

    def _check_and_subscribe(self):
        """구독 대상을 추출하여 KIS 웹소켓에 등록합니다."""
        if not self.is_connected or not self.ws:
            return
            
        current_codes = set()
        for h in self.state.holdings:
            code = h.get("pdno", "").strip()
            if code: current_codes.add(code)
            
        recs = getattr(self.strategy, "ai_recommendations", [])
        for r in recs:
            code = r.get("code", "").strip()
            if code: current_codes.add(code)
            
        for item_list in [self.state.hot_raw, self.state.vol_raw, self.state.amt_raw]:
            for item in (item_list or [])[:15]: 
                code = item.get("code", "").strip()
                if code: current_codes.add(code)
            
        new_codes = current_codes - self.subscribed_codes
        if not new_codes: return

        # KIS는 종목별로 개별 REG 요청 필요
        for code in list(new_codes):
            self._subscribe_item(code, "H0STCNT0") # 실시간 체결
            self._subscribe_item(code, "H0STANT0") # 동시호가 예상체결
            self.subscribed_codes.add(code)
            time.sleep(0.05) # 초당 20건 제한 준수

    def _subscribe_item(self, code: str, tr_id: str = "H0STCNT0"):
        """특정 종목에 대해 실시간 체결(H0STCNT0) 또는 동시호가(H0STANT0) 데이터를 구독합니다."""
        if not self.ws or not self._approval_key: return
        try:
            req = {
                "header": {
                    "approval_key": self._approval_key,
                    "custtype": "P",
                    "tr_type": "1",  # 1: 등록
                    "content-type": "utf-8"
                },
                "body": {
                    "input": {
                        "tr_id": tr_id,
                        "tr_key": code
                    }
                }
            }
            self.ws.send(json.dumps(req))
            logger.debug(f"[WS_KIS] {code} ({tr_id}) 구독 요청 완료")
        except Exception as e:
            log_error(f"KIS WS 구독 실패 ({code}): {e}")

    def _handle_auction_data(self, code: str, data_str: str):
        """수신된 동시호가 예상체결 데이터를 전역 상태에 반영합니다."""
        try:
            items = data_str.split("^")
            if len(items) < 2: return
            
            # [1] 예상체결가
            price = abs(float(items[1]))
            # [4] 예상체결가 전일대비율
            rate = float(items[4])
            
            with self.state.lock:
                if code not in self.state.stock_info:
                    self.state.stock_info[code] = {}
                
                info = self.state.stock_info[code]
                info["price"] = price
                info["day_rate"] = rate
                info["is_socket"] = True
                info["is_antc"] = True # 예상체결가 플래그
                
                # 워커 상태 업데이트
                self.state.indicator_updates["WS_KIS"] = {
                    "time": time.time(), "status": "성공", "value": "동시호가 수신 중", "remark": f"최근: {code}"
                }
        except:
            pass

    def _handle_real_data(self, code: str, data_str: str):
        """수신된 실시간 데이터(체결가 등)를 전역 상태에 반영합니다."""
        try:
            # KIS 주식체결(H0STCNT0) 데이터부 형식 (유니코드 구분자 ^ 사용)
            # [0]체결시간, [1]현재가, [2]전일대비부호, [3]전일대비, [4]전일대비율, ...
            items = data_str.split("^")
            if len(items) < 2: return
            
            price = abs(float(items[1]))
            # [4] 전일대비율
            rate = float(items[4])
            # [12] 누적거래량
            vol = float(items[12]) if len(items) > 12 else 0
            
            with self.state.lock:
                if code in self.state.stock_info:
                    self.state.stock_info[code]["price"] = price
                    self.state.stock_info[code]["day_rate"] = rate
                    self.state.stock_info[code]["is_socket"] = True
                    self.state.stock_info[code]["is_antc"] = False # 실체결 시 플래그 해제
                    if vol > 0:
                        self.state.stock_info[code]["vol"] = vol
                else:
                    self.state.stock_info[code] = {"price": price, "day_rate": rate, "vol": vol, "is_socket": True, "is_antc": False}
                
                # 워커 상태 업데이트
                self.state.indicator_updates["WS_KIS"] = {
                    "time": time.time(), "status": "성공", "value": "실시간 시세 수신 중", "remark": f"최근: {code}"
                }

                # 보유 종목 수익률 실시간 갱신
                for h in self.state.holdings:
                    if h.get("pdno", "").strip() == code:
                        h["prpr"] = str(price)
                        qty = float(h.get("hldg_qty", 0))
                        avg_p = float(h.get("pchs_avg_pric", 0))
                        h["evlu_amt"] = str(price * qty)
                        if avg_p > 0:
                            h["evlu_pfls_rt"] = str(round((price - avg_p) / avg_p * 100, 2))
                            h["evlu_pfls_amt"] = str((price - avg_p) * qty)
                        break
        except Exception as e:
            pass
