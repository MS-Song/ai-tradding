import logging
import sys
import io

def setup_logger(name="VibeTrader"):
    # 윈도우 터미널(win32) 한글 깨짐 방지: 표준 출력을 UTF-8로 강제 설정
    if sys.platform == "win32":
        try:
            # 윈도우 코드 페이지를 65001(UTF-8)로 변경하는 효과
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
        except:
            pass

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    # Clean Logs 원칙 적용 (날짜와 레벨만 깔끔하게 출력)
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-7s | %(message)s', 
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # 터미널 핸들러 설정
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    
    if not logger.handlers:
        logger.addHandler(console_handler)
        
    return logger

logger = setup_logger()
