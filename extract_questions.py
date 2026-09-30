#!/usr/bin/env python3
"""Extract question text from downloaded worksheet .docx files into
build/extracted/<course>/<code>.txt — compact plain text for solving.

Only extracts worksheets that have NO boilerplate yet.
Tables are flattened row-wise; empty boilerplate chrome (college header,
name/reg blanks) is stripped.
"""
import json, os, re, sys
from docx import Document

ROOT = os.path.dirname(os.path.abspath(__file__))
INV = os.path.join(ROOT, "build", "file_inventory.json")
SRC = os.path.join(ROOT, "build", "worksheets")
DST = os.path.join(ROOT, "build", "extracted")

SKIP_PATTERNS = [
    r"^SRM Institute", r"^College of Engineering", r"^School of Computing",
    r"^Name:\s*_", r"^Work sheet$", r"^Worksheet:?$", r"^Questions?$",
    r"^Unit\s+[IVX0-9]+$", r"^Date:",
]


def keep(text):
    t = text.strip()
    if not t:
        return False
    return not any(re.match(p, t, re.I) for p in SKIP_PATTERNS)


def extract(path):
    doc = Document(path)
    out = []
    # walk body in order: paragraphs and tables interleaved
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    from docx.oxml.ns import qn
    body = doc.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            p = Paragraph(child, doc)
            if keep(p.text):
                out.append(re.sub(r"[ \t]+", " ", p.text.strip()))
        elif child.tag == qn("w:tbl"):
            t = Table(child, doc)
            for row in t.rows:
                cells = [re.sub(r"\s+", " ", c.text.strip()) for c in row.cells]
                line = " | ".join(c for c in cells if c)
                if keep(line):
                    out.append(line)
    return out


def main():
    inv = json.load(open(INV))
    only = sys.argv[1:]
    total = 0
    for course, items in sorted(inv.items()):
        if only and course not in only:
            continue
        done = 0
        for it in items:
            code = it["code"]
            bp = os.path.join(ROOT, "data", course, f"unit-{code[0]}", code,
                              "boilerplate.json")
            if os.path.exists(bp):
                continue  # already solved
            src = os.path.join(SRC, course, f"{code}.{it['ext']}")
            dst_dir = os.path.join(DST, course)
            os.makedirs(dst_dir, exist_ok=True)
            dst = os.path.join(dst_dir, f"{code}.txt")
            if os.path.exists(dst):
                continue
            if it["ext"] != "docx":
                with open(dst, "w") as f:
                    f.write(f"[PDF worksheet — see {src}]\n")
                continue
            try:
                lines = extract(src)
            except Exception as e:
                lines = [f"[EXTRACTION FAILED: {e}]"]
            with open(dst, "w") as f:
                f.write("\n".join(lines) + "\n")
            done += 1
            total += 1
        print(f"{course}: extracted {done}")
    print("TOTAL extracted:", total)


if __name__ == "__main__":
    main()
