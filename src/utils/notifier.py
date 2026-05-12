import os
import threading
import queue
import asyncio
import time
import html
from datetime import datetime
from src.logger import log_error, telegram_logger
from src.utils import get_now


class TelegramNotifier:
    """텔레그램 메시지 전송 및 알림 서비스.
    
    매매 내역, 시장 상황, 긴급 경보 등을 텔레그램 봇을 통해 사용자에게 전송합니다.
    시스템 성능 저하를 방지하기 위해 큐(`msg_queue`) 기반의 비동기 백그라운드 
    워커 스레드를 사용하여 메시지를 순차적으로 처리합니다.

    Attributes:
        token (str): 텔레그램 봇 API 토큰.
        chat_id (str): 알림을 받을 텔레그램 채팅 ID.
        dm: 워커 상태 업데이트를 위한 DataManager 인스턴스.
        is_active (bool): 토큰과 채팅 ID 설정 여부에 따른 활성화 상태.
        msg_queue (Queue): 전송 대기 메시지 큐.
    """
    def __init__(self, token=None, chat_id=None, dm=None):
        """TelegramNotifier를 초기화하고 백그라운드 메시지 워커를 시작합니다.

        Args:
            token (str, optional): 텔레그램 봇 API 토큰. 미지정 시 환경변수 활용.
            chat_id (str, optional): 알림을 받을 텔레그램 채팅 ID. 미지정 시 환경변수 활용.
            dm (DataManager, optional): 워커 상태 보고를 위한 데이터 관리자.
        """
        self.token = token or os.getenv("TELEGRAM_TOKEN")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        self.dm = dm  # DataManager 참조 저장
        self.is_active = bool(self.token and self.chat_id)
        
        self.msg_queue = queue.Queue()
        self.is_running = True
        self.worker_thread = None
        self.status_msg = "대기중"
        self.last_result = "-"
        self.last_task = "-"
        
        if self.is_active:
            self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self.worker_thread.start()
            self.send_message("🚀 <b>Vibe-Trader 알림 엔진이 시작되었습니다.</b>")
        else:
            from src.logger import logger
            logger.info("ℹ️ 텔레그램 설정이 비어 있어 알림 엔진을 비활성화합니다.")

    def _worker_loop(self):
        """별도 스레드에서 asyncio 이벤트 루프를 생성하고 메시지 전송 루프를 실행합니다.
        
        메인 스레드의 블로킹을 방지하기 위해 전용 스레드에서 비동기 루프를 관리합니다.
        """
        asyncio.run(self._async_send_loop())

    async def _async_send_loop(self):
        """큐에서 메시지를 꺼내어 텔레그램 봇 API로 실제 전송하는 비동기 루프.
        
        API 속도 제한(Rate Limit)을 준수하기 위해 전송 간 간격을 두며, 
        실패 시 재시도 로직을 포함합니다.
        """
        from telegram import Bot
        from telegram.constants import ParseMode
        
        bot = Bot(token=self.token)
        
        while self.is_running:
            try:
                # 큐에서 메시지 대기 (타임아웃을 두어 루프 종료 체크)
                try:
                    msg, parse_mode = self.msg_queue.get(timeout=1.0)
                    if msg == "__QUIT__":
                        self.msg_queue.task_done()
                        break
                except queue.Empty:
                    continue

                # 메시지 전송
                self.status_msg = "전송중"
                clean_preview = msg[:30].replace('\n', ' ')
                self.last_task = f"메시지 전송: {clean_preview}..."
                if self.dm:
                    self.dm.update_worker_status("TELEGRAM", last_task=self.last_task)
                
                await bot.send_message(
                    chat_id=self.chat_id,
                    text=msg,
                    parse_mode=parse_mode or ParseMode.HTML
                )
                self.last_result = "성공"
                # 발송 내역 로깅
                clean_msg = msg.replace('\n', ' ')
                telegram_logger.info(f"SENT | {clean_msg[:100]}...")
                
                if self.dm:
                    self.dm.update_worker_status("TELEGRAM", result="성공", last_task=self.last_task)
                
                self.msg_queue.task_done()
                self.status_msg = "대기중"
                
                # 텔레그램 API 속도 제한 방지 (초당 1건 정도)
                await asyncio.sleep(0.5)
                
            except Exception as e:
                self.status_msg = "에러"
                self.last_result = "실패"
                self.last_task = f"전송 실패: {str(e)[:30]}"
                if self.dm:
                    self.dm.update_worker_status("TELEGRAM", result="실패", last_task=self.last_task)
                
                log_error(f"Telegram Send Error (ID: {self.chat_id}): {e}")
                await asyncio.sleep(2) # 에러 발생 시 잠시 대기

    def send_message(self, text, parse_mode=None):
        """메시지를 전송 큐에 추가합니다 (Non-blocking).

        Args:
            text (str): 전송할 메시지 본문 (HTML 지원).
            parse_mode (ParseMode, optional): 텔레그램 파싱 모드. 기본값은 HTML.
        """
        if not self.is_active:
            return
        self.msg_queue.put((text, parse_mode))

    def notify_trade(self, trade_type, code, name, price, qty, memo="", profit=0, model_id=""):
        """실시간 매매 체결 내역을 서식화하여 전송합니다.

        Args:
            trade_type (str): 매매 유형 (매수, 익절, 손절, 교체 등).
            code (str): 종목 코드.
            name (str): 종목명.
            price (float): 체결 가격.
            qty (int): 체결 수량.
            memo (str, optional): 매매 사유나 메모.
            profit (float, optional): 발생 수익금 (매도 시).
            model_id (str, optional): 매매를 결정한 AI 모델 ID.
        """
        emoji = "📈" if "매수" in trade_type else "📉"
        if "익절" in trade_type: emoji = "💰"
        if "손절" in trade_type: emoji = "🚫"
        if "교체" in trade_type: emoji = "🔄"
        
        # HTML 이스케이프 처리
        trade_type_esc = html.escape(trade_type)
        name_esc = html.escape(name)
        memo_esc = html.escape(memo)
        model_id_esc = html.escape(model_id)
        
        profit_str = f"\n💰 <b>수익금</b>: {int(profit):+,}원" if profit != 0 else ""
        model_str = f" (<code>{model_id_esc}</code>)" if model_id else ""
        
        msg = (
            f"{emoji} <b>[{trade_type_esc}] {name_esc}</b>{model_str}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔹 <b>종목코드</b>: <code>{code}</code>\n"
            f"🔹 <b>체결가격</b>: {int(price):,}원\n"
            f"🔹 <b>체결수량</b>: {qty}주\n"
            f"🔹 <b>체결금액</b>: {int(price * qty):,}원\n"
            f"🔹 <b>사유</b>: {memo_esc}"
            f"{profit_str}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ {get_now().strftime('%H:%M:%S')}"
        )
        self.send_message(msg)

    def notify_alert(self, title, message, is_critical=False):
        """시스템 경보 및 알림 메시지를 전송합니다.

        Args:
            title (str): 알림 제목.
            message (str): 알림 상세 내용.
            is_critical (bool): 긴급 상황 여부 (True일 경우 사이렌 이모지 사용).
        """
        emoji = "🚨" if is_critical else "⚠️"
        title_esc = html.escape(title)
        message_esc = html.escape(message)
        msg = (
            f"{emoji} <b>{title_esc}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{message_esc}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ {get_now().strftime('%H:%M:%S')}"
        )
        self.send_message(msg)

    def notify_market_start(self, vibe):
        """정규장 개시 알림과 오늘의 시장 전망을 전송합니다.

        Args:
            vibe (str): 오늘의 시장 분위기 (Bull, Bear 등).
        """
        vibe_esc = html.escape(vibe)
        msg = (
            f"🔔 <b>장 개시 알림 (09:00)</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"☀️ <b>오늘의 시장 VIBE</b>: <code>{vibe_esc}</code>\n"
            f"🚀 오늘도 성공적인 투자 되시길 바랍니다!\n"
            f"━━━━━━━━━━━━━━━━━━━━"
        )
        self.send_message(msg)

    def notify_market_end(self, asset_info):
        """장 마감 시 당일의 성과 요약 리포트를 전송합니다.

        Args:
            asset_info (dict): 당일 수익금, 수익률, 총 자산, 예수금 정보가 포함된 딕셔너리.
        """
        pnl = asset_info.get('daily_pnl_amt', 0)
        rate = asset_info.get('daily_pnl_rate', 0.0)
        emoji = "🥳" if pnl >= 0 else "😥"
        
        msg = (
            f"🏁 <b>장 마감 리포트 (15:30)</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{emoji} <b>수익금 (수익률)</b>: {int(pnl):+,}원 ({abs(rate):.2f}%)\n"
            f"💰 <b>현재 자산</b>: {int(asset_info.get('total_asset', 0)):,}원\n"
            f"💵 <b>예수금</b>: {int(asset_info.get('cash', 0)):,}원\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"고생하셨습니다!"
        )
        self.send_message(msg)

    def stop(self):
        """알림 엔진을 중지하고 백그라운드 스레드를 안전하게 종료합니다."""
        self.is_running = False
        if self.worker_thread and self.worker_thread.is_alive():
            self.msg_queue.put(("__QUIT__", None))
            # 큐에 남은 메시지가 처리될 때까지 잠시 대기 (최대 2초)
            self.worker_thread.join(timeout=2.0)
