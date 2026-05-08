from typing import List, Optional

class ChartRenderer:
    """터미널 환경에서 아스키/ANSI 코드를 사용하여 캔들 차트를 시각화하는 클래스.
    
    데이터 정규화를 통해 정해진 높이 내에 가격 범위를 매핑하고, 
    상승/하락 여부에 따른 색상(ANSI Escape Code)과 캔들 구성 요소(Wick, Body)를 표현합니다.
    """

    @staticmethod
    def render_candle_chart(candles: List[dict], width: int = 30, height: int = 12, title: str = "") -> str:
        """캔들 데이터를 받아 터미널용 텍스트 기반 차트 문자열을 생성합니다.

        Args:
            candles (List[dict]): KIS API `output2` 형식의 캔들 리스트 (0번 인덱스가 최신).
            width (int, optional): 차트의 가로 너비(캔들 개수). 기본값 30.
            height (int, optional): 차트의 세로 높이(줄 수). 기본값 12.
            title (str, optional): 차트 상단에 표시할 제목.

        Returns:
            str: 렌더링된 텍스트 차트 전체 문자열. 데이터 부족 시 안내 메시지 반환.
        """
        if not candles:
            return " [차트 데이터가 없습니다. 주말/휴장일 또는 데이터 지연 여부를 확인하세요.]"

        # 사용 가능한 너비에 맞춰 데이터 슬라이싱 및 정렬 (과거 -> 현재)
        # candles[0] 이 가장 최신이므로 뒤집어서 과거부터 출력함
        data = candles[:width]
        data.reverse()
        
        if not data: return " [차트 데이터 부족]"

        try:
            highs = [float(c.get('stck_hgpr', 0) or c.get('hts_high', 0)) for c in data]
            lows = [float(c.get('stck_lwpr', 0) or c.get('hts_low', 0)) for c in data]
            opens = [float(c.get('stck_oprc', 0) or c.get('hts_open', 0)) for c in data]
            closes = [float(c.get('stck_clpr', 0) or c.get('hts_last', 0)) for c in data]
        except (ValueError, TypeError):
            return " [데이터 파싱 오류]"

        max_p = max(highs)
        min_p = min(lows)
        price_range = max_p - min_p if max_p != min_p else 1.0

        # 도표 캔버스 초기화 (높이 x 너비)
        canvas = [[' ' for _ in range(len(data))] for _ in range(height)]

        def get_y(p):
            """전체 가격 범위 내에서 현재 가격의 Y축 위치(0 ~ height-1)를 정수로 계산합니다."""
            raw_y = (p - min_p) / price_range * (height - 1)
            return int(round(raw_y))

        for x in range(len(data)):
            o, h, l, c = opens[x], highs[x], lows[x], closes[x]
            y_h, y_l = get_y(h), get_y(l)
            y_o, y_c = get_y(o), get_y(c)
            
            # 1. 꼬리(Wick) 그리기
            for y in range(min(y_h, y_l), max(y_h, y_l) + 1):
                if 0 <= y < height: canvas[y][x] = '│'
            
            # 2. 몸통(Body) 그리기 및 색상 적용
            # 상승(빨강), 하락(파랑), 보합(흰색)
            color = "\033[91m" if c > o else ("\033[94m" if c < o else "")
            reset = "\033[0m"
            
            body_start, body_end = min(y_o, y_c), max(y_o, y_c)
            for y in range(body_start, body_end + 1):
                if 0 <= y < height:
                    # 몸통이 한 칸인 경우에도 표시
                    char = "┃" if body_start == body_end else "█"
                    canvas[y][x] = f"{color}{char}{reset}"

        # 3. 텍스트 버퍼 구성 (Y축 상단부터 하단까지)
        output = []
        if title:
            output.append(f" \033[1m[{title}]\033[0m")
            
        for y in range(height - 1, -1, -1):
            # Y축 가격 라벨 (처음, 마지막, 중간 정도만 표시)
            if y == height - 1:
                label = f"{max_p:10,.0f} ┐"
            elif y == 0:
                label = f"{min_p:10,.0f} ┘"
            elif y == height // 2:
                label = f"{min_p + price_range/2:10,.0f} ┤"
            else:
                label = " " * 10 + "│"
            
            row_str = "".join(canvas[y])
            output.append(f"{label}{row_str}")
            
        # X축 구분선
        output.append(" " * 11 + "└" + "─" * len(data))
        
        return "\n".join(output)
