import logging
import sys
import io
import os
import json
import threading
from datetime import datetime

# --- 1. 기본 로깅 설정 ---
def setup_logger(name="VibeTrader"):
    # 윈도우 터미널(win32) 한글 깨짐 방지
    if sys.platform == "win32":
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
        except:
            pass

    # 로거 생성
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    
    # 1. 일반 로그 포맷 (간결함 유지)
    default_formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-7s | %(message)s', 
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # 2. 에러 로그 포맷 (파일명:라인번호 포함하여 디버깅 용이성 강화)
    error_formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-7s | [%(filename)s:%(lineno)d] %(message)s', 
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 1. 거래 및 일반 로그 (ONLY INFO)
    trade_handler = logging.FileHandler("trading.log", encoding="utf-8", delay=True)
    trade_handler.setLevel(logging.INFO)
    # INFO 레벨만 허용하고 그 이상의 레벨(WARNING, ERROR)은 거르는 필터 추가
    class InfoOnlyFilter(logging.Filter):
        def filter(self, record):
            return record.levelno == logging.INFO
    trade_handler.addFilter(InfoOnlyFilter())
    trade_handler.setFormatter(default_formatter)

    # 2. 에러 전용 로그 (ERROR 이상)
    error_handler = logging.FileHandler("error.log", encoding="utf-8", delay=True)
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(error_formatter)

    if not logger.handlers:
        logger.addHandler(trade_handler)
        logger.addHandler(error_handler)
    
    return logger
        
