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
_cached_themes = []

def load_theme_data():
    """파일에서 동적 테마 데이터를 로드"""
    global _dynamic_theme_map
    if os.path.exists(THEME_DATA_FILE):
        try:
            with open(THEME_DATA_FILE, "r", encoding="utf-8") as f:
                _dynamic_theme_map = json.load(f)
        except:
            _dynamic_theme_map = {}

# 모듈 로드 시 최초 1회 로드
load_theme_data()

# 제외하거나 후순위로 밀어낼 광범위한 테마명 (섹터 분류 등)
BROAD_THEMES = ["KOSPI200", "KOSDAQ150", "IT 대표주", "자동차 대표주", "금융지주", "은행", "대형주", "중형주", "소형주", "코스피 200", "코스닥 150"]

def get_theme_for_stock(code: str, name: str) -> str:
    """종목 코드 또는 이름을 기반으로 테마명을 반환 (동적 데이터 우선)"""
    candidate_themes = []
    
    # 1. 동적 데이터베이스 검색
    for theme, stocks in _dynamic_theme_map.items():
        if any(s['code'] == code for s in stocks):
            candidate_themes.append(theme)
            
    if candidate_themes:
        # 광범위한 테마보다 구체적인 테마 우선 (예: 'IT 대표주'보다 '2차전지' 선호)
        specific_themes = [t for t in candidate_themes if t not in BROAD_THEMES]
        if specific_themes: 
            # 2차전지나 자동차 키워드가 포함된 구체적 테마를 더 선호
            priority_themes = [t for t in specific_themes if any(kw in t for kw in ["전지", "자동차", "반도체", "로봇", "AI", "바이오"])]
            if priority_themes: return priority_themes[0]
            return specific_themes[0]
        return candidate_themes[0]
            
    # 2. 폴백: 하드코딩된 키워드 검색
    for theme, keywords in THEME_KEYWORDS.items():
        if any(kw.lower() in name.lower() for kw in keywords):
            return theme
            
    return "기타"

def save_theme_data(theme_map: dict):
    """테마 데이터를 파일에 안전하게 저장 (Atomic Write)"""
    global _dynamic_theme_map
    _dynamic_theme_map = theme_map
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
