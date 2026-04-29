import time
from datetime import datetime
from src.workers.base import BaseWorker
from src.logger import log_error

class RetrospectiveWorker(BaseWorker):
    def __init__(self, state, strategy, notifier=None):
        # 30분 단위로 체크하지만 1분 간격으로 루프 돌며 시간 체크
        super().__init__("RETRO", state, interval=60.0)
        self.strategy = strategy
        self.notifier = notifier

    def run(self):
        now = datetime.now()
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
        if not self.notifier or not self.notifier.is_active:
            return
            
        date_str = datetime.now().strftime('%Y-%m-%d')
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
        msg += f"⏰ {datetime.now().strftime('%H:%M:%S')} 기준"
        
        self.notifier.send_message(msg)
