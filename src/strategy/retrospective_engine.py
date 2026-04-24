"""
투자 적중 복기 엔진 (Trade Retrospective Engine)
- 매일 장 마감 후(16:00) 당일 수익/손실 TOP 3 종목을 AI가 분석하여 복기
- 30분 단위로 사후 분석 업데이트 (최종 가격 + 뉴스 기반)
- 누적 보관: 최근 3개월(90일)간 데이터를 보관, 초과 시 자동 정리
"""
import json
import os
import threading
import time
from datetime import datetime, timedelta
from src.logger import log_error, trading_log


class RetrospectiveEngine:
    DATA_FILE = "trade_retrospective.json"
    RETENTION_DAYS = 90  # 3개월(90일) 보관

    def __init__(self, api=None, ai_advisor=None):
        self.api = api
        self.ai_advisor = ai_advisor
        self.lock = threading.Lock()
        self.data = {"reports": {}}
        self._load()
        self._cleanup_old_reports()

    def _load(self):
        with self.lock:
            if os.path.exists(self.DATA_FILE):
                try:
                    with open(self.DATA_FILE, "r", encoding="utf-8") as f:
                        self.data = json.load(f)
                    if "reports" not in self.data:
                        self.data["reports"] = {}
                except Exception as e:
                    log_error(f"투자 적중 데이터 로드 실패: {e}")
                    self.data = {"reports": {}}

    def _save(self):
        """원자적 쓰기: 데이터 손실 방지"""
        import copy
        import uuid

        with self.lock:
            data_to_save = copy.deepcopy(self.data)

        def _do(shared_data):
            tmp = f"{self.DATA_FILE}.{uuid.uuid4().hex[:8]}.tmp"
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(shared_data, f, indent=2, ensure_ascii=False)
                for i in range(5):
                    try:
                        os.replace(tmp, self.DATA_FILE)
                        break
                    except OSError:
                        if i == 4:
                            raise
                        time.sleep(0.1)
            except Exception as e:
                try:
                    os.remove(tmp)
                except:
                    pass
                log_error(f"투자 적중 데이터 저장 실패: {e}")

        threading.Thread(target=_do, args=(data_to_save,), daemon=True).start()

    def _cleanup_old_reports(self):
        """3개월(90일) 초과 리포트를 자동 삭제하여 파일 크기를 관리합니다."""
        cutoff = (datetime.now() - timedelta(days=self.RETENTION_DAYS)).strftime('%Y-%m-%d')
        removed = []
        with self.lock:
            keys_to_remove = [k for k in self.data.get("reports", {}) if k < cutoff]
            for k in keys_to_remove:
                del self.data["reports"][k]
                removed.append(k)
        if removed:
            self._save()
            from src.logger import logger
            logger.info(f"🗂️ 투자 적중 복기: {len(removed)}건의 오래된 리포트 정리 (기준: {cutoff} 이전)")

    def has_daily_report(self, date_str: str = None) -> bool:
        """해당 날짜의 복기 리포트가 이미 생성되었는지 확인"""
        if not date_str:
            date_str = datetime.now().strftime('%Y-%m-%d')
        with self.lock:
            return date_str in self.data.get("reports", {})

    def get_daily_top_trades(self, date_str: str = None):
        """
        당일 수익/손실 상위 3개 매매를 추출합니다.
        Returns: (top_profits: list, top_losses: list)
        """
        if not date_str:
            date_str = datetime.now().strftime('%Y-%m-%d')

        sell_types = ["익절", "손절", "청산", "확정", "매도", "종료"]
        trades_with_profit = []

        with trading_log.lock:
            for t in trading_log.data.get("trades", []):
                if not t["time"].startswith(date_str):
                    continue
                t_type = t.get("type", "")
                profit = t.get("profit", 0.0)
                # 수익/손실이 발생한 매도 거래만 수집
                if any(x in t_type for x in sell_types) and profit != 0.0:
                    trades_with_profit.append({
                        "code": t.get("code", ""),
                        "name": t.get("name", "Unknown"),
                        "type": t_type,
                        "profit": float(profit),
                        "price": float(t.get("price", 0)),
                        "qty": int(t.get("qty", 0)),
                        "time": t.get("time", ""),
                        "memo": t.get("memo", ""),
                        "model_id": t.get("model_id", "")
                    })

        # 같은 종목의 거래를 합산
        stock_summary = {}
        for t in trades_with_profit:
            code = t["code"]
            if code not in stock_summary:
                stock_summary[code] = {
                    "code": code,
                    "name": t["name"],
                    "total_profit": 0.0,
                    "trades": [],
                    "last_sell_type": t["type"],
                    "last_memo": t["memo"],
                    "last_model": t["model_id"]
                }
            stock_summary[code]["total_profit"] += t["profit"]
            stock_summary[code]["trades"].append(t)

        all_stocks = list(stock_summary.values())

        # 수익 상위 3개 (profit > 0, 내림차순)
        top_profits = sorted(
            [s for s in all_stocks if s["total_profit"] > 0],
            key=lambda x: x["total_profit"],
            reverse=True
        )[:3]

        # 손실 상위 3개 (profit < 0, 오름차순)
        top_losses = sorted(
            [s for s in all_stocks if s["total_profit"] < 0],
            key=lambda x: x["total_profit"]
        )[:3]

        return top_profits, top_losses

    def generate_daily_report(self, date_str: str = None, vibe: str = "Neutral"):
        """
        당일 매매 복기 리포트를 AI 분석을 통해 생성합니다.
        - 수익 TOP 3 / 손실 TOP 3 종목의 매매 사유 분석
        - 장 마감 후 최종 가격과 뉴스를 기반으로 결정의 적절성 평가
        """
        if not date_str:
            date_str = datetime.now().strftime('%Y-%m-%d')

        top_profits, top_losses = self.get_daily_top_trades(date_str)

        if not top_profits and not top_losses:
            return None  # 매매 기록이 없으면 리포트 생성 불가

        # 종목별 현재가 및 뉴스 수집 (장 마감 후이므로 종가 기준)
        analyzed_profits = []
        for s in top_profits:
            info = self._enrich_stock_data(s)
            analyzed_profits.append(info)

        analyzed_losses = []
        for s in top_losses:
            info = self._enrich_stock_data(s)
            analyzed_losses.append(info)

        # AI 분석 요청
        ai_analysis = None
        if self.ai_advisor:
            ai_analysis = self._request_ai_analysis(
                date_str, vibe, analyzed_profits, analyzed_losses
            )

        # 리포트 생성
        report = {
            "generated_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "updated_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "market_vibe": vibe,
            "top_profits": analyzed_profits,
            "top_losses": analyzed_losses,
            "ai_analysis": ai_analysis,
            "update_count": 1
        }

        with self.lock:
            self.data["reports"][date_str] = report
        self._save()

        return report

    def update_post_market_analysis(self, date_str: str = None, vibe: str = "Neutral"):
        """
        30분 단위로 호출되어 기존 리포트에 사후 분석을 업데이트합니다.
        - 최종 종가 반영
        - 뉴스 업데이트
        - AI 재분석 (매매 결정이 맞았는지 평가)
        """
        if not date_str:
            date_str = datetime.now().strftime('%Y-%m-%d')

        with self.lock:
            existing = self.data.get("reports", {}).get(date_str)

        if not existing:
            return self.generate_daily_report(date_str, vibe)

        # 기존 리포트의 종목 데이터 갱신
        for stock in existing.get("top_profits", []):
            updated = self._enrich_stock_data(stock)
            stock.update({
                "closing_price": updated.get("closing_price"),
                "latest_news": updated.get("latest_news")
            })

        for stock in existing.get("top_losses", []):
            updated = self._enrich_stock_data(stock)
            stock.update({
                "closing_price": updated.get("closing_price"),
                "latest_news": updated.get("latest_news")
            })

        # AI 재분석 (종가 반영)
        if self.ai_advisor:
            ai_analysis = self._request_ai_analysis(
                date_str, vibe,
                existing.get("top_profits", []),
                existing.get("top_losses", []),
                is_update=True
            )
            existing["ai_analysis"] = ai_analysis

        existing["updated_at"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        existing["update_count"] = existing.get("update_count", 1) + 1

        with self.lock:
            self.data["reports"][date_str] = existing
        self._save()

        return existing

    def _enrich_stock_data(self, stock_data: dict) -> dict:
        """종목의 현재가/뉴스 등 부가 정보를 수집하여 반환"""
        code = stock_data.get("code", "")
        result = dict(stock_data)  # 기존 데이터 복사

        if self.api and code:
            try:
                detail = self.api.get_naver_stock_detail(code)
                news = self.api.get_naver_stock_news(code)
                result["closing_price"] = float(detail.get("price", 0))
                result["per"] = detail.get("per", "N/A")
                result["pbr"] = detail.get("pbr", "N/A")
                result["day_rate"] = detail.get("rate", 0)
                result["latest_news"] = news[:3] if news else []
            except Exception as e:
                log_error(f"종목 부가 정보 수집 실패 ({code}): {e}")
                result["closing_price"] = 0
                result["latest_news"] = []

        return result

    def _request_ai_analysis(self, date_str, vibe, profits, losses, is_update=False):
        """AI에게 매매 복기 분석을 요청합니다."""
        if not self.ai_advisor:
            return None

        try:
            res = self.ai_advisor.analyze_trade_retrospective(
                date_str, vibe, profits, losses, is_update=is_update
            )
            if res:
                # TUI 가독성을 위해 마크다운 볼드체(**) 제거
                res = res.replace("**", "")
            return res
        except Exception as e:
            log_error(f"AI 복기 분석 요청 실패: {e}")
            return None

    def get_reports(self, limit: int = 7) -> list:
        """최근 N일간의 리포트를 날짜 내림차순으로 반환"""
        with self.lock:
            reports = self.data.get("reports", {})
        sorted_keys = sorted(reports.keys(), reverse=True)[:limit]
        return [(k, reports[k]) for k in sorted_keys]

    def get_report(self, date_str: str = None) -> dict:
        """특정 날짜의 리포트 반환"""
        if not date_str:
            date_str = datetime.now().strftime('%Y-%m-%d')
        with self.lock:
            return self.data.get("reports", {}).get(date_str)

    def get_cumulative_stats(self) -> dict:
        """누적 통계 (전체 승률, 평균 수익/손실 등) 계산"""
        with self.lock:
            reports = self.data.get("reports", {})

        total_days = len(reports)
        total_profit_trades = 0
        total_loss_trades = 0
        total_profit_amount = 0
        total_loss_amount = 0

        for date_str, report in reports.items():
            for s in report.get("top_profits", []):
                total_profit_trades += 1
                total_profit_amount += s.get("total_profit", 0)
            for s in report.get("top_losses", []):
                total_loss_trades += 1
                total_loss_amount += s.get("total_profit", 0)

        total_trades = total_profit_trades + total_loss_trades
        win_rate = (total_profit_trades / total_trades * 100) if total_trades > 0 else 0

        return {
            "total_days": total_days,
            "total_trades": total_trades,
            "win_rate": win_rate,
            "total_profit": total_profit_amount,
            "total_loss": total_loss_amount,
            "net_profit": total_profit_amount + total_loss_amount,
            "avg_profit": total_profit_amount / total_profit_trades if total_profit_trades > 0 else 0,
            "avg_loss": total_loss_amount / total_loss_trades if total_loss_trades > 0 else 0
        }
