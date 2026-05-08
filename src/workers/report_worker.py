import time
from datetime import datetime
from src.workers.base import BaseWorker
from src.utils import align_kr

class ReportWorker(BaseWorker):
    """정기적인 포트폴리오 및 시장 현황 리포트를 전송하는 워커.
    
    설정된 주기(예: 30분)마다 현재 자산 현황, 수익률, 보유 종목 상세 내역, 
    시장 장세(Vibe) 등을 요약하여 텔레그램으로 전송합니다.

    Attributes:
        strategy: 리포트 설정을 확인하기 위한 VibeStrategy 인스턴스.
        notifier: 리포트 전송을 위한 TelegramNotifier 인스턴스.
    """
    def __init__(self, state, strategy, notifier=None):
        """ReportWorker를 초기화합니다.

        Args:
            state (DataManager): 시스템 전역 상태 인스턴스.
            strategy (VibeStrategy): 리포트 설정을 읽어올 전략 엔진.
            notifier (TelegramNotifier, optional): 텔레그램 알림 전송 인스턴스.
        """
        # 모니터링을 위해 'REPORT' 워커로 등록, 10초마다 체크 (실제 발송은 설정된 주기 기준)
        super().__init__("REPORT", state, interval=10.0)
        self.strategy = strategy
        self.notifier = notifier
        self._first_run = True

    def run(self):
        """정기 리포트 전송 로직을 수행합니다.
        
        1. 엔진 시작 직후 데이터 로딩이 완료되면 최초 리포트를 발송합니다.
        2. 이후 설정된 `report_interval` 주기에 따라 정기 리포트를 발송합니다.
        3. 장 개시 시간(09:00~15:30) 내에서만 발송하며, 중복 발송을 방지합니다.
        """
        if not self.notifier or not self.notifier.is_active:
            self.state.update_worker_status("REPORT", result="대기", last_task="텔레그램 비활성")
            return

        curr_time_str = datetime.now().strftime('%H:%M')
        curr_min = datetime.now().minute
        today_str = datetime.now().strftime('%Y-%m-%d')
        
        # 설정에서 발송 주기 읽기 (0이면 비활성)
        interval = self.strategy.ai_config.get("report_interval", 30)
        if interval <= 0:
            self.state.update_worker_status("REPORT", result="대기", last_task="리포트 발송 비활성화 (0분)", friendly_name="REPORT_ENG")
            return

        # 1. 엔진 시작 시 지연 발송 (데이터 로딩 완료 후 1회)
        if self._first_run:
            if not self.state.holdings_fetched:
                self.state.update_worker_status("REPORT", status="데이터 로딩 대기", friendly_name="REPORT_ENG")
                return # 다음 사이클에 재시도
            
            self.state.update_worker_status("REPORT", status="최초 발송 중", friendly_name="REPORT_ENG")
            self._send_periodic_report("엔진 시작")
            self._first_run = False
            self.state.update_worker_status("REPORT", status="대기 중 (IDLE)", result="성공", last_task="엔진 시작 리포트 발송 완료", friendly_name="REPORT_ENG")
            return

        # 2. 설정된 주기 단위 정기 발송 (예: 30분이면 :00, :30)
        if curr_min % interval == 0:
            if self.state.notified_dates.get(f"report_{curr_time_str}") != today_str:
                if self.state.is_kr_market_active and "09:00" <= curr_time_str <= "15:30":
                    self.set_busy(f"리포트 전송 중", friendly_name="REPORT_ENG")
                    self._send_periodic_report(curr_time_str)
                    self.state.notified_dates[f"report_{curr_time_str}"] = today_str
                    self.set_result("성공", last_task=f"{curr_time_str} 리포트 발송 완료", friendly_name="REPORT_ENG")
                else:
                    self.set_result("대기", last_task="장외 시간대 리포트 스킵", friendly_name="REPORT_ENG")
        else:
            # 발송 시간이 아닐 때는 마지막 상태 유지
            pass

    def _send_periodic_report(self, time_str):
        """정기 포트폴리오 상태 리포트 생성 및 전송.

        현재 계좌의 총 자산, 당일 손익, 보유 종목별 수익률 및 시장 지수 추세를 
        HTML 서식으로 구성하여 텔레그램으로 전송합니다.

        Args:
            time_str (str): 리포트 식별을 위한 시간 문자열 (예: "10:30", "엔진 시작").
        """
        try:
            with self.state.lock:
                asset = dict(self.state.asset)
                holdings = [dict(h) for h in self.state.holdings]
                vibe = self.state.vibe
                dema = dict(self.state.dema_info)
            
            # 지수 정보 추출
            idx_str = ""
            for idx_name in ["KOSPI", "KOSDAQ"]:
                d = dema.get(idx_name, {})
                if d:
                    trend = "↑" if d.get('diff', 0) >= 0 else "↓"
                    idx_str += f" | {idx_name}{trend}"

            # 보유 종목 상세 요약 (Telegram 최적화 테이블 스타일)
            holdings_detail = ""
            if not holdings:
                holdings_detail = "🔹 현재 보유 종목이 없습니다."
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
                f"📊 <b>정기 시장 리포트 ({time_str})</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🌍 <b>시장 VIBE</b>: <code>{vibe}</code>{idx_str}\n"
                f"💰 <b>총 자산</b>: {int(asset.get('total_asset', 0)):,}원\n"
                f"{pnl_emoji} <b>당일 손익</b>: {int(pnl_amt):+,}원 ({pnl_rt:+.2f}%)\n"
                f"💵 <b>가용 현금</b>: {int(asset.get('cash', 0)):,}원\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📦 <b>보유 종목 상세 ({len(holdings)}개)</b>\n"
                f"{holdings_detail}"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"⏰ {datetime.now().strftime('%H:%M:%S')} 기준"
            )
            self.notifier.send_message(msg)
        except Exception as e:
            from src.logger import log_error
            log_error(f"Periodic Report Error: {e}")
            self.state.update_worker_status("REPORT", result="실패", last_task=f"리포트 생성 오류: {e}")
