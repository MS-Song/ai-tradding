import logging
import sys
import io

# 윈도우 터미널(win32) 한글 깨짐 방지: 표준 출력을 UTF-8로 재설정
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        # Python 3.7 미만 버전 대응
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def setup_logger(name="VibeTrader"):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    # Clean Logs 원칙 적용
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-7s | %(message)s', 
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    
    if not logger.handlers:
        logger.addHandler(console_handler)
        
    return logger

logger = setup_logger()
