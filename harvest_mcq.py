#!/usr/bin/env python3
"""Harvest the full question bank (MCQ + SQ + LQ, with answers) for every
course via student/session/getquestions. Questions reshuffle per call, so we
pull repeatedly and dedupe by _id until the bank stops growing.

Output: db/<course>/mcq/<session>.json  {"mcq": [...], "sq": [...], "lq": [...]}
"""
import json, os, sys, time
import concurrent.futures

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from core import portal, portal_http as ph

COURSES = {           # course -> sessions per unit
    "21CSS201T": 12,  # COA
    "21CSC203P": 12,  # APP
    "21LEM202T": 9,   # UHV
    "21CSC201J": 12,  # DSA
    "21CSC202J": 12,  # OS
    "21MAB201T": 12,  # Math
}
MAX_PULLS = 10
STABLE_STOP = 2       # stop after this many consecutive pulls with no new ids


def harvest_session(course_info, course, session):
    bank = {"mcq": {}, "sq": {}, "lq": {}}
    stable = 0
    for pull in range(MAX_PULLS):
        try:
            out = ph._session._post("/curricula/student/session/getquestions", {
                "COURSE_INFO": course_info,
                "USER_ID": ph._session.info["USER_ID"],
                "FULL_NAME": ph._session.full_name(),
                "DEPARTMENT": ph._session.info.get("DEPARTMENT"),
                "SLOT": ph._session.info.get("SLOT"),
                "SESSION": session, "key": ph.KEY,
                "MCQ": 5, "SQ": 2, "LQ": 1}, timeout=45)
        except Exception as e:
            return session, None, f"error: {e}"
        if out.get("Status") != 1:
            return session, None, f"Status={out.get('Status')}"
        new = 0
        for kind in ("mcq", "sq", "lq"):
            for q in out.get(kind) or []:
                qid = q.get("_id")
                if qid is not None and qid not in bank[kind]:
                    bank[kind][qid] = q
                    new += 1
        if new == 0:
            stable += 1
            if stable >= STABLE_STOP and pull >= 2:
                break
        else:
            stable = 0
        time.sleep(0.2)
    if not any(bank.values()):
        return session, None, "empty"
    return session, bank, None


def main():
    assert portal.up(), "no cached portal session"
    s = ph._session
    s.list_courses()
    only = sys.argv[1:] or list(COURSES)

    for course in only:
        maxs = COURSES[course]
        s.open_course(course)
        ci = s.course_info
        outdir = os.path.join(ROOT, "db", course, "mcq")
        os.makedirs(outdir, exist_ok=True)
        sessions = [u * 100 + n for u in range(1, 6) for n in range(1, maxs + 1)]
        done = empty = failed = 0
        t0 = time.time()
        # sequential-ish: portal seems fragile; 3 workers max
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
            futs = {ex.submit(harvest_session, ci, course, sess): sess
                    for sess in sessions}
            for f in concurrent.futures.as_completed(futs):
                sess, bank, err = f.result()
                if bank:
                    with open(os.path.join(outdir, f"{sess}.json"), "w") as fh:
                        json.dump({k: sorted(v.values(), key=lambda q: q["_id"])
                                   for k, v in bank.items()}, fh, indent=1)
                    done += 1
                elif err and "empty" in err:
                    empty += 1
                else:
                    failed += 1
                    print(f"  {course} S{sess}: {err}")
        print(f"{course}: {done} banks saved, {empty} empty, {failed} failed "
              f"({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
