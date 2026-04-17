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
    
    # 포맷 설정
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-7s | %(message)s', 
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 1. 거래 및 일반 로그 (ONLY INFO)
    trade_handler = logging.FileHandler("trading.log", encoding="utf-8")
    trade_handler.setLevel(logging.INFO)
    # INFO 레벨만 허용하고 그 이상의 레벨(WARNING, ERROR)은 거르는 필터 추가
    class InfoOnlyFilter(logging.Filter):
        def filter(self, record):
            return record.levelno == logging.INFO
    trade_handler.addFilter(InfoOnlyFilter())
    trade_handler.setFormatter(formatter)

    # 2. 에러 전용 로그 (ERROR 이상)
    error_handler = logging.FileHandler("error.log", encoding="utf-8")
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)

    if not logger.handlers:
        logger.addHandler(trade_handler)
        logger.addHandler(error_handler)
        
    return logger

logger = setup_logger()

# --- 2. 구조화된 JSON 로그 관리 (Spec: Group 2 반영) ---
class TradingLogManager:
    def __init__(self, log_file="trading_logs.json"):
        self.log_file = log_file
        self.data = {"trades": [], "configs": []}
        self.lock = threading.Lock()
        self._load()

    def _load(self):
        with self.lock:
            if os.path.exists(self.log_file):
                try:
                    with open(self.log_file, "r", encoding="utf-8") as f:
                        self.data = json.load(f)
                except:
                    self.data = {"trades": [], "configs": []}

    def _save(self):
        """원자적 쓰기: tmp파일 기록 후 os.replace()로 교체 → 부분 쓰기 방지.
        메인 스레드 프리징을 방지하기 위해 데이터를 복사하여 별도 스레드에서 저장."""
        import copy
        with self.lock:
            data_to_save = copy.deepcopy(self.data)
            
        def _do(shared_data):
            import uuid
            tmp = f"{self.log_file}.{uuid.uuid4().hex[:8]}.tmp"
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(shared_data, f, indent=4, ensure_ascii=False)
                os.replace(tmp, self.log_file)
            except Exception as e:
                try: os.remove(tmp)
                except: pass
                log_error(f"TradingLog 저장 실패: {e}")
        
        threading.Thread(target=_do, args=(data_to_save,), daemon=True, name="LogSaveWorker").start()

    def log_trade(self, trade_type, code, name, price, qty, memo="", profit=0.0):
        """실제 체결 데이터를 기록 (TRADE). 매도 시 profit(수익금) 포함 가능"""
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = {
            "type": trade_type, 
            "time": now, 
            "code": code, 
            "name": name, 
            "price": float(price), 
            "qty": int(qty), 
            "memo": memo,
            "profit": float(profit)
        }
        with self.lock:
            self.data["trades"].insert(0, log_entry) # 최신순
        self._save()
        
        # 텍스트 로그 파일에도 동시 기록
        p_str = f" | 수익: {int(profit):+,}원" if profit != 0 else ""
        logger.info(f"[TRADE] {trade_type} | {name}({code}) | {int(price):,}원 | {qty}주 | {memo}{p_str}")

    def log_config(self, content):
        """환경 설정 및 전략 변경을 기록 (CONFIG)"""
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = {"time": now, "content": content}
        with self.lock:
            self.data["configs"].insert(0, log_entry) # 최신순
        self._save()
        logger.info(f"[CONFIG] {content}")

    def cleanup(self, days_to_keep=2):
        """영업일 기준 n일 로그만 남기고 삭제"""
        from src.utils import get_business_days_ago
        threshold_date = get_business_days_ago(days_to_keep).strftime('%Y-%m-%d')
        
        with self.lock:
            original_trade_count = len(self.data.get("trades", []))
            self.data["trades"] = [t for t in self.data.get("trades", []) if t["time"] >= threshold_date]
            self.data["configs"] = [c for c in self.data.get("configs", []) if c["time"] >= threshold_date]
            
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

# 전역 인스턴스
trading_log = TradingLogManager()

def log_trade(msg):
    """구버전 호환용 (텍스트 로그만 남김)"""
    logger.info(f"[TRADE] {msg}")

def log_error(msg):
    """에러 관련 명시적 로그"""
    logger.error(msg)

def cleanup_text_log(file_path, days_to_keep=2):
    """텍스트 로그 파일을 영업일 기준 n일치만 남기고 정리"""
    from src.utils import get_business_days_ago
    if not os.path.exists(file_path): return False
    
    threshold_date = get_business_days_ago(days_to_keep).strftime('%Y-%m-%d')
    cleaned = False
    
    try:
        # FileHandler가 파일을 잡고 있을 수 있으므로 주의해서 처리
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        new_lines = []
        for line in lines:
            if len(line) >= 10:
                date_part = line[:10]
                if date_part >= threshold_date:
                    new_lines.append(line)
        
        if len(new_lines) != len(lines):
            with open(file_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            cleaned = True
    except Exception as e:
        log_error(f"로그 정리 실패 ({file_path}): {e}")
    
    return cleaned
