"""Build and validate the submission guide without changing application dependencies.

From the repository root:
  uv run --no-project --with reportlab --with pypdf --with pillow python submission/build_documentation.py

Uses Segoe UI/Consolas on Windows; ReportLab's bundled Vera fonts elsewhere.
Render for visual inspection with:
  pdftoppm -scale-to 1200 -png output/pdf/Resolve_Technical_Documentation.pdf tmp/pdfs/page
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Flowable, Frame, PageBreak, PageTemplate,
    Paragraph, Preformatted, Spacer, Table, TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "submission/Resolve_Technical_Documentation.md"
OUTPUT = ROOT / "output/pdf/Resolve_Technical_Documentation.pdf"
QA_DIR = ROOT / "tmp/pdfs"
WIDTH, HEIGHT = A4
MARGIN = 48
CONTENT = WIDTH - 2 * MARGIN
NAVY = colors.HexColor("#172B47")
BLUE = colors.HexColor("#2355AE")
INK = colors.HexColor("#263649")
MUTED = colors.HexColor("#617184")
LINE = colors.HexColor("#D8DFE8")
PALE = colors.HexColor("#F3F6FA")


def fonts():
    import reportlab
    bundled = Path(reportlab.__file__).parent / "fonts"
    windows = Path("C:/Windows/Fonts")
    pairs = [
        ("Body", windows / "segoeui.ttf", bundled / "Vera.ttf"),
        ("Strong", windows / "seguisb.ttf", bundled / "VeraBd.ttf"),
        ("Italic", windows / "segoeuii.ttf", bundled / "VeraIt.ttf"),
        ("Code", windows / "consola.ttf", bundled / "Vera.ttf"),
    ]
    for name, preferred, fallback in pairs:
        pdfmetrics.registerFont(TTFont(name, str(preferred if preferred.exists() else fallback)))
    pdfmetrics.registerFontFamily("Body", normal="Body", bold="Strong", italic="Italic", boldItalic="Strong")


fonts()
STYLES = {
    "title": ParagraphStyle("title", fontName="Strong", fontSize=23, leading=29, textColor=NAVY, spaceAfter=17),
    "h2": ParagraphStyle("h2", fontName="Strong", fontSize=11.1, leading=15, textColor=NAVY, spaceBefore=12, spaceAfter=6, keepWithNext=True),
    "body": ParagraphStyle("body", fontName="Body", fontSize=9.6, leading=14.1, textColor=INK, spaceAfter=8, allowWidows=0, allowOrphans=0),
    "bullet": ParagraphStyle("bullet", fontName="Body", fontSize=9.6, leading=14.1, textColor=INK, leftIndent=11, firstLineIndent=-10, spaceAfter=5),
    "table": ParagraphStyle("table", fontName="Body", fontSize=8.5, leading=11.7, textColor=INK, spaceAfter=0, splitLongWords=True),
    "tablehead": ParagraphStyle("tablehead", fontName="Strong", fontSize=8.5, leading=11.7, textColor=colors.white, spaceAfter=0),
    "code": ParagraphStyle("code", fontName="Code", fontSize=7.65, leading=11.1, textColor=NAVY, backColor=PALE, borderColor=LINE, borderWidth=0.5, borderPadding=9, spaceBefore=5, spaceAfter=12),
    "small": ParagraphStyle("small", fontName="Body", fontSize=7.9, leading=11.5, textColor=MUTED, spaceAfter=7),
}


def inline(text):
    text = html.escape(text)
    text = re.sub(r"`([^`]+)`", r'<font name="Code" size="8.2">\1</font>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    return text


def paragraph(text, style="body"):
    return Paragraph(inline(text), STYLES[style])


class Cover(Flowable):
    def __init__(self):
        super().__init__()
        self.width = CONTENT
        self.height = 688

    def draw(self):
        c = self.canv
        c.setFillColor(NAVY)
        c.rect(0, 659, 35, 5, fill=1, stroke=0)
        c.setFont("Strong", 15)
        c.drawString(0, 625, "Resolve.")
        c.setFillColor(MUTED)
        c.setFont("Body", 9)
        c.drawString(0, 602, "PAYMENT AFTERCARE FOR PAYPAL MERCHANTS")
        c.setFillColor(NAVY)
        c.setFont("Strong", 36)
        c.drawString(0, 478, "Technical")
        c.drawString(0, 432, "documentation")
        c.setStrokeColor(BLUE)
        c.setLineWidth(2)
        c.line(0, 404, 68, 404)
        p = paragraph("Resolve connects a customer's issue, the merchant's commitment and the payment evidence needed to determine whether that commitment was fulfilled.")
        p.wrap(CONTENT - 67, 200)
        p.drawOn(c, 0, 322)
        c.setStrokeColor(LINE)
        c.setLineWidth(0.6)
        c.line(0, 258, CONTENT, 258)
        for x, label, value in [(0, "EDITION", "Submission"), (173, "ISSUED", "12 November 2026"), (351, "AUDIENCE", "Reviewers / developers")]:
            c.setFillColor(MUTED)
            c.setFont("Strong", 7.5)
            c.drawString(x, 235, label)
            c.setFillColor(INK)
            c.setFont("Body", 9)
            c.drawString(x, 215, value)
        p = paragraph("This guide describes the implemented repository and its recorded validation. PayPal transactions discussed here use Sandbox test funds. A model recommendation does not authorize a refund.", "small")
        p.wrap(CONTENT - 30, 100)
        p.drawOn(c, 0, 89)


class Architecture(Flowable):
    def __init__(self):
        super().__init__()
        self.width = CONTENT
        self.height = 188

    def draw(self):
        c = self.canv

        def box(x, y, w, h, title, sub):
            c.setFillColor(PALE)
            c.setStrokeColor(LINE)
            c.roundRect(x, y, w, h, 5, fill=1, stroke=1)
            c.setFillColor(NAVY)
            c.setFont("Strong", 9)
            c.drawString(x + 10, y + h - 19, title)
            c.setFillColor(MUTED)
            c.setFont("Body", 7.8)
            c.drawString(x + 10, y + 12, sub)

        def arrow(x1, y1, x2, y2):
            c.setStrokeColor(BLUE)
            c.setLineWidth(0.9)
            c.line(x1, y1, x2, y2)
            path = c.beginPath()
            if x1 == x2:
                path.moveTo(x2 - 3, y2 + 5)
                path.lineTo(x2, y2)
                path.lineTo(x2 + 3, y2 + 5)
            else:
                path.moveTo(x2 - 5, y2 + 3)
                path.lineTo(x2, y2)
                path.lineTo(x2 - 5, y2 - 3)
            c.drawPath(path)

        box(0, 125, 233, 48, "Buyer / merchant browser", "Next.js workspace and private portal")
        box(267, 125, 232, 48, "Merchant app server", "Owned orders / Resolve TypeScript SDK")
        box(0, 52, 233, 48, "Resolve API", "FastAPI / validation / authorization")
        box(267, 52, 232, 48, "Workers and storage", "Durable queues / SQLite or PostgreSQL")
        # Both callers reach the API; merchant apps never connect to Resolve storage.
        c.setStrokeColor(BLUE)
        c.setLineWidth(0.9)
        c.line(383, 125, 383, 112)
        c.line(383, 112, 116, 112)
        arrow(116, 125, 116, 100)
        arrow(233, 76, 267, 76)
        c.setStrokeColor(LINE)
        c.line(0, 35, 499, 35)
        c.setFillColor(MUTED)
        c.setFont("Body", 8.3)
        c.drawString(0, 17, "Trusted adapters: PayPal REST / optional evidence providers / bounded model inference")


class Workflow(Flowable):
    def __init__(self):
        super().__init__()
        self.width = CONTENT
        self.height = 48

    def draw(self):
        c = self.canv
        labels = ["Issue", "Commitment", "Evidence", "Approval", "Execution", "Verification"]
        step = CONTENT / len(labels)
        for i, label in enumerate(labels):
            x = i * step
            c.setFillColor(BLUE)
            c.circle(x + 6, 34, 3, fill=1, stroke=0)
            c.setStrokeColor(LINE)
            if i < len(labels) - 1:
                c.line(x + 12, 34, x + step, 34)
            c.setFillColor(NAVY)
            c.setFont("Strong", 8)
            c.drawString(x, 15, label)


def table(lines):
    rows = [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in lines]
    rows = [r for r in rows if not all(re.fullmatch(r"[: -]+", cell) for cell in r)]
    cols = len(rows[0])
    fractions = [0.39, 0.61] if cols == 2 else [0.27, 0.34, 0.39]
    if rows[0] == ["Section", "Page"]:
        fractions = [0.88, 0.12]
    elif rows[0][0] == "Setting":
        fractions = [0.56, 0.44]
    data = [[Paragraph(inline(cell), STYLES["tablehead" if i == 0 else "table"]) for cell in row] for i, row in enumerate(rows)]
    t = Table(data, colWidths=[CONTENT * f for f in fractions], repeatRows=1, hAlign="LEFT")
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, NAVY),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINE),
    ]
    for i in range(2, len(rows), 2):
        commands.append(("BACKGROUND", (0, i), (-1, i), PALE))
    t.setStyle(TableStyle(commands))
    t.spaceAfter = 10
    return t


def parse(section):
    lines = section.strip().splitlines()
    items = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if line.startswith("# "):
            items.append(paragraph(line[2:], "title"))
        elif line.startswith("## "):
            items.append(paragraph(line[3:], "h2"))
        elif line == ":::architecture":
            items.append(Architecture())
        elif line == ":::workflow":
            items.append(Workflow())
        elif line.startswith("```"):
            code = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            for code_line in code:
                if pdfmetrics.stringWidth(code_line, "Code", 7.65) > CONTENT - 20:
                    raise ValueError(f"Code line too wide: {code_line}")
            items.append(Preformatted("\n".join(code), STYLES["code"]))
        elif line.startswith("|"):
            collected = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                collected.append(lines[i])
                i += 1
            items.append(table(collected))
            continue
        elif line.startswith("- "):
            items.append(paragraph("\u2022 " + line[2:], "bullet"))
        elif re.match(r"^\d+\. ", line):
            items.append(paragraph(line, "body"))
        else:
            style = "small" if line.startswith("Source:") else "body"
            items.append(paragraph(line, style))
        i += 1
    return items


class GuideDoc(BaseDocTemplate):
    def afterFlowable(self, item):
        if isinstance(item, Paragraph) and item.style.name == "title":
            title = item.getPlainText()
            self.canv.bookmarkPage(title)
            self.canv.addOutlineEntry(title, title, 0, closed=False)


def chrome(canvas, doc):
    canvas.saveState()
    if doc.page > 1:
        canvas.setFont("Strong", 8)
        canvas.setFillColor(NAVY)
        canvas.drawString(MARGIN, HEIGHT - 34, "Resolve.")
        canvas.setFont("Body", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawRightString(WIDTH - MARGIN, HEIGHT - 34, "TECHNICAL DOCUMENTATION / SUBMISSION EDITION")
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, HEIGHT - 43, WIDTH - MARGIN, HEIGHT - 43)
    canvas.setStrokeColor(LINE)
    canvas.line(MARGIN, 42, WIDTH - MARGIN, 42)
    canvas.setFont("Body", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(MARGIN, 28, "12 November 2026  |  Repository implementation and recorded evidence")
    canvas.drawRightString(WIDTH - MARGIN, 28, f"{doc.page:02d} / 14")
    canvas.restoreState()


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    QA_DIR.mkdir(parents=True, exist_ok=True)
    source = SOURCE.read_text(encoding="utf-8")
    sections = source.split("<!-- page -->")
    if len(sections) != 14:
        raise ValueError("Expected the 14 authored pages")
    story = [Cover(), PageBreak()]
    for i, section in enumerate(sections[1:], start=2):
        story.extend(parse(section))
        if i < 14:
            story.append(PageBreak())
    doc = GuideDoc(str(OUTPUT), pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                   topMargin=66, bottomMargin=56, title="Resolve | Technical documentation",
                   author="Resolve", subject="Architecture, installation, integration and validation",
                   creator="Resolve documentation build")
    frame = Frame(MARGIN, 56, CONTENT, HEIGHT - 122, leftPadding=0, bottomPadding=0,
                  rightPadding=0, topPadding=0, id="body")
    doc.addPageTemplates(PageTemplate(id="guide", frames=[frame], onPage=chrome))
    doc.build(story)
    reader = PdfReader(OUTPUT)
    headings = [section.strip().splitlines()[0][2:] for section in sections]
    if len(reader.pages) != 14:
        raise ValueError(f"Layout overflow: expected 14 pages, got {len(reader.pages)}")
    pages = []
    for number, (page, title) in enumerate(zip(reader.pages, headings), start=1):
        text = page.extract_text()
        if title not in text:
            raise ValueError(f"Page {number} does not start its intended section: {title}")
        if "\ufffd" in text or "\u25a0" in text:
            raise ValueError(f"Possible missing glyph on page {number}")
        pages.append({"page": number, "heading": title, "characters": len(text)})
    result = {"pages": len(reader.pages), "bytes": OUTPUT.stat().st_size, "page_checks": pages}
    (QA_DIR / "document_validation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
