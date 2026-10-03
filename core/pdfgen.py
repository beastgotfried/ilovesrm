"""PDF renderer: boilerplate answer JSON + student identity -> solved worksheet PDF.

Design: course-accented header band, identity line, section blocks with
accent bars, per-page footer with name / reg / page number.

Render caching: a SHA-256 of (boilerplate JSON + course + code + name + reg)
is stored next to the PDF as <code>_solved.hash; unchanged inputs reuse the
existing PDF instead of rebuilding it.
"""
import hashlib
import json, os, re
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph,
                                Spacer, HRFlowable, Table, TableStyle, KeepTogether)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

COURSE_META = {
    "21LEM202T": ("Universal Human Values — II", colors.HexColor("#0e7a5f")),
    "21CSC203P": ("Advanced Programming Practice", colors.HexColor("#1a3a6b")),
    "21CSS201T": ("Computer Organization and Architecture", colors.HexColor("#5b2c8b")),
    "21CSC201J": ("Data Structures and Algorithms", colors.HexColor("#8b4513")),
    "21CSC202J": ("Operating Systems", colors.HexColor("#0f5e8c")),
    "21MAB201T": ("Transforms and Boundary Value Problems", colors.HexColor("#8c1d40")),
}
DEFAULT_META = ("Course Worksheet", colors.HexColor("#333333"))

TITLE = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=15, leading=19,
                       textColor=colors.white)
SUB = ParagraphStyle("sub", fontName="Helvetica", fontSize=9.5, leading=13,
                     textColor=colors.HexColor("#e8e8e8"))
IDENT = ParagraphStyle("ident", fontName="Helvetica", fontSize=9.5, leading=13,
                       textColor=colors.HexColor("#222222"))
WTITLE = ParagraphStyle("wtitle", fontName="Helvetica-Bold", fontSize=12, leading=16,
                        textColor=colors.HexColor("#111111"), spaceAfter=2 * mm)
H2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=11, leading=15,
                    spaceBefore=5 * mm, spaceAfter=2.2 * mm)
BODY = ParagraphStyle("body", fontName="Helvetica", fontSize=10, leading=14.5,
                      spaceAfter=1.6, alignment=TA_LEFT)
FOOT = ParagraphStyle("foot", fontName="Helvetica", fontSize=8,
                      textColor=colors.HexColor("#777777"))


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def db_entry(course, code):
    path = os.path.join(ROOT, "data", course, f"unit-{code[0]}", code, "boilerplate.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def _footer(canvas, doc, name, reg, accent):
    canvas.saveState()
    canvas.setStrokeColor(accent)
    canvas.setLineWidth(0.6)
    canvas.line(18 * mm, 12 * mm, A4[0] - 18 * mm, 12 * mm)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#777777"))
    canvas.drawString(18 * mm, 8 * mm, f"{name}  ·  {reg}")
    canvas.drawRightString(A4[0] - 18 * mm, 8 * mm, f"Page {doc.page}")
    canvas.restoreState()


def _render_hash(course, code, name, reg, data):
    h = hashlib.sha256()
    h.update(json.dumps(data, sort_keys=True).encode())
    h.update(f"|{course}|{code}|{name}|{reg}|v2".encode())
    return h.hexdigest()


def render(course, code, name, reg, outdir):
    """Render one solved worksheet. Returns path or None if no boilerplate.
    Reuses the existing PDF when boilerplate + identity are unchanged."""
    data = db_entry(course, code)
    if data is None:
        return None

    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, f"{code}_solved.pdf")
    digest = _render_hash(course, code, name, reg, data)
    hash_path = path[:-4] + ".hash"
    if os.path.exists(path) and os.path.exists(hash_path):
        with open(hash_path) as f:
            if f.read().strip() == digest:
                return path                     # cache hit — skip rebuild

    course_name, accent = COURSE_META.get(course, DEFAULT_META)
    unit, sess, slo = code[0], str(int(code[1:3])), code[3]
    doc = BaseDocTemplate(path, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                          topMargin=16 * mm, bottomMargin=18 * mm,
                          title=f"{course} {code} Solved Worksheet — {name}",
                          author=name)
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f")
    doc.addPageTemplates([PageTemplate(
        id="p", frames=[frame],
        onPage=lambda c, d: _footer(c, d, name, reg, accent))])

    # header band
    band = Table([[Paragraph(f"{course_name}  ·  {course}", TITLE)],
                  [Paragraph(f"Unit {unit}  ·  Session {sess}  ·  SLO {slo} — Solved Worksheet", SUB)]],
                 colWidths=[doc.width])
    band.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), accent),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
    ]))
    el = [band, Spacer(1, 3 * mm),
          Paragraph(f"<b>Name:</b> {_esc(name)} &nbsp;&nbsp;|&nbsp;&nbsp; "
                    f"<b>Reg. No:</b> {_esc(reg)}", IDENT),
          Spacer(1, 1.5 * mm),
          HRFlowable(width="100%", color=accent, thickness=1.1),
          Spacer(1, 2.5 * mm),
          Paragraph(_esc(data["title"]), WTITLE)]

    chex = "#" + accent.hexval()[2:]
    for heading, lines in data["sections"]:
        block = [Paragraph(f'<font color="{chex}">▍</font> {_esc(heading)}', H2)]
        for ln in lines:
            # numbered / lettered answers keep their own marker; others get a dot
            marker = "" if re.match(r"^\s*(\d+\.|[A-D][).])", ln) else "•  "
            block.append(Paragraph(marker + _esc(ln), BODY))
        el.append(KeepTogether(block[:2]))
        el.extend(block[2:])
    doc.build(el)
    with open(hash_path, "w") as f:
        f.write(digest)
    return path


def available_codes(course):
    """Worksheet codes that have answer-key boilerplate, from
    data/<course>/unit-N/<code>/boilerplate.json."""
    base = os.path.join(ROOT, "data", course)
    if not os.path.isdir(base):
        return []
    out = []
    for unit in os.listdir(base):
        udir = os.path.join(base, unit)
        if not unit.startswith("unit-") or not os.path.isdir(udir):
            continue
        for code in os.listdir(udir):
            if os.path.exists(os.path.join(udir, code, "boilerplate.json")):
                out.append(code)
    return sorted(out)
