import os
import re
from reportlab.lib.pagesizes import A4
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak, KeepTogether, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.units import inch, mm
from reportlab.pdfgen import canvas

# 폰트 경로 탐색 (D2Coding 최우선)
FONT_PATHS = [
    "fonts/D2Coding.ttf",
    os.path.join(os.path.dirname(__file__), "../../fonts/D2Coding.ttf"),
    "C:/Windows/Fonts/D2Coding.ttf",
    "C:/Windows/Fonts/NanumGothic.ttf",
    "C:/Windows/Fonts/malgun.ttf",
    "/usr/share/fonts/truetype/d2coding/D2Coding.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/nanum/NanumGothic.ttf",
]

FONT_NAME = "D2Coding"
FONT_BOLD_NAME = "D2Coding"

def register_fonts():
    global FONT_NAME, FONT_BOLD_NAME
    for path in FONT_PATHS:
        abs_path = os.path.abspath(path)
        if os.path.exists(abs_path):
            try:
                pdfmetrics.registerFont(TTFont("D2Coding", abs_path))
                FONT_NAME = "D2Coding"
                FONT_BOLD_NAME = "D2Coding"
                print(f"[*] Korean Font registered: {abs_path}")
                return True
            except Exception as e:
                print(f"[!] Font register error ({abs_path}): {e}")
                continue

    FONT_NAME = "Helvetica"
    FONT_BOLD_NAME = "Helvetica-Bold"
    print("[!] Warning: No Korean font found. Using Helvetica fallback.")
    return False

register_fonts()

