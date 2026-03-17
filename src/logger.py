import logging
import sys
import io
import os

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

def log_trade(msg):
    """거래 관련 명시적 로그 (별도 처리가 필요한 경우를 대비)"""
    logger.info(f"[TRADE] {msg}")

def log_error(msg):
    """에러 관련 명시적 로그"""
    logger.error(msg)
