import os
import markdown2
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.units import inch
import re

# OS별 폰트 경로 탐색
FONT_PATHS = [
    "C:/Windows/Fonts/malgun.ttf", # Windows: 맑은 고딕
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf", # Ubuntu: 나눔고딕
    "/usr/share/fonts/nanum/NanumGothic.ttf", # CentOS: 나눔고딕
    "/usr/share/fonts/truetype/baekmuk/dotum.ttf", # Fallback: 백묵 돋움
]

FONT_NAME = "KoreanFont"

def register_font():
    global FONT_NAME
    for path in FONT_PATHS:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont(FONT_NAME, path))
                print(f"[*] Font registered: {path}")
                return True
            except Exception as e:
                print(f"[!] Failed to register font {path}: {e}")
                continue
    
    FONT_NAME = "Helvetica"
    print("[!] Warning: No Korean font found. Using Helvetica.")
    return False

register_font()

def create_pdf_from_md(input_md, output_pdf):
    if not os.path.exists(input_md):
        print(f"[!] Error: {input_md} not found.")
        return

    with open(input_md, 'r', encoding='utf-8') as f:
        text = f.read()

    # 타겟 폴더 생성
    os.makedirs(os.path.dirname(output_pdf), exist_ok=True)

    doc = SimpleDocTemplate(output_pdf, pagesize=A4, 
                            rightMargin=50, leftMargin=50, 
                            topMargin=50, bottomMargin=50)
    
    styles = getSampleStyleSheet()
    
    # 한글 지원 스타일 정의
    normal_style = ParagraphStyle(
        name='NormalKR',
        fontName=FONT_NAME,
        fontSize=10,
        leading=14,
        spaceAfter=10
    )
    
    h1_style = ParagraphStyle(
        name='Heading1KR',
        parent=styles['Heading1'],
        fontName=FONT_NAME,
        fontSize=20,
        leading=24,
        alignment=1, # Center
        spaceAfter=20,
        borderPadding=10,
        borderWidth=1,
        borderColor=colors.black
    )
    
    h2_style = ParagraphStyle(
        name='Heading2KR',
        parent=styles['Heading2'],
        fontName=FONT_NAME,
        fontSize=16,
        leading=20,
        spaceBefore=15,
        spaceAfter=10,
        borderPadding=(0, 0, 2, 0),
        borderWidth=0.5,
        borderColor=colors.grey
    )

    h3_style = ParagraphStyle(
        name='Heading3KR',
        parent=styles['Heading3'],
        fontName=FONT_NAME,
        fontSize=12,
        leading=16,
        spaceBefore=10,
        spaceAfter=8
    )

    story = []

    # Markdown 파싱 및 렌더링
    lines = text.split('\n')
    in_table = False
    table_data = []

    for line in lines:
        line = line.strip()
        
        # 테이블 처리 로직
        if '|' in line:
            if '---' in line: continue
            cells = [c.strip() for c in line.split('|') if c.strip()]
            if cells:
                table_data.append(cells)
                in_table = True
                continue
        elif in_table:
            if table_data:
                t = Table(table_data, hAlign='LEFT')
                t.setStyle(TableStyle([
                    ('FONTNAME', (0,0), (-1,-1), FONT_NAME),
                    ('FONTSIZE', (0,0), (-1,-1), 9),
                    ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
                    ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
                ]))
                story.append(t)
                story.append(Spacer(1, 0.1*inch))
                table_data = []
            in_table = False

        if not line:
            story.append(Spacer(1, 0.1*inch))
            continue

        # 헤더 처리
        if line.startswith('# '):
            story.append(Paragraph(line[2:], h1_style))
        elif line.startswith('## '):
            story.append(Paragraph(line[3:], h2_style))
        elif line.startswith('### '):
            story.append(Paragraph(line[4:], h3_style))
        
        # 이미지 처리
        elif line.startswith('!['):
            match = re.search(r'\((.*?)\)', line)
            if match:
                img_path = match.group(1)
                # 상대 경로를 현재 파일 기준으로 보정
                if not os.path.isabs(img_path):
                    # docs/ 내부에 있으면 한 단계 위로
                    test_path = os.path.join(os.getcwd(), img_path)
                    if os.path.exists(test_path): img_path = test_path

                if os.path.exists(img_path):
                    try:
                        img = Image(img_path, width=5.5*inch, height=3*inch, kind='proportional')
                        story.append(img)
                        story.append(Spacer(1, 0.1*inch))
                    except: pass
        
        # 본문 및 리스트
        else:
            line = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', line)
            if line.startswith('* ') or line.startswith('- '):
                story.append(Paragraph(f"• {line[2:]}", normal_style))
            else:
                story.append(Paragraph(line, normal_style))

    # 마무리 테이블 처리
    if table_data:
        t = Table(table_data, hAlign='LEFT')
        t.setStyle(TableStyle([('FONTNAME', (0,0), (-1,-1), FONT_NAME), ('GRID', (0,0), (-1,-1), 0.5, colors.grey)]))
        story.append(t)

    doc.build(story)
    print(f"[*] Success: {output_pdf}")

if __name__ == "__main__":
    create_pdf_from_md("docs/USER_MANUAL.md", "target/USER_MANUAL.pdf")
