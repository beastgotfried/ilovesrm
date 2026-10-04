"""Pipeline: boilerplate db -> personalized PDF -> GitHub -> portal link -> verify.

Idempotent: a session is skipped entirely when it is already complete —
MCQ at 100 AND both SLO PDF slots holding correct links — so re-runs cost
nothing. Partially done sessions only fill what is missing or wrong.

Caching (three layers):
  portal   — one whole-course status snapshot per course (portal_http),
             invalidated on every successful write
  render   — pdfgen skips PDF rebuilds when boilerplate+identity are unchanged
  push     — a per-student manifest remembers content-hash -> GitHub URL, so
             unchanged PDFs never hit the GitHub API at all
Safety: every portal write is guarded by an on-screen course-code check.
"""
import hashlib
import json
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

    # snapshot MCQ scores once — used for the per-session skip check
    scores = {}
    if not dry_run:
        try:
            scores = portal.mcq_scores(course)
        except Exception as e:
            log(f"  MCQ scores unreadable ({e}) — skip check will use links only")
    results = []

    if not sessions:
        log(f"  no boilerplate for {course} — worksheets skipped")
    else:
        outdir = os.path.join(ROOT, "build", course, reg)
        skipped = 0
        for unit, sess in sessions:
            try:
                r = _run_session(course, codes, unit, sess, name, reg,
                                 gh, outdir, dry_run, log, scores)
                results.append(r)
                skipped += r["status"] in ("already-complete", "already-correct")
            except Exception as e:
                log(f"  U{unit} S{sess}: ERROR {e} — continuing with next session")
                results.append({"unit": unit, "session": sess, "status": "failed"})
        if skipped:
            log(f"  {skipped}/{len(sessions)} session(s) already complete — skipped")

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


def _student_identity(name, reg):
    """Git author/committer for a student's commits — the repo history shows
    the worksheet owner (their SRM email), not the token account."""
    words = (name or "").split()
    # portal FULL_NAME often arrives doubled ("ANKUSH WADEHRA ANKUSH WADEHRA")
    if len(words) > 1 and len(words) % 2 == 0 and \
            words[:len(words)//2] == words[len(words)//2:]:
        words = words[:len(words)//2]
    pretty = " ".join(w.capitalize() for w in words)
    ident = {"name": pretty or reg, "email": f"{(reg or 'student').lower()}@srmist.edu.in"}
    return ident, dict(ident)


def _github_push(gh, pdf, remote, author=None, committer=None, tries=3):
    delay = 2
    for attempt in range(1, tries + 1):
        try:
            return github.push_file(gh["token"], gh["owner"], gh["repo"], pdf,
                                    remote, author=author, committer=committer)
        except Exception as e:
            if attempt == tries:
                raise
            time.sleep(delay)
            delay *= 2


def _load_manifest(outdir):
    path = os.path.join(outdir, "_push_manifest.json")
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_manifest(outdir, manifest):
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "_push_manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)


def _push_cached(gh, pdf, remote, manifest, author=None, committer=None):
    """Push pdf to GitHub unless the manifest says this exact content is
    already hosted — then reuse the recorded URL with zero network calls."""
    with open(pdf, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    hit = manifest.get(remote)
    if hit and hit.get("sha256") == digest:
        return hit["url"]
    url = _github_push(gh, pdf, remote, author=author, committer=committer)
    manifest[remote] = {"sha256": digest, "url": url}
    return url


def _expected_url(gh, course, reg, code):
    return (f"https://github.com/{gh['owner']}/{gh['repo']}"
            f"/blob/main/{course}/{reg}/{code}_solved.pdf")


def _run_session(course, codes, unit, sess, name, reg, gh, outdir, dry_run, log,
                 scores=None):
    pair = sorted(c for c in codes if unit_of(c) == unit and session_of(c) == sess)
    expected = [_expected_url(gh, course, reg, c) for c in pair]
    sess_int = unit * 100 + sess
    mcq = (scores or {}).get(sess_int, 0)

    if dry_run:
        log(f"  U{unit} S{sess}: [dry-run] would submit {len(expected)} link(s)")
        return {"unit": unit, "session": sess, "status": "dry-run"}

    # ---- skip check BEFORE any render/upload work -------------------------
    state = portal.read_slot(course, unit, sess)
    links = state["links"]                      # [slo1_url|None, slo2_url|None]
    states = state.get("states") or ["?", "?"]
    both_filled = all(links)
    exact = both_filled and all(l == u for l, u in zip(links, expected))

    if exact and mcq >= 100:
        log(f"  U{unit} S{sess}: MCQ 100 + PDFs linked — skipped (already-complete)")
        return {"unit": unit, "session": sess, "status": "already-complete"}
    if exact:
        log(f"  U{unit} S{sess}: PDFs already correct (MCQ {mcq} — sweep will top up)")
        return {"unit": unit, "session": sess, "status": "already-correct"}
    if both_filled and mcq >= 100 and all(s == "Verified" for s in states):
        # verified slots are GREEN — never touch them, whatever the links are
        log(f"  U{unit} S{sess}: MCQ 100 + verified PDF slots — skipped (untouched)")
        return {"unit": unit, "session": sess, "status": "already-complete"}

    # ---- fill only what is missing or WRONG -------------------------------
    # a slot needs work when it is empty OR holds a link that is not the
    # expected one AND the slot is not Verified (green slots stay untouched)
    todo, urls = [], list(links)
    manifest = _load_manifest(outdir)
    author, committer = _student_identity(name, reg)
    dirty = False
    for i, code in enumerate(pair):
        if i < len(links) and links[i] == expected[i]:
            continue                            # already correct
        if i < len(states) and states[i] == "Verified":
            if i < len(links) and links[i] and links[i] != expected[i]:
                log(f"  U{unit} S{sess} SLO{i+1}: VERIFIED slot with unexpected link — left untouched")
            continue                            # green rule: never modify
        todo.append(i)
        pdf = pdfgen.render(course, code, name, reg, outdir)
        urls[i] = _push_cached(gh, pdf, f"{course}/{reg}/{code}_solved.pdf",
                               manifest, author=author, committer=committer)
        dirty = True
    if dirty:
        _save_manifest(outdir, manifest)

    if not todo:
        log(f"  U{unit} S{sess}: PDFs done (MCQ {mcq} — sweep will top up)")
        return {"unit": unit, "session": sess, "status": "already-correct"}

    # submit ONLY the slots being (re)filled — never re-touch the rest
    submit_urls = [urls[i] if i in todo else None for i in range(len(pair))]
    ok = portal.submit_links(course, unit, sess, submit_urls)
    if not ok:
        log(f"  U{unit} S{sess}: SUBMIT FAILED")
        return {"unit": unit, "session": sess, "status": "failed"}

    # verify the new links are what the portal now serves
    time.sleep(2)
    check = portal.read_slot(course, unit, sess)
    good = bool(check["links"]) and all(l == u for l, u in zip(check["links"], urls))
    status = "verified" if good else "submitted-unverified"
    log(f"  U{unit} S{sess}: {status} (filled SLO {', '.join(str(i+1) for i in todo)})")
    return {"unit": unit, "session": sess, "status": status, "urls": urls}
