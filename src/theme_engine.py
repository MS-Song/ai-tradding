THEME_KEYWORDS = {
    "반도체": ["반도체", "HBM", "DDR5", "하이닉스", "삼성전자", "한미반도체", "리노공업", "가온칩스", "CXL", "온디바이스"],
    "AI/로봇": ["AI", "인공지능", "로봇", "챗봇", "LLM", "엔비디아", "마음AI", "코난테크", "솔트룩스", "레인보우"],
    "이차전지": ["이차전지", "2차전지", "에코프로", "포스코", "리튬", "배터리", "전고체", "양극재", "음극재", "금양"],
    "바이오": ["바이오", "제약", "셀트리온", "HLB", "헬스케어", "알테오젠", "임상", "유한양행", "한미약품"],
    "엔터/게임": ["엔터", "엔터테인먼트", "하이브", "JYP", "게임", "크래프톤", "넷마블", "네오위즈", "SM"],
    "금융/PBR": ["은행", "금융", "지주", "보험", "증권", "PBR", "밸류업", "KB금융", "하나금융"],
    "에너지/방산": ["에너지", "태양광", "풍력", "수소", "원자력", "원전", "방산", "한화에어로", "현대로템", "넥스원"],
    "가상화폐": ["비트코인", "가상화폐", "우리기술투자", "한화투자증권", "위메이드", "블록체인"],
    "초전도체": ["초전도체", "신성델타테크", "서남", "모비스", "덕성"]
}

_cached_themes = []

def analyze_popular_themes(hot_list, vol_list):
    global _cached_themes
    counts = {k: 0 for k in THEME_KEYWORDS.keys()}
    seen_codes = set()
    
    # 인기/거래량 통합 리스트 조사
    for item in hot_list + vol_list:
        code = item.get('code')
        if code in seen_codes: continue
        seen_codes.add(code)
        
        name = item.get('name', '')
        for theme, keywords in THEME_KEYWORDS.items():
            if any(kw.lower() in name.lower() for kw in keywords):
                counts[theme] += 1
                break # 한 종목당 하나의 테마만 매핑 (우선순위)
                
    # 카운트가 있는 테마만 내림차순 정렬
    sorted_themes = sorted([{"name": k, "count": v} for k, v in counts.items() if v > 0], 
                           key=lambda x: x['count'], reverse=True)
    _cached_themes = sorted_themes
    return _cached_themes

def get_cached_themes():
    return _cached_themes