class NumberedCanvas(canvas.Canvas):
    """
    2-pass 캔버스를 통해 전체 페이지 수 계산 및 세련된 러닝 헤더/푸터 출력
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, total_pages):
        self.saveState()
        self.setFont(FONT_NAME, 8)
        self.setFillColor(colors.HexColor("#6C757D"))

        page_w, page_h = A4
        left_m = 40
        right_m = page_w - 40

        # 첫 페이지(표지/개요)는 상단 헤더 생략
        if self._pageNumber > 1:
            # 상단 헤더
            self.drawString(left_m, page_h - 30, "AI-Vibe-Trader 사용자 조작 및 운용 매뉴얼 (v2.4.1)")
            self.drawRightString(right_m, page_h - 30, "Autonomous Trading System")
            self.setStrokeColor(colors.HexColor("#DEE2E6"))
            self.setLineWidth(0.5)
            self.line(left_m, page_h - 34, right_m, page_h - 34)

        # 하단 푸터 (모든 페이지)
        self.setStrokeColor(colors.HexColor("#DEE2E6"))
        self.setLineWidth(0.5)
        self.line(left_m, 40, right_m, 40)

        self.drawString(left_m, 28, "Confidential - For Personal Trading Use Only")
        self.drawRightString(right_m, 28, f"페이지 {self._pageNumber} / {total_pages}")

        self.restoreState()


def format_inline_markdown(text):
    """
    인라인 마크다운 문법을 ReportLab Paragraph용 HTML 태그로 안전 변환
    """
    # 1. 특수문자 HTML 엔티티 치환 (단, <font>, <b>, <i> 등과 겹치지 않게 사전 치환)
    text = text.replace("&", "&amp;")
    
    # 2. 코드 스팬 `code` -> <font color="#D63384"><b>code</b></font>
    text = re.sub(r'`([^`]+)`', r'<font color="#D63384"><b>\1</b></font>', text)
    
    # 3. 볼드 **text** -> <b>text</b>
    text = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', text)
    
    # 4. 이탤릭 *text* -> <i>\1</i>
    text = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<i>\1</i>', text)
    
    # 5. 링크 [text](url) -> <u>text</u>
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<font color="#0D6EFD"><u>\1</u></font>', text)

    return text


def create_pdf_from_md(input_md, output_pdf):
    if not os.path.exists(input_md):
        print(f"[!] Error: {input_md} not found.")
        return False

    with open(input_md, 'r', encoding='utf-8') as f:
        content = f.read()

    os.makedirs(os.path.dirname(os.path.abspath(output_pdf)), exist_ok=True)

    page_w, page_h = A4
    margin = 40
    content_w = page_w - (margin * 2)

    doc = SimpleDocTemplate(
        output_pdf,
        pagesize=A4,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=45,
        bottomMargin=50
    )

    styles = getSampleStyleSheet()

    # 맞춤형 스타일 정의
    body_style = ParagraphStyle(
        name='BodyKR',
        fontName=FONT_NAME,
        fontSize=9,
        leading=14,
        textColor=colors.HexColor("#212529"),
        spaceAfter=6
    )

    bullet_style = ParagraphStyle(
        name='BulletKR',
        parent=body_style,
        leftIndent=14,
        firstLineIndent=-10,
        spaceAfter=4
    )

    title_style = ParagraphStyle(
        name='TitleKR',
        fontName=FONT_BOLD_NAME,
        fontSize=22,
        leading=26,
        textColor=colors.HexColor("#0D6EFD"),
        alignment=1, # Center
        spaceBefore=10,
        spaceAfter=15
    )

    h1_style = ParagraphStyle(
        name='Heading1KR',
        fontName=FONT_BOLD_NAME,
        fontSize=15,
        leading=19,
        textColor=colors.HexColor("#1A2530"),
        spaceBefore=14,
        spaceAfter=8,
        keepWithNext=True
    )

    h2_style = ParagraphStyle(
        name='Heading2KR',
        fontName=FONT_BOLD_NAME,
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#2C3E50"),
        spaceBefore=10,
        spaceAfter=6,
        keepWithNext=True
    )

    h3_style = ParagraphStyle(
        name='Heading3KR',
        fontName=FONT_BOLD_NAME,
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#34495E"),
        spaceBefore=8,
        spaceAfter=4,
        keepWithNext=True
    )

    code_style = ParagraphStyle(
        name='CodeKR',
        fontName=FONT_NAME,
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#212529"),
        backColor=colors.HexColor("#F8F9FA"),
        borderColor=colors.HexColor("#DEE2E6"),
        borderWidth=0.5,
        borderPadding=6,
        spaceBefore=4,
        spaceAfter=6
    )

    callout_style = ParagraphStyle(
        name='CalloutKR',
        fontName=FONT_NAME,
        fontSize=8.5,
        leading=13,
        textColor=colors.HexColor("#1E3A8A"),
        backColor=colors.HexColor("#EFF6FF"),
        borderColor=colors.HexColor("#93C5FD"),
        borderWidth=0.8,
        borderPadding=6,
        spaceBefore=6,
        spaceAfter=8
    )

    table_header_style = ParagraphStyle(
        name='TableHeaderKR',
        fontName=FONT_BOLD_NAME,
        fontSize=8.5,
        leading=11,
        textColor=colors.white,
        alignment=1 # Center
    )

    table_cell_style = ParagraphStyle(
        name='TableCellKR',
        fontName=FONT_NAME,
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#212529")
    )

    table_cell_center_style = ParagraphStyle(
        name='TableCellCenterKR',
        fontName=FONT_NAME,
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#212529"),
        alignment=1
    )

    story = []
    lines = content.split('\n')

    in_table = False
    table_lines = []
    in_code_block = False
    code_lines = []

    def flush_table(tbl_lines):
        if not tbl_lines:
            return None
        
        parsed_rows = []
        for l in tbl_lines:
            # 양 끝의 | 제거 및 분할
            clean = l.strip()
            if clean.startswith('|'): clean = clean[1:]
            if clean.endswith('|'): clean = clean[:-1]
            cols = [c.strip() for c in clean.split('|')]
            # 구분선(---)은 제외
            if any(set(c).issubset({'-', ':', ' '}) for c in cols if c):
                continue
            parsed_rows.append(cols)

        if not parsed_rows:
            return None

        # 열 개수 맞추기 (최대 열 수 기준)
        max_cols = max(len(r) for r in parsed_rows)
        for r in parsed_rows:
            while len(r) < max_cols:
                r.append('')

        # 컬럼 너비 분배
        col_widths = None
        if max_cols == 2:
            col_widths = [content_w * 0.30, content_w * 0.70]
        elif max_cols == 3:
            col_widths = [content_w * 0.18, content_w * 0.22, content_w * 0.60]
        elif max_cols == 4:
            col_widths = [content_w * 0.15, content_w * 0.20, content_w * 0.45, content_w * 0.20]
        elif max_cols == 5:
            col_widths = [content_w * 0.12, content_w * 0.18, content_w * 0.25, content_w * 0.25, content_w * 0.20]
        else:
            col_widths = [content_w / max_cols] * max_cols

        formatted_table_data = []
        for row_idx, row in enumerate(parsed_rows):
            formatted_row = []
            for col_idx, cell in enumerate(row):
                fmt_text = format_inline_markdown(cell)
                if row_idx == 0:
                    formatted_row.append(Paragraph(fmt_text, table_header_style))
                else:
                    # 번호나 단축키 등 짧은 첫 번째 컬럼은 중앙 정렬
                    if col_idx == 0 and len(cell) <= 6:
                        formatted_row.append(Paragraph(fmt_text, table_cell_center_style))
                    else:
                        formatted_row.append(Paragraph(fmt_text, table_cell_style))
            formatted_table_data.append(formatted_row)

        t = Table(formatted_table_data, colWidths=col_widths, repeatRows=1)
        t_style = [
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#DEE2E6")),
            ('BOX', (0, 0), (-1, -1), 0.8, colors.HexColor("#ADB5BD")),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ]
        # 지브라 스트라이핑
        for r_i in range(1, len(formatted_table_data)):
            if r_i % 2 == 0:
                t_style.append(('BACKGROUND', (0, r_i), (-1, r_i), colors.HexColor("#F8F9FA")))
        t.setStyle(TableStyle(t_style))
        return t

    for line in lines:
        stripped = line.strip()

        # 코드 블록 처리
        if stripped.startswith('```'):
            if in_code_block:
                code_text = "<br/>".join(code_lines)
                story.append(Paragraph(code_text, code_style))
                code_lines = []
                in_code_block = False
            else:
                if in_table:
                    tbl = flush_table(table_lines)
                    if tbl:
                        story.append(tbl)
                        story.append(Spacer(1, 6))
                    table_lines = []
                    in_table = False
                in_code_block = True
                code_lines = []
            continue

        if in_code_block:
            safe_line = stripped.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            code_lines.append(safe_line if safe_line else "&nbsp;")
            continue

        # 테이블 감지 및 버퍼링
        if '|' in stripped and not stripped.startswith('>'):
            in_table = True
            table_lines.append(stripped)
            continue
        elif in_table:
            tbl = flush_table(table_lines)
            if tbl:
                story.append(tbl)
                story.append(Spacer(1, 6))
            table_lines = []
            in_table = False

        # 빈 줄 처리
        if not stripped:
            story.append(Spacer(1, 4))
            continue

        # 구분선 (---)
        if stripped in ('---', '***', '___'):
            story.append(Spacer(1, 4))
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#DEE2E6"), spaceAfter=6, spaceBefore=4))
            continue

        # 인용구 및 알림 (> [!NOTE] 등)
        if stripped.startswith('>'):
            callout_text = stripped.lstrip('>').strip()
            # [!NOTE], [!TIP] 등의 깃허브 얼럿 표기 변환
            callout_text = re.sub(r'\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]', r'<b>[\1]</b>', callout_text)
            fmt_callout = format_inline_markdown(callout_text)
            story.append(Paragraph(fmt_callout, callout_style))
            continue

        # 헤더 레벨 파싱
        if stripped.startswith('# '):
            title_text = format_inline_markdown(stripped[2:].strip())
            story.append(Paragraph(title_text, title_style))
            story.append(Spacer(1, 8))
        elif stripped.startswith('## '):
            h1_text = format_inline_markdown(stripped[3:].strip())
            story.append(Paragraph(h1_text, h1_style))
        elif stripped.startswith('### '):
            h2_text = format_inline_markdown(stripped[4:].strip())
            story.append(Paragraph(h2_text, h2_style))
        elif stripped.startswith('#### '):
            h3_text = format_inline_markdown(stripped[5:].strip())
            story.append(Paragraph(h3_text, h3_style))

        # 리스트 아이템 (*, -, 숫자.)
        elif stripped.startswith(('* ', '- ', '+ ')):
            bullet_text = format_inline_markdown(stripped[2:].strip())
            story.append(Paragraph(f"• {bullet_text}", bullet_style))
        elif re.match(r'^\d+\.\s+', stripped):
            num_match = re.match(r'^(\d+\.)\s+(.*)', stripped)
            prefix = num_match.group(1)
            rest_text = format_inline_markdown(num_match.group(2))
            story.append(Paragraph(f"<b>{prefix}</b> {rest_text}", bullet_style))

        # 일반 본문 문단
        else:
            p_text = format_inline_markdown(stripped)
            story.append(Paragraph(p_text, body_style))

    # 남아있는 테이블 플러시
    if in_table and table_lines:
        tbl = flush_table(table_lines)
        if tbl:
            story.append(tbl)

    try:
        doc.build(story, canvasmaker=NumberedCanvas)
        print(f"[*] PDF Build Success: {output_pdf}")
        return True
    except Exception as e:
        print(f"[!] PDF Build Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    create_pdf_from_md("docs/USER_MANUAL.md", "target/USER_MANUAL.pdf")