# 3. 텔레그램 발송 로그 (별도 관리)
def setup_telegram_logger():
    logger = logging.getLogger("TelegramLog")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.FileHandler("telegram.log", encoding="utf-8", delay=True)
        handler.setFormatter(logging.Formatter('%(asctime)s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
        logger.addHandler(handler)
    return logger

logger = setup_logger()
telegram_logger = setup_telegram_logger()

# --- 2. 구조화된 JSON 로그 관리 (Spec: Group 2 반영) ---
class TradingLogManager:
    def __init__(self, log_file="trading_logs.json"):
        self.log_file = log_file
        self.data = {"trades": [], "configs": [], "rejections": [], "buy_reasons": [], "ai_activities": []}
        self.lock = threading.Lock()
        self.notifier = None  # [추가] 텔레그램 알림 엔진 연동
        self.state = None     # [추가] TUI 실시간 로그 연동용 state
        self.last_tui_msg = "" # [통합] 최근 생성된 TUI용 메시지
        self._load()

    def set_notifier(self, notifier):
        """[추가] 알림 엔진 연동을 위한 세터"""
        self.notifier = notifier

    def set_state(self, state):
        """[통합] TradingState 주입 (TUI 실시간 로그 자동 반영용)"""
        self.state = state

    def _load(self):
        with self.lock:
            if os.path.exists(self.log_file):
                try:
                    with open(self.log_file, "r", encoding="utf-8") as f:
                        self.data = json.load(f)
                    if "rejections" not in self.data: self.data["rejections"] = []
                    if "buy_reasons" not in self.data: self.data["buy_reasons"] = []
                    if "ai_activities" not in self.data: self.data["ai_activities"] = []
                except:
                    self.data = {"trades": [], "configs": [], "rejections": [], "buy_reasons": [], "ai_activities": []}

    def _save(self):
        """원자적 쓰기: tmp파일 기록 후 os.replace()로 교체 → 부분 쓰기 방지.
        메인 스레드 프리징을 방지하기 위해 데이터를 복사하여 별도 스레드에서 저장."""
        import copy
        with self.lock:
            data_to_save = copy.deepcopy(self.data)
            
        def _do(shared_data):
            import uuid
            import time
            tmp = f"{self.log_file}.{uuid.uuid4().hex[:8]}.tmp"
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(shared_data, f, indent=4, ensure_ascii=False)
                
                # Retry os.replace a few times for Windows lock issues
                for i in range(5):
                    try:
                        os.replace(tmp, self.log_file)
                        break
                    except OSError as oe:
                        if i == 4:
                            raise
                        time.sleep(0.1)
            except Exception as e:
                try: os.remove(tmp)
                except: pass
                log_error(f"TradingLog 저장 실패: {e}")
        
        threading.Thread(target=_do, args=(data_to_save,), daemon=True, name="LogSaveWorker").start()

    def log_trade(self, trade_type, code, name, price, qty, memo="", profit=0.0, model_id="", ma_20=0.0):
        """실제 체결 데이터를 기록 (TRADE). 매도 시 profit(수익금) 포함 가능"""
        try:
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # [Safety] NaN 또는 Inf 수익금 처리
            import math
            f_profit = float(profit)
            if not math.isfinite(f_profit):
                f_profit = 0.0
            
            f_price = float(price)
            if not math.isfinite(f_price):
                f_price = 0.0
            
            f_ma = float(ma_20)
            if not math.isfinite(f_ma):
                f_ma = 0.0

            log_entry = {
                "type": trade_type, 
                "time": now, 
                "code": code, 
                "name": name, 
                "price": f_price, 
                "qty": int(qty), 
                "memo": memo,
                "profit": f_profit,
                "model_id": model_id,
                "ma_20": f_ma
            }
            with self.lock:
                self.data["trades"].insert(0, log_entry) # 최신순
            self._save()
            
            # 텍스트 로그 파일에도 동시 기록 (stacklevel=2로 실제 호출 위치 기록)
            p_str = f" | 수익: {int(f_profit):+,}원" if f_profit != 0 else ""
            m_str = f" | 모델: {model_id}" if model_id else ""
            logger.info(f"[TRADE] {trade_type} | {name}({code}) | {int(f_price):,}원 | {qty}주 | {memo}{p_str}{m_str}", stacklevel=2)

            # [Phase 2] 텔레그램 및 TUI 로그 동시 기록
            if self.notifier:
                try:
                    self.notifier.notify_trade(trade_type, code, name, f_price, qty, memo, f_profit, model_id)
                except Exception as e:
                    log_error(f"Telegram Notification Error: {e}")

            # [통합] TUI 실시간 로그 자동 반영 (State 연동 시)
            if self.state:
                try:
                    tui_msg = self._build_tui_message(trade_type, name, qty, f_profit)
                    self.last_tui_msg = tui_msg
                    self.state.add_trading_log(tui_msg)
                except Exception as e:
                    log_error(f"TUI Log Update Error: {e}")
        except Exception as e:
            log_error(f"log_trade 기록 중 치명적 오류: {e}")

    def _build_tui_message(self, trade_type: str, name: str, qty: int, profit: float = 0.0) -> str:
        """[통합] 거래 데이터를 TUI용 한 줄 요약 메시지로 변환"""
        p_str = f" ({int(profit):+,}원)" if profit != 0 else ""
        
        # 타입별 아이콘 및 문구 매핑
        if "AI자율매수" in trade_type: return f"🚀 AI자율매수: {name} {qty}주"
        if "AI자율매도" in trade_type: return f"🤖 AI 자율 매도: {name}{p_str}"
        if "물타기" in trade_type:     return f"🤖 물타기: {name} {qty}주"
        if "불타기" in trade_type:     return f"🤖 불타기: {name} {qty}주"
        if "익절" in trade_type:       return f"자동 익절: {name} {qty}주"
        if "손절" in trade_type:       return f"자동 손절: {name} {qty}주"
        if "교체매도" in trade_type:   return f"🔄 교체매도: {name}{p_str}"
        if "P3" in trade_type:        return f"🏁 P3 수익확정: {name}{p_str}"
        if "P4" in trade_type:        return f"💤 P4 청산: {name}{p_str}"
        if "수동" in trade_type:      return f"✅ {trade_type}: {name} {qty}주"
        
        # 기본 형식
        return f"{trade_type}: {name} {qty}주{p_str}"
        

    def log_config(self, content):
        """환경 설정 및 전략 변경을 기록 (CONFIG)"""
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = {"time": now, "content": content}
        with self.lock:
            self.data["configs"].insert(0, log_entry) # 최신순
        self._save()
        logger.info(f"[CONFIG] {content}", stacklevel=2)

    def log_rejection(self, code, name, reason, model_id=""):
        """AI 매수 거절 내역을 기록 (REJECTION)"""
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = {
            "time": now,
            "code": code,
            "name": name,
            "reason": reason,
            "model_id": model_id
        }
        with self.lock:
            self.data["rejections"].insert(0, log_entry)
            # 최근 100건 정도만 유지 (너무 쌓이면 부담)
            if len(self.data["rejections"]) > 100:
                self.data["rejections"] = self.data["rejections"][:100]
        self._save()
        logger.info(f"[REJECT] {name}({code}) | 사유: {reason} | 모델: {model_id}", stacklevel=2)

    def log_buy_reason(self, code, name, reason, model_id=""):
        """AI 매수 승인 사유를 기록 (BUY_REASON)"""
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = {
            "time": now,
            "code": code,
            "name": name,
            "reason": reason,
            "model_id": model_id
        }
        with self.lock:
            self.data["buy_reasons"].insert(0, log_entry)
            if len(self.data["buy_reasons"]) > 100:
                self.data["buy_reasons"] = self.data["buy_reasons"][:100]
        self._save()
        logger.info(f"[BUY_REASON] {name}({code}) | 사유: {reason} | 모델: {model_id}", stacklevel=2)

    def log_ai_activity(self, category, content, result, remarks=""):
        """AI의 주기적 활동(시황분석, 매수검토 등)을 기록 (AI_ACTIVITY)"""
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = {
            "time": now,
            "category": category,
            "content": content,
            "result": result,
            "remarks": remarks
        }
        with self.lock:
            if "ai_activities" not in self.data: self.data["ai_activities"] = []
            self.data["ai_activities"].insert(0, log_entry)
            # 최근 200건 정도 유지
            if len(self.data["ai_activities"]) > 200:
                self.data["ai_activities"] = self.data["ai_activities"][:200]
        self._save()
        # [Architect] AI 활동 로그는 별도 UI(A키)가 있으므로 메인 로그(L키) 노이즈 방지를 위해 DEBUG로 기록
        logger.debug(f"[AI_ACT] {category} | {content} | {result} | {remarks}", stacklevel=2)

    def cleanup(self, days_to_keep=2):
        """영업일 기준 n일 로그만 남기고 삭제"""
        from src.utils import get_business_days_ago
        threshold_date = get_business_days_ago(days_to_keep).strftime('%Y-%m-%d')
        
        with self.lock:
            original_trade_count = len(self.data.get("trades", []))
            self.data["trades"] = [t for t in self.data.get("trades", []) if t["time"] >= threshold_date]
            self.data["configs"] = [c for c in self.data.get("configs", []) if c["time"] >= threshold_date]
            self.data["rejections"] = [r for r in self.data.get("rejections", []) if r["time"] >= threshold_date]
            self.data["buy_reasons"] = [b for b in self.data.get("buy_reasons", []) if b["time"] >= threshold_date]
            self.data["ai_activities"] = [a for a in self.data.get("ai_activities", []) if a["time"] >= threshold_date]
            
            if len(self.data["trades"]) != original_trade_count:
                # 내부에서 락이 걸린 상태이므로 _save 호출 시 주의 (이미 복사하므로 안전)
                pass # 아래에서 호출함
            else:
                return False

        self._save()
        return True

    def get_daily_profit(self):
        """금일 발생한 TRADE 로그 중 profit을 모두 합산 (요구사항 9)"""
        today = datetime.now().strftime('%Y-%m-%d')
        total_profit = 0.0
        with self.lock:
            for t in self.data.get("trades", []):
                if t["time"].startswith(today):
                    total_profit += t.get("profit", 0.0)
        return int(total_profit)

    def get_daily_amounts(self):
        """금일 발생한 BEAR, BULL, ALGO 트레이딩의 누적 집행 금액 합산 (요구사항 9)"""
        today = datetime.now().strftime('%Y-%m-%d')
        amounts = {"BEAR": 0, "BULL": 0, "ALGO": 0}
        with self.lock:
            for t in self.data.get("trades", []):
                if t["time"].startswith(today):
                    t_type = t.get("type", "")
                    amt = float(t.get("price", 0)) * int(t.get("qty", 0))
                    if "물타기" in t_type:
                        amounts["BEAR"] += amt
                    elif "불타기" in t_type:
                        amounts["BULL"] += amt
                    elif "AI자율매수" in t_type:
                        amounts["ALGO"] += amt
        return amounts

    def get_daily_trading_fees(self, fee_rate=0.00015, tax_rate=0.0018):
        """금일 발생한 거래에 대한 예상 수수료 및 세금 합산"""
        today = datetime.now().strftime('%Y-%m-%d')
        total_fees = 0.0
        with self.lock:
            for t in self.data.get("trades", []):
                if t["time"].startswith(today):
                    amt = float(t.get("price", 0)) * int(t.get("qty", 0))
                    t_type = t.get("type", "")
                    # 매수 시 수수료 (0.015% 가정)
                    if "매수" in t_type:
                        total_fees += amt * fee_rate
                    # 매도 시 수수료 + 세금 (0.195% 가정)
                    elif any(x in t_type for x in ["매도", "익절", "손절", "청산", "확정", "교체매도"]):
                        total_fees += amt * (fee_rate + tax_rate)
        return int(total_fees)

    def get_top_profitable_stocks(self, limit=10):
        """누적 수익금이 0원 초과인 상위 종목 집계 (모델별 상세 포함)"""
        stock_stats = {}
        with self.lock:
            for t in self.data.get("trades", []):
                code = t.get("code")
                if not code: continue
                if code not in stock_stats:
                    stock_stats[code] = {
                        "name": t.get("name", "Unknown"), 
                        "total_profit": 0.0, 
                        "count": 0, 
                        "models": {} # {model_name: {"profit": 0.0, "count": 0}}
                    }
                
                t_type = t.get("type", "")
                m_id = t.get("model_id", "")
                m_name = self._normalize_model_name(m_id, t_type)
                
                if m_name not in stock_stats[code]["models"]:
                    stock_stats[code]["models"][m_name] = {"profit": 0.0, "count": 0}
                
                stock_stats[code]["count"] += 1
                stock_stats[code]["models"][m_name]["count"] += 1
                
                if any(x in t_type for x in ["익절", "손절", "청산", "확정", "매도", "종료"]):
                    profit = t.get("profit", 0.0)
                    stock_stats[code]["total_profit"] += profit
                    stock_stats[code]["models"][m_name]["profit"] += profit
        
        # 수익금 순 정렬 및 0원 초과 필터링
        sorted_stats = sorted(stock_stats.items(), key=lambda x: x[1]["total_profit"], reverse=True)
        profitable = [s for s in sorted_stats if s[1]["total_profit"] > 0]
        return profitable[:limit]

    def get_top_loss_stocks(self, limit=10):
        """누적 손실금이 발생한 상위 종목 집계 (모델별 상세 포함)"""
        stock_stats = {}
        with self.lock:
            for t in self.data.get("trades", []):
                code = t.get("code")
                if not code: continue
                if code not in stock_stats:
                    stock_stats[code] = {
                        "name": t.get("name", "Unknown"), 
                        "total_profit": 0.0, 
                        "count": 0, 
                        "models": {} # {model_name: {"profit": 0.0, "count": 0}}
                    }
                
                t_type = t.get("type", "")
                m_id = t.get("model_id", "")
                m_name = self._normalize_model_name(m_id, t_type)
                
                if m_name not in stock_stats[code]["models"]:
                    stock_stats[code]["models"][m_name] = {"profit": 0.0, "count": 0}
                
                stock_stats[code]["count"] += 1
                stock_stats[code]["models"][m_name]["count"] += 1
                
                if any(x in t_type for x in ["익절", "손절", "청산", "확정", "매도", "종료"]):
                    profit = t.get("profit", 0.0)
                    stock_stats[code]["total_profit"] += profit
                    stock_stats[code]["models"][m_name]["profit"] += profit
        
        # 손실금 순(수익금 오름차순) 정렬 및 음수 필터링
        sorted_stats = sorted(stock_stats.items(), key=lambda x: x[1]["total_profit"], reverse=False)
        losses = [s for s in sorted_stats if s[1]["total_profit"] < 0]
        return losses[:limit]

    def _normalize_model_name(self, m_id: str, t_type: str = "") -> str:
        """모델 코드를 사람이 읽기 쉬운 약어로 정규화. 모델 정보가 없으면 타입을 통해 추론 시도."""
        if not m_id:
            # 과거 로그 호환: 타입을 보고 수동/TL/SP 추론
            t_low = t_type.lower()
            if any(x in t_low for x in ["수동", "manual"]): return "수동"
            if any(x in t_low for x in ["자동", "p3", "p4", "청산", "확정", "익절", "손절"]): return "TP/SL"
            return "TP/SL"
            
        m_id_low = m_id.lower()
        if m_id_low in ["manual", "수동", "수동매도", "수동매수"]: return "수동"
        if m_id_low in ["tl/sp", "auto", "logic", "tp/sl"]: return "TP/SL"
        
        if "gemini-3.1-pro" in m_id_low: return "G3.1P"
        if "gemini-3.1-flash-lite" in m_id_low: return "G3.1FL"
        if "gemini-3-flash" in m_id_low or "g3fp" in m_id_low: return "G3FP"
        if "gemini-2.5-flash-lite" in m_id_low: return "G2.5FL"
        if "gemini-2.5-flash" in m_id_low: return "G2.5F"
        if "gemini-2.1-flash-lite" in m_id_low: return "G2.1FL"
        return m_id[:8].upper()

    def get_model_performance(self):
        """모델별 승률 및 수익금 집계 ([Phase 4])"""
        model_stats = {}
        with self.lock:
            for t in self.data.get("trades", []):
                m_id = t.get("model_id", "")
                t_type = t.get("type", "")
                m_name = self._normalize_model_name(m_id, t_type)
                
                if m_name not in model_stats:
                    model_stats[m_name] = {"total_trades": 0, "wins": 0, "total_profit": 0.0, "buy_count": 0}
                
                if "매수" in t_type:
                    model_stats[m_name]["buy_count"] += 1
                elif any(x in t_type for x in ["익절", "손절", "청산", "확정", "매도", "종료"]):
                    model_stats[m_name]["total_trades"] += 1
                    profit = float(t.get("profit", 0.0))
                    model_stats[m_name]["total_profit"] += profit
                    if profit > 0:
                        model_stats[m_name]["wins"] += 1
        return model_stats

# 전역 인스턴스
trading_log = TradingLogManager()

def log_trade(msg):
    """구버전 호환용 (텍스트 로그만 남김)"""
    logger.info(f"[TRADE] {msg}", stacklevel=2)

def log_error(msg):
    """에러 관련 명시적 로그 (stacklevel=2 적용)"""
    logger.error(msg, stacklevel=2)

def cleanup_text_log(file_path, days_to_keep=2):
    """텍스트 로그 파일을 영업일 기준 n일치만 남기고 정리 (윈도우 파일 잠금 대응)"""
    from src.utils import get_business_days_ago
    import uuid
    import logging
    if not os.path.exists(file_path): return False
    
    threshold_date = get_business_days_ago(days_to_keep).strftime('%Y-%m-%d')
    cleaned = False
    
    tmp_path = f"{file_path}.{uuid.uuid4().hex[:6]}.tmp"
    try:
        # 1. 기존 파일 읽기
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        new_lines = []
        for line in lines:
            if len(line) >= 10:
                date_part = line[:10]
                if date_part >= threshold_date:
                    new_lines.append(line)
        
        if len(new_lines) == len(lines):
            return False

        # 2. 임시 파일에 기록
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
            
        # 3. 파일 교체 (Windows 대응: 해당 파일을 사용하는 핸들러를 찾아 잠시 닫음)
        target_abs = os.path.abspath(file_path)
        active_handlers = []
        
        # 메인 로거와 텔레그램 로거 모두 확인
        for log_obj in [logging.getLogger("VibeTrader"), logging.getLogger("TelegramLog")]:
            for h in log_obj.handlers[:]:
                if isinstance(h, logging.FileHandler) and os.path.abspath(h.baseFilename) == target_abs:
                    active_handlers.append((log_obj, h))
                    h.close()
                    log_obj.removeHandler(h)

        success = False
        try:
            os.replace(tmp_path, file_path)
            success = True
        except OSError as e:
            log_error(f"로그 교체 실패 ({file_path}): {e}")
        
        # 4. 핸들러 복구
        for log_obj, old_h in active_handlers:
            new_h = logging.FileHandler(old_h.baseFilename, encoding=old_h.encoding, delay=old_h.delay)
            new_h.setLevel(old_h.level)
            new_h.setFormatter(old_h.formatter)
            for f in old_h.filters:
                new_h.addFilter(f)
            log_obj.addHandler(new_h)

        if success:
            cleaned = True
                
    except Exception as e:
        log_error(f"로그 정리 중 예외 발생 ({file_path}): {e}")
    finally:
        if os.path.exists(tmp_path):
            try: os.remove(tmp_path)
            except: pass
    
    return cleaned
