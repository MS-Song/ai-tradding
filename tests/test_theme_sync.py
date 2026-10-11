import pytest
from unittest.mock import MagicMock, patch
from src.api.naver import NaverAPIClient
from src.theme_engine import save_theme_data, get_theme_for_stock, load_theme_data, _code_to_theme_map, _dynamic_theme_map

def test_theme_data_load_order():
    """모듈 로드 시 BROAD_THEMES가 정의되어 있어 load_theme_data 호출 시 NameError가 발생하지 않는지 검증합니다."""
    # load_theme_data 호출 시 예외 없이 실행되어야 함
    load_theme_data()
    assert isinstance(_dynamic_theme_map, dict)
    assert isinstance(_code_to_theme_map, dict)

def test_get_naver_theme_data_parsing():
    """NaverAPIClient.get_naver_theme_data가 네이버 모바일 API 응답 형식을 올바르게 파싱하는지 검증합니다."""
    client = NaverAPIClient()
    
    mock_groups_response = {
        "groups": [
            {"no": 101, "name": "인공지능(AI)", "totalCount": 2},
            {"no": 102, "name": "로봇(산업용/협동로봇)", "totalCount": 1}
        ],
        "totalCount": 2,
        "page": 1,
        "pageSize": 100
    }
    
    mock_detail_101 = {
        "stocks": [
            {"stockName": "솔트룩스", "itemCode": "304100"},
            {"stockName": "마음AI", "itemCode": "377480"}
        ],
        "totalCount": 2
    }
    mock_detail_102 = {
        "stocks": [
            {"stockName": "레인보우로보틱스", "itemCode": "277810"}
        ],
        "totalCount": 1
    }

    def mock_get(url, *args, **kwargs):
        res = MagicMock()
        res.status_code = 200
        if "stocks/theme?" in url:
            if "page=1" in url:
                res.json.return_value = mock_groups_response
            else:
                res.json.return_value = {"groups": [], "totalCount": 2}
        elif "stocks/theme/101" in url:
            res.json.return_value = mock_detail_101
        elif "stocks/theme/102" in url:
            res.json.return_value = mock_detail_102
        else:
            res.status_code = 404
        return res

    with patch.object(client._session, 'get', side_effect=mock_get):
        theme_map = client.get_naver_theme_data()
        assert len(theme_map) == 2
        assert "인공지능(AI)" in theme_map
        assert len(theme_map["인공지능(AI)"]) == 2
        assert theme_map["인공지능(AI)"][0] == {"name": "솔트룩스", "code": "304100"}
        assert "로봇(산업용/협동로봇)" in theme_map
        assert theme_map["로봇(산업용/협동로봇)"][0] == {"name": "레인보우로보틱스", "code": "277810"}

def test_theme_mapping_and_lookup():
    """테마 데이터 저장 및 종목 코드 기반 테마 역방향 매핑 검증."""
    sample_data = {
        "자율주행": [
            {"name": "현대오토에버", "code": "307950"},
            {"name": "모트렉스", "code": "118990"}
        ]
    }
    save_theme_data(sample_data)
    
    # 현대오토에버 검색
    theme = get_theme_for_stock("307950", "현대오토에버")
    assert theme == "자율주행"
