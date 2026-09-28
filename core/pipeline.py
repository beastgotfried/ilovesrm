"""Pipeline: boilerplate db -> personalized PDF -> GitHub -> portal link -> verify.

Idempotent: slots already holding the exact target URL are skipped.
Safety: every portal write is guarded by an on-screen course-code check.
"""
import os, time
from . import portal, pdfgen, github

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def unit_of(code):
    return int(code[0])

def session_of(code):
    return int(code[1:3])

def run_course(course, name, reg, gh, units=None, dry_run=False, log=print):
    """Complete all available worksheet slots for a course.

    gh = {"token":..., "owner":..., "repo":...}
    Returns list of per-session result dicts.
    """
    codes = pdfgen.available_codes(course)
    if units:
        codes = [c for c in codes if unit_of(c) in units]
    sessions = sorted({(unit_of(c), session_of(c)) for c in codes})
    if not sessions:
        log(f"  no boilerplate for {course} — nothing to do")
        return []

    if not dry_run:
        github.ensure_repo(gh["token"], gh["owner"], gh["repo"])
        if not portal.open_course(course):
            raise RuntimeError(f"could not open course circle for {course}")
    outdir = os.path.join(ROOT, "build", course, reg)
    results = []

    for unit, sess in sessions:
        pair = sorted(c for c in codes if unit_of(c) == unit and session_of(c) == sess)
        urls = []
        for code in pair:
            pdf = pdfgen.render(course, code, name, reg, outdir)
            if dry_run:
                urls.append(f"https://github.com/{gh['owner']}/{gh['repo']}/blob/main/{course}/{reg}/{code}_solved.pdf")
            else:
                remote = f"{course}/{reg}/{code}_solved.pdf"
                urls.append(github.push_file(gh["token"], gh["owner"], gh["repo"], pdf, remote))

        if dry_run:
            log(f"  U{unit} S{sess}: [dry-run] would submit {len(urls)} link(s)")
            results.append({"unit": unit, "session": sess, "status": "dry-run"})
            continue

        # skip if both slots already hold the target links
        state = portal.read_slot(course, unit, sess)
        if state["links"] and all(l == u for l, u in zip(state["links"], urls)):
            log(f"  U{unit} S{sess}: already correct — skipped")
            results.append({"unit": unit, "session": sess, "status": "already-correct"})
            continue

        ok = portal.submit_links(course, unit, sess, urls)
        if not ok:
            log(f"  U{unit} S{sess}: SUBMIT FAILED")
            results.append({"unit": unit, "session": sess, "status": "failed"})
            continue

        # verify the new links are what the portal now serves
        time.sleep(2)
        check = portal.read_slot(course, unit, sess)
        good = bool(check["links"]) and all(l == u for l, u in zip(check["links"], urls))
        status = "verified" if good else "submitted-unverified"
        log(f"  U{unit} S{sess}: {status}")
        results.append({"unit": unit, "session": sess, "status": status, "urls": urls})

    return results
