"""Fetch 100%-solution answer keys for every session of every course on the
logged-in account, into data/<COURSE>/unit-N/<code>/solutions.json.

Source: /curricula/student/session/getquestions (MCQ+SQ+LQ with official
answers). The session list comes from the account-wide session-status record
(LO keys), so sessions without MCQ scores yet are still covered.

Usage:
    python3 fetch_solutions.py              # all courses on the account
    python3 fetch_solutions.py 21CSC203P    # one course
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bs4 import BeautifulSoup

import core.portal_http as ph

ROOT = os.path.dirname(os.path.abspath(__file__))
LETTERS = "ABCD"


def lines(html):
    soup = BeautifulSoup(html or "", "html.parser")
    blocks = soup.find_all(["p", "li"])
    if not blocks:
        t = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
        return [t] if t else []
    out = []
    for b in blocks:
        t = re.sub(r"\s+", " ", b.get_text(" ", strip=True))
        if t:
            out.append(t)
    return out


def one(html):
    return re.sub(r"\s+", " ", " ".join(lines(html))).strip()


def clean_mcq(item):
    idx = int(item["ANSWER"])
    opts = {LETTERS[i]: one(item[f"OPT_{i + 1}"]) for i in range(4)}
    return {"q": one(item["QUESTION_DESC"]), "options": opts,
            "answer": LETTERS[idx - 1], "answer_text": opts[LETTERS[idx - 1]]}


def clean_qa(item):
    return {"q": one(item["QUESTION_DESC"]), "answer": lines(item["ANSWER"])}


def course_sessions(s):
    """All session numbers (101, 102, ...) for the open course.
    The status record (LO/MCQ keys) only lists sessions the student has
    touched; when it is sparse, probe the full unit/session grid instead."""
    res = ph._with_retry(lambda: s.get_session_status(101), 3, "sessionstatus")
    lo = res.get("LO") or {}
    mcq = res.get("MCQ") or {}
    keys = set(lo) | set(mcq)
    found = sorted(int(k) for k in keys if str(k).isdigit())
    if len(found) >= 10:
        return found
    found = []
    for unit in (1, 2, 3, 4, 5):
        for sess_n in range(1, 13):
            sess = unit * 100 + sess_n
            try:
                q = s._post("/curricula/student/session/getquestions", {
                    "COURSE_INFO": s.course_info, "USER_ID": s.info["USER_ID"],
                    "FULL_NAME": s.full_name(),
                    "DEPARTMENT": s.info.get("DEPARTMENT"),
                    "SLOT": s.info.get("SLOT"), "SESSION": sess,
                    "key": ph.KEY, "MCQ": 1, "SQ": 1, "LQ": 1})
                if q.get("Status") == 1 and ((q.get("mcq") or []) or
                                             (q.get("sq") or []) or
                                             (q.get("lq") or [])):
                    found.append(sess)
            except Exception:
                pass
            time.sleep(0.2)
    return found


def fetch_course(s, course_code):
    s.open_course(course_code)
    sessions = course_sessions(s)
    if not sessions:
        print(f"{course_code}: no sessions visible — skipped")
        return 0
    written = 0
    for sess in sessions:
        unit, sess_n = sess // 100, sess % 100
        try:
            q = ph._with_retry(
                lambda: s._post("/curricula/student/session/getquestions", {
                    "COURSE_INFO": s.course_info, "USER_ID": s.info["USER_ID"],
                    "FULL_NAME": s.full_name(),
                    "DEPARTMENT": s.info.get("DEPARTMENT"),
                    "SLOT": s.info.get("SLOT"), "SESSION": sess,
                    "key": ph.KEY, "MCQ": 5, "SQ": 2, "LQ": 1}),
                3, f"getquestions {sess}")
        except Exception as e:
            print(f"  {sess}: FAILED {e} — skipped")
            continue
        if q.get("Status") != 1:
            print(f"  {sess}: Status={q.get('Status')} — skipped")
            continue
        slo = q.get("slo") or {}
        mcq = [clean_mcq(m) for m in (q.get("mcq") or [])]
        sq = [clean_qa(x) for x in (q.get("sq") or [])]
        lq = [clean_qa(x) for x in (q.get("lq") or [])]
        for slo_n in (1, 2):
            code = f"{sess}{slo_n}"
            doc = {
                "course": course_code, "code": code,
                "unit": unit, "session": sess_n, "slo": slo_n,
                "slo_title": slo.get(f"SLO{slo_n}", ""),
                "mcq": mcq, "sq": sq, "lq": lq,
            }
            d = os.path.join(ROOT, "data", course_code, f"unit-{unit}", code)
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "solutions.json"), "w") as f:
                json.dump(doc, f, indent=1, ensure_ascii=False)
            written += 1
        print(f"  {sess}: mcq={len(mcq)} sq={len(sq)} lq={len(lq)} "
              f"| {slo.get('SLO1', '')[:40]} / {slo.get('SLO2', '')[:40]}")
        time.sleep(0.4)
    print(f"{course_code}: {written} SLO solution files ({len(sessions)} sessions)")
    return written


def main():
    ph._session.load()
    s = ph._session
    if not s.token:
        sys.exit("no cached portal session — run bot.py once to log in")
    want = sys.argv[1:]
    courses = s.list_courses()
    total = 0
    for c in courses:
        code = c.get("COURSE_CODE") or c.get("_id")
        if want and code not in want:
            continue
        try:
            total += fetch_course(s, code)
        except Exception as e:
            print(f"{code}: FAILED {e}")
        time.sleep(1)
    print("TOTAL solution files:", total)


if __name__ == "__main__":
    main()
