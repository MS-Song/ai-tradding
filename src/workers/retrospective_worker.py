import time
from src.workers.base import BaseWorker
from src.logger import log_error
from src.utils import get_now


class RetrospectiveWorker(BaseWorker):
    """장 마감 후 당일 매매 내역을 분석하고 복기 리포트를 생성하는 워커.
    
    평일 16:00부터 22:00까지 30분 주기로 동작하며, 당일의 수익/손실 TOP 3 종목을 
    AI가 분석하여 매매 적절성과 교훈을 도출합니다. 데이터 보충을 위해 종가 정보를 
    지속적으로 업데이트하며 최대 3회까지 분석을 고도화합니다.

    Attributes:
        strategy: 복기 로직을 실행하기 위한 VibeStrategy 인스턴스.
        notifier: 복기 리포트 전송을 위한 TelegramNotifier 인스턴스.
    """
    def __init__(self, state, strategy, notifier=None):
        """RetrospectiveWorker를 초기화합니다.

        Args:
            state (DataManager): 시스템 전역 상태 인스턴스.
            strategy (VibeStrategy): 복기 로직을 수행할 전략 엔진.
            notifier (TelegramNotifier, optional): 복기 리포트 전송 인스턴스.
        """
        # 30분 단위로 체크하지만 1분 간격으로 루프 돌며 시간 체크
        super().__init__("RETRO", state, interval=60.0)
        self.strategy = strategy
        self.notifier = notifier

    def run(self):
        """복기 리포트 생성 및 업데이트 루틴을 수행합니다.
        
        1. 작동 시간(16:00~22:00) 및 주말 여부를 확인합니다.
        2. 30분 단위 정기 시점 또는 16:00 리포트 누락 시 분석을 트리거합니다.
        3. `RetrospectiveEngine`을 통해 AI 복기 분석을 수행하고 텔레그램으로 전송합니다.
        """
        now = get_now()
        curr_time_str = now.strftime('%H:%M')
        today_str = now.strftime('%Y-%m-%d')
        
        # 16:00 ~ 22:00 사이 작동
        if not ("16:00" <= curr_time_str <= "22:00"):
            self.state.update_worker_status("RETRO", result="대기", last_task="작동 시간 외 (16:00~22:00)", friendly_name="RETRO_ENG")
            return

        # 주말 제외 (0: 월, 5: 토, 6: 일)
        if now.weekday() >= 5:
            self.state.update_worker_status("RETRO", result="대기", last_task="주말 스킵", friendly_name="RETRO_ENG")
            return

        # 30분 단위 체크 (16:00, 16:30, ...)
        is_trigger_time = (now.minute % 30 == 0)
        
        # [보충 발송] 16:00~16:29 사이에 엔진이 켜졌는데 16:00 리포트가 없다면 즉시 발송 시도
        catch_up_1600 = ("16:00" <= curr_time_str < "16:30") and (self.state.notified_dates.get(f"retro_{today_str}_16:00") != "DONE")

        if is_trigger_time or catch_up_1600:
            target_time_str = "16:00" if catch_up_1600 and not is_trigger_time else curr_time_str
            key = f"retro_{today_str}_{target_time_str}"
            
            if self.state.notified_dates.get(key) != "DONE":
                self.set_busy(f"투자 적중 복기 리포트({target_time_str}) 생성 중", friendly_name="RETRO_ENG")
                try:
                    # 리포트 생성 또는 업데이트
                    report = self.strategy.retrospective.update_post_market_analysis(
                        date_str=today_str, 
                        vibe=self.strategy.current_market_vibe
                    )
                    
                    if report:
                        # 첫 생성 시 또는 업데이트 시 알림 발송
                        mode = "생성" if report.get("update_count", 1) == 1 else "업데이트"
                        self._send_notification(report, mode)
                        
                        self.state.notified_dates[key] = "DONE"
                        self.set_result("성공", last_task=f"{target_time_str} 복기 리포트 {mode} 완료", friendly_name="RETRO_ENG")
                    else:
                        # 매매 기록이 없으면 리포트가 생성되지 않음
                        self.set_result("대기", last_task="오늘 매매 기록 없음 (복기 건너뜀)", friendly_name="RETRO_ENG")
                        self.state.notified_dates[key] = "DONE" # 매매 없어도 해당 시간 체크 완료 처리
                except Exception as e:
                    log_error(f"Retrospective Worker Error: {e}")
                    self.set_result("실패", last_task=f"리포트 생성 오류: {e}", friendly_name="RETRO_ENG")
        else:
            self.state.update_worker_status("RETRO", result="대기", last_task="발송 주기 대기 중", friendly_name="RETRO_ENG")

    def _send_notification(self, report, mode):
        """생성된 복기 리포트를 텔레그램으로 전송합니다.

        Args:
            report (dict): 분석 결과 데이터 (수익/손실 리스트, AI 총평 등).
            mode (str): 리포트 상태 설명 ("생성" 또는 "업데이트").
        """
        if not self.notifier or not self.notifier.is_active:
            return
            
        date_str = get_now().strftime('%Y-%m-%d')
        vibe = report.get("market_vibe", "N/A")
        
        msg = (
            f"🎯 <b>투자 적중 복기 리포트 ({mode})</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 <b>날짜</b>: {date_str}\n"
            f"🌍 <b>장세</b>: <code>{vibe}</code>\n"
            f"🔄 <b>업데이트</b>: {report.get('update_count', 1)}회차\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
        )
        
        # 수익 종목
        if report.get("top_profits"):
            msg += "✅ <b>수익 TOP 3</b>\n"
            for s in report["top_profits"]:
                msg += f"• <b>{s['name']}</b>: <code>{int(s['total_profit']):+,}원</code>"
                if s.get("closing_price"):
                    msg += f" (종가: <code>{int(s['closing_price']):,}</code>)"
                msg += "\n"
            msg += "\n"
            
        # 손실 종목
        if report.get("top_losses"):
            msg += "⚠️ <b>손실 TOP 3</b>\n"
            for s in report["top_losses"]:
                msg += f"• <b>{s['name']}</b>: <code>{int(s['total_profit']):+,}원</code>"
                if s.get("closing_price"):
                    msg += f" (종가: <code>{int(s['closing_price']):,}</code>)"
                msg += "\n"
            msg += "\n"
            
        # AI 총평
        ai_text = report.get("ai_analysis", "")
        if ai_text:
            msg += "🤖 <b>AI 복기 총평</b>\n"
            # 가독성을 위해 너무 길면 자르기 (텔레그램 제한 고려)
            if len(ai_text) > 2000: ai_text = ai_text[:2000] + "..."
            msg += f"<code>{ai_text}</code>\n"
            
        msg += "━━━━━━━━━━━━━━━━━━━━\n"
        msg += f"⏰ {get_now().strftime('%H:%M:%S')} 기준"
        
        self.notifier.send_message(msg)
