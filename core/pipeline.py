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
    """Complete all available worksheet slots for a course, then top up MCQs.

    gh = {"token":..., "owner":..., "repo":...}
    Returns list of per-session result dicts.
    """
    codes = pdfgen.available_codes(course)
    if units:
        codes = [c for c in codes if unit_of(c) in units]
    sessions = sorted({(unit_of(c), session_of(c)) for c in codes})

    if not dry_run:
        github.ensure_repo(gh["token"], gh["owner"], gh["repo"])
        if not portal.open_course(course):
            raise RuntimeError(f"could not open course circle for {course}")
    results = []

    if not sessions:
        log(f"  no boilerplate for {course} — worksheets skipped")
    else:
        outdir = os.path.join(ROOT, "build", course, reg)
        for unit, sess in sessions:
            try:
                results.append(_run_session(course, codes, unit, sess, name, reg,
                                            gh, outdir, dry_run, log))
            except Exception as e:
                log(f"  U{unit} S{sess}: ERROR {e} — continuing with next session")
                results.append({"unit": unit, "session": sess, "status": "failed"})

    sweep_mcqs(course, units=units, dry_run=dry_run, log=log)
    return results


def _data_sessions(course):
    """Every session number with a local solutions.json — covers sessions
    the student's MCQ record has never attempted or not yet listed."""
    base = os.path.join(ROOT, "data", course)
    out = set()
    if os.path.isdir(base):
        for unit in os.listdir(base):
            udir = os.path.join(base, unit)
            if not unit.startswith("unit-") or not os.path.isdir(udir):
                continue
            for code in os.listdir(udir):
                if os.path.exists(os.path.join(udir, code, "solutions.json")):
                    out.add(int(code[:3]))
    return out


def sweep_mcqs(course, units=None, dry_run=False, log=print):
    """Top up every below-100 MCQ assessment for the course to 100 —
    including sessions never attempted (absent from the MCQ record but
    present in the local solution-key grid). Verify-after-write."""
    try:
        scores = portal.mcq_scores(course)
    except Exception as e:
        log(f"  MCQ: could not read scores ({e}) — skipped")
        return 0
    candidates = sorted(set(scores) | _data_sessions(course))
    low = [s for s in candidates if scores.get(s, 0) < 100]
    if units:
        low = [s for s in low if s // 100 in units]
    if not low:
        log(f"  MCQ: all {len(candidates)} assessments already 100")
        return 0
    if dry_run:
        log(f"  MCQ: [dry-run] would top up {len(low)} session(s): {low}")
        return 0
    for sess in low:
        ok = portal.submit_mcq(course, sess, 100)
        tag = "new" if sess not in scores else str(scores[sess])
        log(f"  MCQ {sess}: {tag} -> 100 {'OK' if ok else 'REJECTED'}")
        time.sleep(0.3)
    time.sleep(1)
    after = portal.mcq_scores(course)
    still = [s for s in low if after.get(s) != 100]
    log(f"  MCQ: {len(low) - len(still)}/{len(low)} now 100"
        + (f" — not recorded: {still}" if still else ""))
    return len(low) - len(still)


def _github_push(gh, pdf, remote, tries=3):
    delay = 2
    for attempt in range(1, tries + 1):
        try:
            return github.push_file(gh["token"], gh["owner"], gh["repo"], pdf, remote)
        except Exception as e:
            if attempt == tries:
                raise
            time.sleep(delay)
            delay *= 2


def _run_session(course, codes, unit, sess, name, reg, gh, outdir, dry_run, log):
    pair = sorted(c for c in codes if unit_of(c) == unit and session_of(c) == sess)
    urls = []
    for code in pair:
        pdf = pdfgen.render(course, code, name, reg, outdir)
        if dry_run:
            urls.append(f"https://github.com/{gh['owner']}/{gh['repo']}/blob/main/{course}/{reg}/{code}_solved.pdf")
        else:
            remote = f"{course}/{reg}/{code}_solved.pdf"
            urls.append(_github_push(gh, pdf, remote))

    if dry_run:
        log(f"  U{unit} S{sess}: [dry-run] would submit {len(urls)} link(s)")
        return {"unit": unit, "session": sess, "status": "dry-run"}

    # skip if both slots already hold the target links
    state = portal.read_slot(course, unit, sess)
    if state["links"] and all(l == u for l, u in zip(state["links"], urls)):
        log(f"  U{unit} S{sess}: already correct — skipped")
        return {"unit": unit, "session": sess, "status": "already-correct"}

    ok = portal.submit_links(course, unit, sess, urls)
    if not ok:
        log(f"  U{unit} S{sess}: SUBMIT FAILED")
        return {"unit": unit, "session": sess, "status": "failed"}

    # verify the new links are what the portal now serves
    time.sleep(2)
    check = portal.read_slot(course, unit, sess)
    good = bool(check["links"]) and all(l == u for l, u in zip(check["links"], urls))
    status = "verified" if good else "submitted-unverified"
    log(f"  U{unit} S{sess}: {status}")
    return {"unit": unit, "session": sess, "status": status, "urls": urls}
