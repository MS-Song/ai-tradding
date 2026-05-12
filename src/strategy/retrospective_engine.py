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
from src.utils import get_now



class RetrospectiveEngine:
    """매매 결과에 대한 사후 분석 및 복기를 담당하는 엔진입니다.

    매일 장 마감 후(16:00) 당일의 주요 매매(수익/손실 TOP 3)를 선별하여 심층 분석합니다. 
    AI 어드바이저를 통해 매매 타이밍의 적절성, 종목 선정 사유, 시황 대응력 등을 사후 
    평가하며, 최근 90일간의 복기 데이터를 JSON 형식으로 영속 보관합니다.

    Attributes:
        api: 시세 및 뉴스 수집을 위한 API 인스턴스.
        ai_advisor: 복기 분석 및 전략 평가를 수행할 AI Advisor.
        data (dict): 로드된 복기 리포트 및 누적 통계 데이터.
        DATA_FILE (str): 복기 데이터 저장 파일명 (`trade_retrospective.json`).
        RETENTION_DAYS (int): 리포트 최대 보관 기간 (90일).
    """
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
        """저장된 복기 데이터를 파일로부터 로드합니다. 파일이 없거나 손상된 경우 초기화합니다."""
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
        """데이터를 JSON 파일로 원자적(Atomic Write)으로 저장합니다.

        비동기 스레드를 생성하여 임시 파일 작성 후 교체하는 방식으로 
        데이터 손상을 방지합니다.
        """
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
        """보관 기간(90일)을 초과한 오래된 리포트를 식별하여 자동 삭제합니다."""
        cutoff = (get_now() - timedelta(days=self.RETENTION_DAYS)).strftime('%Y-%m-%d')
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
        """특정 날짜의 복기 리포트가 시스템에 이미 존재하는지 확인합니다.

        Args:
            date_str (str, optional): 확인할 날짜 (YYYY-MM-DD). 기본값은 오늘 날짜.

        Returns:
            bool: 존재 시 True, 미존재 시 False.
        """
        if not date_str:
            date_str = get_now().strftime('%Y-%m-%d')
        with self.lock:
            return date_str in self.data.get("reports", {})

    def get_daily_top_trades(self, date_str: str = None):
        """지정한 날짜에 발생한 매매 중 손익 금액 기준 상위 3개 종목(수익/손실 각각)을 선별합니다.

        동일 종목에 대해 여러 번의 매매가 발생한 경우 수익금을 합산하여 계산합니다.

        Args:
            date_str (str, optional): 분석 대상 날짜.

        Returns:
            Tuple[List, List]: (수익 상위 리스트, 손실 상위 리스트).
        """
        if not date_str:
            date_str = get_now().strftime('%Y-%m-%d')

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
        """당일 매매 복기 리포트를 최초 생성하고 AI 분석을 수행합니다.

        수익/손실 종목별로 시세 지표(PER/PBR) 및 뉴스 데이터를 보강한 뒤 
        AI에게 종합적인 사후 평가를 요청합니다.

        Args:
            date_str (str, optional): 리포트를 생성할 날짜.
            vibe (str): 당일의 시장 장세.

        Returns:
            dict: 생성된 리포트 상세 데이터. 매매 기록이 없으면 None.
        """
        if not date_str:
            date_str = get_now().strftime('%Y-%m-%d')

        top_profits, top_losses = self.get_daily_top_trades(date_str)

        if not top_profits and not top_losses:
            return None  # 매매 기록이 없으면 리포트 생성 불가

        # 종목별 현재가 및 뉴스 수집 (장 마감 후이므로 종가 기준)
        analyzed_profits = [self._enrich_stock_data(s) for s in top_profits]
        analyzed_losses = [self._enrich_stock_data(s) for s in top_losses]

        # AI 분석 요청
        ai_analysis = None
        if self.ai_advisor:
            ai_analysis = self._request_ai_analysis(
                date_str, vibe, analyzed_profits, analyzed_losses
            )

        # 리포트 생성
        report = {
            "generated_at": get_now().strftime('%Y-%m-%d %H:%M:%S'),
            "updated_at": get_now().strftime('%Y-%m-%d %H:%M:%S'),
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
        """기존 생성된 리포트에 장 마감 후의 정산 시세 및 뉴스를 추가하여 분석을 업데이트합니다.

        워커를 통해 주기적으로 호출되어 AI 분석의 완성도를 높입니다.

        Args:
            date_str (str, optional): 업데이트할 리포트의 날짜.
            vibe (str): 현재 시장 장세.

        Returns:
            dict: 업데이트가 완료된 리포트 데이터.
        """
        if not date_str:
            date_str = get_now().strftime('%Y-%m-%d')

        with self.lock:
            existing = self.data.get("reports", {}).get(date_str)

        if not existing:
            return self.generate_daily_report(date_str, vibe)

        # 기존 리포트의 종목 데이터 갱신 (최신 뉴스 등)
        for stock in existing.get("top_profits", []):
            updated = self._enrich_stock_data(stock)
            stock.update({"closing_price": updated.get("closing_price"), "latest_news": updated.get("latest_news")})

        for stock in existing.get("top_losses", []):
            updated = self._enrich_stock_data(stock)
            stock.update({"closing_price": updated.get("closing_price"), "latest_news": updated.get("latest_news")})

        # AI 재분석 (최종 데이터 기반)
        if self.ai_advisor:
            ai_analysis = self._request_ai_analysis(
                date_str, vibe, existing.get("top_profits", []), existing.get("top_losses", []), is_update=True
            )
            existing["ai_analysis"] = ai_analysis

        existing["updated_at"] = get_now().strftime('%Y-%m-%d %H:%M:%S')
        existing["update_count"] = existing.get("update_count", 1) + 1

        with self.lock:
            self.data["reports"][date_str] = existing
        self._save()

        return existing

    def _enrich_stock_data(self, stock_data: dict) -> dict:
        """종목의 펀더멘털 지표(PER/PBR) 및 실시간 뉴스를 수집하여 데이터를 보강합니다."""
        code = stock_data.get("code", "")
        result = dict(stock_data)

        if self.api and code:
            try:
                detail = self.api.get_naver_stock_detail(code)
                news = self.api.get_naver_stock_news(code)
                result.update({
                    "closing_price": float(detail.get("price", 0)),
                    "per": detail.get("per", "N/A"),
                    "pbr": detail.get("pbr", "N/A"),
                    "day_rate": detail.get("rate", 0),
                    "latest_news": news[:3] if news else []
                })
            except Exception as e:
                log_error(f"종목 부가 정보 수집 실패 ({code}): {e}")
                result.update({"closing_price": 0, "latest_news": []})

        return result

    def _request_ai_analysis(self, date_str, vibe, profits, losses, is_update=False):
        """AI Advisor에게 매매 복기 심층 분석을 요청합니다."""
        if not self.ai_advisor: return None
        try:
            res = self.ai_advisor.analyze_trade_retrospective(date_str, vibe, profits, losses, is_update=is_update)
            return res.replace("**", "") if res else res # TUI 가시성 위해 볼드 제거
        except Exception as e:
            log_error(f"AI 복기 분석 요청 실패: {e}")
            return None

    def get_reports(self, limit: int = 7) -> list:
        """최근 저장된 리포트 목록을 내림차순으로 조회합니다.

        Args:
            limit (int): 조회할 최대 리포트 개수.

        Returns:
            list: [(날짜, 리포트데이터), ...] 형태의 리스트.
        """
        with self.lock:
            reports = self.data.get("reports", {})
        sorted_keys = sorted(reports.keys(), reverse=True)[:limit]
        return [(k, reports[k]) for k in sorted_keys]

    def get_report(self, date_str: str = None) -> dict:
        """특정 날짜의 복기 리포트 상세 데이터를 조회합니다."""
        if not date_str: date_str = get_now().strftime('%Y-%m-%d')
        with self.lock: return self.data.get("reports", {}).get(date_str)

    def get_cumulative_stats(self) -> dict:
        """보관 중인 전체 기간에 대한 누적 투자 성과 통계를 산출합니다.

        Returns:
            dict: 총 분석 일수, 승률, 총 손익, 평균 수익/손실 등 통계 정보.
        """
        with self.lock:
            reports = self.data.get("reports", {})

        total_days = len(reports)
        p_trades, l_trades, p_amt, l_amt = 0, 0, 0.0, 0.0

        for r in reports.values():
            for s in r.get("top_profits", []):
                p_trades += 1; p_amt += s.get("total_profit", 0)
            for s in r.get("top_losses", []):
                l_trades += 1; l_amt += s.get("total_profit", 0)

        total_trades = p_trades + l_trades
        win_rate = (p_trades / total_trades * 100) if total_trades > 0 else 0

        return {
            "total_days": total_days, "total_trades": total_trades, "win_rate": win_rate,
            "total_profit": p_amt, "total_loss": l_amt, "net_profit": p_amt + l_amt,
            "avg_profit": p_amt / p_trades if p_trades > 0 else 0,
            "avg_loss": l_amt / l_trades if l_trades > 0 else 0
        }

