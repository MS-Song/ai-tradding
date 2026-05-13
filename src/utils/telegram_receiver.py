import os
import threading
import asyncio
from telegram import Update, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from src.logger import log_error

class TelegramCommandListener:
    """텔레그램을 통한 원격 제어 및 상태 조회 명령어 수신기.
    
    사용자로부터 텔레그램 메시지(명령어)를 수신하여 계좌 상태 조회, 수동 매매 집행, 
    긴급 청산(Panic), 시스템 설정 변경 등의 기능을 수행합니다.
    별도의 백그라운드 스레드에서 폴링(Polling) 방식으로 동작합니다.

    Attributes:
        dm: 명령어 실행 및 상태 업데이트를 위한 DataManager 인스턴스.
        token (str): 텔레그램 봇 API 토큰.
        chat_id (str): 허용된 사용자 채팅 ID (보안 검증용).
        is_active (bool): 토큰과 채팅 ID 설정 여부에 따른 활성화 상태.
    """
    def __init__(self, dm=None):
        """TelegramCommandListener를 초기화합니다.

        Args:
            dm (DataManager, optional): 명령어 실행 및 상태 업데이트를 위한 데이터 관리자.
        """
        self.dm = dm
        self.token = os.getenv("TELEGRAM_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.is_active = bool(self.token and self.chat_id)
        self.app = None
        self.worker_thread = None

    def start(self):
        """명령어 수신기를 시작합니다. 백그라운드 스레드에서 폴링 루프를 생성합니다."""
        if not self.is_active:
            return
        
        self.worker_thread = threading.Thread(target=self._run_polling, daemon=True, name="TelegramListener")
        self.worker_thread.start()

    def stop(self):
        """수신기를 중지하고 관련 비동기 리소스를 안전하게 해제합니다."""
        self.is_active = False
        try:
            if hasattr(self, 'loop') and self.loop and self.loop.is_running() and self.app:
                if self.app.updater:
                    asyncio.run_coroutine_threadsafe(self.app.updater.stop(), self.loop)
                asyncio.run_coroutine_threadsafe(self.app.stop(), self.loop)
        except Exception as e:
            log_error(f"TelegramListener Stop Error: {e}")

    def _run_polling(self):
        """텔레그램 폴링을 실행하는 메인 루프. 
        
        비동기 이벤트 루프를 생성하고 명령어 핸들러를 등록한 뒤 전용 스레드에서 대기합니다.
        """
        try:
            # 새로운 이벤트 루프 생성 및 설정
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            
            async def update_status_loop():
                """수신기가 정상 작동 중임을 DataManager에 주기적으로 알립니다."""
                while self.is_active:
                    if self.dm:
                        self.dm.update_worker_status("TG_RECEIVE", result="정상", last_task="명령 대기중")
                    await asyncio.sleep(10)
            
            async def post_init(application):
                """봇 시작 직후 메뉴에 표시될 명령어 목록을 설정합니다."""
                commands = [
                    BotCommand("status", "계좌 요약 및 상태 확인"),
                    BotCommand("diagnosis", "AI 즉시 진단 실행 (스케줄 무시)"),
                    BotCommand("log", "최신 트레이딩 로그 10개 확인"),
                    BotCommand("error", "최신 에러 로그 10개 확인"),
                    BotCommand("buy", "수동 매수 (/buy 종목코드 수량 [가격])"),
                    BotCommand("sell", "수동 매도 (/sell 종목코드 수량 [가격])"),
                    BotCommand("reset", "모든 특수 상태 해제 (AI 자율 복귀)"),
                    BotCommand("defensive", "강제 방어모드 전환 (리스크 최소화)"),
                    BotCommand("pause", "신규 매수 일시 정지"),
                    BotCommand("panic", "전 종목 시장가 긴급 청산"),
                ]
                await application.bot.set_my_commands(commands)
                self.loop.create_task(update_status_loop())
            
            self.app = ApplicationBuilder().token(self.token).post_init(post_init).build()
            
            # 명령어 핸들러 등록
            self.app.add_handler(CommandHandler("status", self._cmd_status))
            self.app.add_handler(CommandHandler("diagnosis", self._cmd_diagnosis))
            self.app.add_handler(CommandHandler("log", self._cmd_log))
            self.app.add_handler(CommandHandler("error", self._cmd_error))
            self.app.add_handler(CommandHandler("buy", self._cmd_buy))
            self.app.add_handler(CommandHandler("sell", self._cmd_sell))
            self.app.add_handler(CommandHandler("reset", self._cmd_reset))
            self.app.add_handler(CommandHandler("defensive", self._cmd_defensive))
            self.app.add_handler(CommandHandler("pause", self._cmd_pause))
            self.app.add_handler(CommandHandler("panic", self._cmd_panic))
            
            # 폴링 시작 (Blocking in this thread)
            self.app.run_polling(close_loop=False, drop_pending_updates=True)
        except Exception as e:
            log_error(f"TelegramCommandListener Polling Error: {e}")

    async def _verify_auth(self, update: Update) -> bool:
        """메시지를 보낸 사용자가 허가된 사용자(`chat_id`)인지 보안 검증을 수행합니다.

        Args:
            update (Update): 수신된 텔레그램 업데이트 객체.

        Returns:
            bool: 허가된 사용자인 경우 True, 아니면 False.
        """
        if not update.effective_chat or str(update.effective_chat.id) != str(self.chat_id):
            return False
        return True

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/status: 계좌 현황, 보유 종목 상세, AI 추천 목록을 조회하여 전송합니다."""
        if not await self._verify_auth(update): return
        if not self.dm: return
        self.dm.update_worker_status("TG_RECEIVE", result="성공", last_task="/status 처리")
        
        try:
            asset = self.dm.cached_asset
            vibe = getattr(self.dm.state, "vibe", "Unknown")
            paused = getattr(self.dm.state, "is_trading_paused", False)
            panic = getattr(self.dm.state, "is_panic", False)
            
            holdings = getattr(self.dm.state, "holdings", [])
            dema = getattr(self.dm.state, "dema_info", {})

            broker_type = os.getenv("BROKER_TYPE", "KIS").upper()
            broker_name = "키움증권 (Kiwoom)" if broker_type == "KIWOOM" else "한국투자증권 (KIS)"

            # 지수 정보 추출
            idx_str = ""
            for idx_name in ["KOSPI", "KOSDAQ"]:
                d = dema.get(idx_name, {})
                if d:
                    trend = "↑" if d.get('diff', 0) >= 0 else "↓"
                    idx_str += f" | {idx_name}{trend}"

            # 보유 종목 상세 요약
            holdings_detail = ""
            if not holdings:
                holdings_detail = "🔹 현재 보유 종목이 없습니다.\n"
            else:
                sorted_h = sorted(holdings, key=lambda x: float(x.get('evlu_pfls_rt', 0)), reverse=True)
                for h in sorted_h:
                    name = h.get('prdt_name', 'Unknown')
                    code = h.get('pdno', '000000')
                    rt = float(h.get('evlu_pfls_rt', 0))
                    pfls_amt = int(float(h.get('evlu_pfls_amt', 0)))
                    prpr = int(float(h.get('prpr', 0)))
                    pchs = int(float(h.get('pchs_avg_pric', 0)))
                    qty = int(float(h.get('hldg_qty', 0)))
                    prdy_ctrt = float(h.get('prdy_ctrt', 0))
                    prdy_vrss = int(float(h.get('prdy_vrss', 0)))
                    
                    emoji = "🔥" if rt >= 3 else "📈" if rt > 0 else "📉" if rt < -3 else "🔹"
                    
                    holdings_detail += (
                        f"{emoji} <b>{name}</b> ({code})\n"
                        f"┣ 💰수익: <code>{rt:+.2f}%</code> ({pfls_amt:+,}원)\n"
                        f"┣ 📊변동: <code>{prdy_ctrt:+.2f}%</code> ({prdy_vrss:+,}원)\n"
                        f"┗ 💵단가: {pchs:,} → {prpr:,}원 (<code>{qty}주</code>)\n"
                        f"───────────────\n"
                    )

            pnl_amt = asset.get('daily_pnl_amt', 0)
            pnl_rt = asset.get('daily_pnl_rate', 0.0)
            pnl_emoji = "🚀" if pnl_rt >= 1.0 else "🟢" if pnl_rt >= 0 else "🔴"

            msg = (
                f"📊 <b>현재 시스템 상태</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🏛️ <b>증권사</b>: <code>[{broker_type}] {broker_name}</code>\n"
                f"🌍 <b>시장 VIBE</b>: <code>{vibe}</code>{idx_str}\n"
                f"💰 <b>총 자산</b>: {int(asset.get('total_asset', 0)):,}원\n"
                f"{pnl_emoji} <b>당일 손익</b>: {int(pnl_amt):+,}원 ({pnl_rt:+.2f}%)\n"
                f"💵 <b>가용 현금</b>: {int(asset.get('cash', 0)):,}원\n"
                f"⏸️ <b>매수 일시정지</b>: {'🟢 켜짐' if paused else '🔴 꺼짐'}\n"
                f"🚨 <b>패닉 모드</b>: {'🟢 발동' if panic else '🔴 안전'}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📦 <b>보유 종목 상세 ({len(holdings)}개)</b>\n"
                f"{holdings_detail}"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"💡 <b>AI 추천 종목 TOP 5</b>\n"
            )
            
            recs = getattr(self.dm.state, "recommendations", [])
            if not recs:
                msg += "🔹 추천 데이터가 아직 없습니다.\n"
            else:
                for r in recs[:5]:
                    score = r.get('score', 0)
                    code = r.get('code', '000000')
                    name = r.get('name', 'Unknown')
                    msg += f"┣ <code>[{score:.0f}점]</code> {code} {name}\n"
            
            msg += "━━━━━━━━━━━━━━━━━━━━"
            await update.message.reply_text(msg, parse_mode='HTML')
        except Exception as e:
            log_error(f"Telegram Inbound /status Error: {e}")

    async def _cmd_diagnosis(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/diagnosis: 스케줄링된 시간과 관계없이 즉시 AI 시장 분석 및 전략 수립을 실행합니다."""
        if not await self._verify_auth(update): return
        if self.dm:
            self.dm.update_worker_status("TG_RECEIVE", result="성공", last_task="/diagnosis 처리")
            try:
                msg = self.dm.trigger_ai_diagnosis()
                await update.message.reply_text(msg, parse_mode='HTML')
            except Exception as e:
                log_error(f"Telegram Inbound /diagnosis Error: {e}")

    async def _cmd_log(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/log: 최근 10개의 트레이딩 로그를 조회합니다."""
        if not await self._verify_auth(update): return
        if self.dm:
            self.dm.update_worker_status("TG_RECEIVE", result="성공", last_task="/log 처리")
            try:
                msg = self.dm.get_recent_logs(10)
                await update.message.reply_text(msg, parse_mode='HTML')
            except Exception as e:
                log_error(f"Telegram Inbound /log Error: {e}")

    async def _cmd_error(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/error: 최근 10개의 시스템 에러 로그를 조회합니다."""
        if not await self._verify_auth(update): return
        if self.dm:
            self.dm.update_worker_status("TG_RECEIVE", result="성공", last_task="/error 처리")
            try:
                msg = self.dm.get_recent_errors(10)
                await update.message.reply_text(msg, parse_mode='HTML')
            except Exception as e:
                log_error(f"Telegram Inbound /error Error: {e}")

    async def _cmd_panic(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/panic: 전 종목 긴급 시장가 청산 및 신규 매수 차단 명령을 수행합니다."""
        if not await self._verify_auth(update): return
        if self.dm:
            self.dm.update_worker_status("TG_RECEIVE", result="성공", last_task="/panic 처리")
            try:
                self.dm.execute_emergency_panic()
                await update.message.reply_text("🚨 <b>긴급 패닉 명령 수신됨!</b>\n신규 매수가 차단되고 전 종목 긴급 청산이 진행됩니다.", parse_mode='HTML')
            except Exception as e:
                log_error(f"Telegram Inbound /panic Error: {e}")

    async def _cmd_pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/pause: AI의 신규 종목 매수 진입을 일시적으로 정지시킵니다."""
        if not await self._verify_auth(update): return
        if self.dm:
            self.dm.update_worker_status("TG_RECEIVE", result="성공", last_task="/pause 처리")
            try:
                self.dm.toggle_trading_pause(True)
                await update.message.reply_text("⏸️ <b>매수 일시 정지됨</b>\n신규 AI 진입이 차단됩니다.", parse_mode='HTML')
            except Exception as e:
                log_error(f"Telegram Inbound /pause Error: {e}")

    async def _cmd_defensive(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/defensive: 시스템 장세를 강제로 방어모드(Defensive)로 전환합니다."""
        if not await self._verify_auth(update): return
        if self.dm:
            self.dm.update_worker_status("TG_RECEIVE", result="성공", last_task="/defensive 처리")
            try:
                self.dm.force_defensive_mode()
                await update.message.reply_text("🛡️ <b>강제 방어모드 전환 완료</b>\n손절선이 타이트해집니다.", parse_mode='HTML')
            except Exception as e:
                log_error(f"Telegram Inbound /defensive Error: {e}")
                
    async def _cmd_reset(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/reset: 패닉, 일시정지, 강제 방어모드 등의 모든 특수 상태를 해제하고 AI 자율 판단 모드로 복귀합니다."""
        if not await self._verify_auth(update): return
        if self.dm:
            self.dm.update_worker_status("TG_RECEIVE", result="성공", last_task="/reset 처리")
            try:
                self.dm.reset_emergency_state()
                await update.message.reply_text("🔄 <b>모든 특수 상태 해제 완료</b>\n시스템이 AI 자율 판단 모드로 복귀했습니다.", parse_mode='HTML')
            except Exception as e:
                log_error(f"Telegram Inbound /reset Error: {e}")

    async def _parse_trade_args(self, context: ContextTypes.DEFAULT_TYPE):
        """수동 매매 명령어(/buy, /sell)의 인자(코드, 수량, 가격)를 파싱합니다.

        Args:
            context (ContextTypes.DEFAULT_TYPE): 텔레그램 컨텍스트 객체.

        Returns:
            tuple: (종목코드, 수량, 가격, 에러메시지) 형태의 튜플. 에러 없을 시 에러메시지는 None.
        """
        args = context.args
        if len(args) < 2:
            return None, None, None, "⚠️ <b>사용법 오류</b>\n형식: /명령어 [종목코드] [수량] [가격(선택)]\n예시: /buy 005930 10\n예시: /sell 005930 10 80000"
        
        code = args[0]
        try:
            qty = int(args[1])
            if qty <= 0: raise ValueError
        except ValueError:
            return None, None, None, "⚠️ 수량은 양의 정수여야 합니다."
            
        price = None
        if len(args) >= 3:
            try:
                price = float(args[2])
                if price <= 0: raise ValueError
            except ValueError:
                return None, None, None, "⚠️ 가격은 양수여야 합니다."
                
        return code, qty, price, None

    async def _cmd_buy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/buy: 지정된 종목에 대한 수동 매수 주문을 집행합니다."""
        if not await self._verify_auth(update): return
        code, qty, price, err = await self._parse_trade_args(context)
        if err:
            await update.message.reply_text(err, parse_mode='HTML')
            return
            
        if self.dm:
            self.dm.update_worker_status("TG_RECEIVE", result="성공", last_task=f"/buy {code} 처리")
            try:
                success, msg = self.dm.execute_manual_trade("BUY", code, qty, price)
                icon = "✅" if success else "❌"
                await update.message.reply_text(f"{icon} <b>수동 매수 결과</b>\n{msg}", parse_mode='HTML')
            except Exception as e:
                log_error(f"Telegram Inbound /buy Error: {e}")

    async def _cmd_sell(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/sell: 지정된 종목에 대한 수동 매도 주문을 집행합니다."""
        if not await self._verify_auth(update): return
        code, qty, price, err = await self._parse_trade_args(context)
        if err:
            await update.message.reply_text(err, parse_mode='HTML')
            return
            
        if self.dm:
            self.dm.update_worker_status("TG_RECEIVE", result="성공", last_task=f"/sell {code} 처리")
            try:
                success, msg = self.dm.execute_manual_trade("SELL", code, qty, price)
                icon = "✅" if success else "❌"
                await update.message.reply_text(f"{icon} <b>수동 매도 결과</b>\n{msg}", parse_mode='HTML')
            except Exception as e:
                log_error(f"Telegram Inbound /sell Error: {e}")
