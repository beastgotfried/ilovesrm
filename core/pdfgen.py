"""PDF renderer: boilerplate answer JSON + student identity -> solved worksheet PDF."""
import json, os
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_styles = getSampleStyleSheet()
H1 = ParagraphStyle("h1", parent=_styles["Heading1"], fontSize=13, spaceAfter=2)
H2 = ParagraphStyle("h2", parent=_styles["Heading2"], fontSize=11, spaceBefore=8, spaceAfter=3,
                    textColor=colors.HexColor("#1a3a6b"))
BODY = ParagraphStyle("body", parent=_styles["Normal"], fontSize=10, leading=13.5, spaceAfter=2)
META = ParagraphStyle("meta", parent=_styles["Normal"], fontSize=9.5, textColor=colors.HexColor("#444444"))

COURSE_HEADERS = {
    "21LEM202T": "UNIVERSAL HUMAN VALUES — II (UHV-II)",
    "21CSC203P": "ADVANCED PROGRAMMING PRACTICE (21CSC203P)",
    "21CSS201T": "COMPUTER ORGANIZATION AND ARCHITECTURE (21CSS201T)",
}

def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def db_entry(course, code):
    path = os.path.join(ROOT, "data", course, f"unit-{code[0]}", code, "boilerplate.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)

def render(course, code, name, reg, outdir):
    """Render one solved worksheet. Returns path or None if no boilerplate."""
    data = db_entry(course, code)
    if data is None:
        return None
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, f"{code}_solved.pdf")
    doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=18*mm, rightMargin=18*mm,
                            topMargin=14*mm, bottomMargin=14*mm,
                            title=f"{course} {code} Solved Worksheet")
    el = [Paragraph(COURSE_HEADERS.get(course, course), H1),
          Paragraph(_esc(data["title"]), META),
          Paragraph(f"Name: {_esc(name)} &nbsp;|&nbsp; Reg. No: {_esc(reg)} &nbsp;|&nbsp; Solved Worksheet", META),
          Spacer(1, 4),
          HRFlowable(width="100%", color=colors.HexColor("#1a3a6b"), thickness=1)]
    for heading, lines in data["sections"]:
        el.append(Paragraph(_esc(heading), H2))
        for ln in lines:
            el.append(Paragraph("• " + _esc(ln), BODY))
    doc.build(el)
    return path

def available_codes(course):
    """Worksheet codes that have PDF answer-key boilerplate, from
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
