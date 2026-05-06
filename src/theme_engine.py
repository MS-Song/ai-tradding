import os
import json
from typing import List, Dict

# 초기 폴백용 기본 키워드 (파일이 없을 때 사용)
THEME_KEYWORDS = {
    "반도체": ["반도체", "HBM", "DDR5", "하이닉스", "삼성전자", "한미반도체", "리노공업", "가온칩스", "CXL", "온디바이스"],
    "AI/로봇": ["AI", "인공지능", "로봇", "챗봇", "LLM", "엔비디아", "마음AI", "코난테크", "솔트룩스", "레인보우"],
    "이차전지": ["이차전지", "2차전지", "에코프로", "포스코", "리튬", "배터리", "전고체", "양극재", "음극재", "금양", "삼성SDI"],
    "바이오": ["바이오", "제약", "셀트리온", "HLB", "헬스케어", "알테오젠", "임상", "유한양행", "한미약품"],
    "자동차": ["자동차", "현대차", "기아", "현대모비스", "자율주행", "전기차"],
    "엔터/게임": ["엔터", "엔터테인먼트", "하이브", "JYP", "게임", "크래프톤", "넷마블", "네오위즈", "SM"],
    "금융/PBR": ["은행", "금융", "지주", "보험", "증권", "PBR", "밸류업", "KB금융", "하나금융"],
    "에너지/방산": ["에너지", "태양광", "풍력", "수소", "원자력", "원전", "방산", "한화에어로", "현대로템", "넥스원"],
    "가상화폐": ["비트코인", "가상화폐", "우리기술투자", "한화투자증권", "위메이드", "블록체인"],
    "초전도체": ["초전도체", "신성델타테크", "서남", "모비스", "덕성"]
}

THEME_DATA_FILE = "theme_data.json"
_dynamic_theme_map = {} # {theme_name: [{"name": stock_name, "code": stock_code}, ...]}
_code_to_theme_map = {} # {code: theme_name} (Reverse map for O(1) lookup)
_cached_themes = []

def load_theme_data():
    """파일에서 동적 테마 데이터를 로드"""
    global _dynamic_theme_map
    if os.path.exists(THEME_DATA_FILE):
        try:
            with open(THEME_DATA_FILE, "r", encoding="utf-8") as f:
                _dynamic_theme_map = json.load(f)
                _rebuild_reverse_map()
        except:
            _dynamic_theme_map = {}
            _code_to_theme_map = {}

# 모듈 로드 시 최초 1회 로드
load_theme_data()

# 제외하거나 후순위로 밀어낼 광범위한 테마명 (섹터 분류 등)
BROAD_THEMES = [
    "KOSPI200", "KOSDAQ150", "IT 대표주", "자동차 대표주", "금융지주", "은행", "대형주", "중형주", "소형주", 
    "코스피 200", "코스닥 150", "KOSPI", "KOSDAQ", "KRX300", "지주사", "코스피200건설", "철강 주요종목"
]

def _rebuild_reverse_map():
    """역방향 매핑 테이블 재구축 (O(1) 조회를 위함)"""
    global _code_to_theme_map
    new_map = {}
    
    # 1. 일반 테마 우선 할당 (테마가 여러 개인 종목은 첫 번째 테마로 분류)
    for theme, stocks in _dynamic_theme_map.items():
        if theme in BROAD_THEMES:
            continue
        for s in stocks:
            code = s.get('code')
            # 아직 테마가 할당되지 않은 경우에만 첫 번째 테마 적용
            if code and code not in new_map:
                new_map[code] = theme
                
    # 2. 광범위한 테마(BROAD_THEMES)는 일반 테마가 전혀 없는 종목에만 후순위 할당
    for theme, stocks in _dynamic_theme_map.items():
        if theme not in BROAD_THEMES:
            continue
        for s in stocks:
            code = s.get('code')
            if code and code not in new_map:
                new_map[code] = theme
                
    _code_to_theme_map = new_map

def get_theme_for_stock(code: str, name: str) -> str:
    # 0. 대표 종목명 직접 매칭 (가장 높은 우선순위: 삼성전자 등 대형주 테마 오염 방지)
    for theme, keywords in THEME_KEYWORDS.items():
        if name in keywords:
            return theme

    # 1. 동적 데이터베이스 검색 (역매핑 테이블 활용 - O(1))
    if code in _code_to_theme_map:
        return _code_to_theme_map[code]
            
    # 2. 폴백: 하드코딩된 키워드 검색
    for theme, keywords in THEME_KEYWORDS.items():
        if any(kw.lower() in name.lower() for kw in keywords):
            return theme
            
    # 3. ETF 판별 (기타로 분류되기 전 우선 체크)
    etf_keywords = ["ETF", "KODEX", "TIGER", "RISE", "ACE", "SOL", "HANARO", "KOSEF", "KBSTAR", "ARIRANG", "WOORI", "HANA", "PLUS"]
    if any(kw.lower() in name.upper() for kw in etf_keywords):
        return "ETF"

    return "기타"

def save_theme_data(theme_map: dict):
    """테마 데이터를 파일에 안전하게 저장 (Atomic Write)"""
    global _dynamic_theme_map
    _dynamic_theme_map = theme_map
    _rebuild_reverse_map()
    temp_file = THEME_DATA_FILE + ".tmp"
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(theme_map, f, ensure_ascii=False, indent=4)
        if os.path.exists(THEME_DATA_FILE): os.remove(THEME_DATA_FILE)
        os.rename(temp_file, THEME_DATA_FILE)
    except Exception as e:
        if os.path.exists(temp_file): os.remove(temp_file)

def analyze_popular_themes(hot_list, vol_list):
    global _cached_themes
    load_theme_data() # 분석 시마다 최신 데이터 로드
    
    counts = {}
    seen_codes = set()
    
    # 인기/거래량 통합 리스트 조사
    for item in hot_list + vol_list:
        code = item.get('code')
        if not code or code in seen_codes: continue
        seen_codes.add(code)
        
        theme = get_theme_for_stock(code, item.get('name', ''))
        counts[theme] = counts.get(theme, 0) + 1
                
    # 카운트가 있는 테마만 내림차순 정렬
    sorted_themes = sorted([{"name": k, "count": v} for k, v in counts.items() if v > 0], 
                           key=lambda x: x['count'], reverse=True)
    _cached_themes = sorted_themes
    return _cached_themes

def get_cached_themes():
    return _cached_themes
