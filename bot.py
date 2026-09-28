#!/usr/bin/env python3
"""ecurricula-bot — autonomous solved-worksheet pipeline.

Runs anywhere Python 3 runs. No browser, no extension, no daemon.
Auth: paste the portal JWT once (copy(localStorage.jwtToken) in any logged-in
browser) — cached in bot_config.json and auto-refreshed thereafter.
The GitHub token is NEVER cached: it is asked on every run.
Optional: a 2captcha API key enables full username+password login.

Usage:
    python bot.py                 # interactive
    python bot.py --dry-run       # render + plan only, no portal/GitHub writes
"""
import getpass
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
CONFIG = os.path.join(ROOT, "bot_config.json")

from core import portal, pdfgen, pipeline


def load_config():
    if os.path.exists(CONFIG):
        with open(CONFIG) as f:
            return json.load(f)
    return {}


def save_config(cfg):
    with open(CONFIG, "w") as f:
        json.dump(cfg, f, indent=2)


def scrub_cached_github_token(cfg):
    """Older versions cached the GitHub PAT in bot_config.json — remove it."""
    gh = cfg.get("github")
    if gh and gh.pop("token", None) is not None:
        save_config(cfg)
        print("  (removed previously cached GitHub token from bot_config.json)")


def portal_login(cfg):
    """Ensure an authenticated portal session. Returns identity dict."""
    # 1. cached token, auto-refreshed
    if portal.up():
        who = portal.detect_identity()
        if who["reg"]:
            return who

    print("No usable portal session cached.")
    print("  [1] paste JWT  — log in on any browser, devtools console: "
          "copy(localStorage.jwtToken)")
    print("  [2] username + password (needs 2captcha key in bot_config.json "
          "as captcha_key)")
    choice = input("Choice [1]: ").strip() or "1"

    if choice == "2":
        user = input("Portal registration no (RA...): ").strip()
        pw = getpass.getpass("Portal password: ")
        key = cfg.get("captcha_key")
        who = portal.login_with_password(user, pw, key)
    else:
        token = getpass.getpass("JWT token: ").strip()
        who = portal.login_with_token(token)

    return {"reg": who["reg"], "name": who["name"], "logged_in": True}


def get_github(cfg):
    """Ask for the GitHub token on EVERY run — never read it from, or write
    it to, the config file. Only owner/repo defaults persist."""
    from core import github
    gh = cfg.get("github", {})
    while True:
        token = getpass.getpass("GitHub personal access token (repo scope): ").strip()
        if not token:
            print("  token cannot be empty — try again")
            continue
        try:
            owner = github.whoami(token)
            break
        except Exception as e:
            print(f"  GitHub rejected that token: {e} — try again")
    default_repo = gh.get("repo") or "course-worksheets"
    repo = input(f"GitHub repo name [{default_repo}]: ").strip() or default_repo
    cfg["github"] = {"owner": owner, "repo": repo}  # token deliberately NOT saved
    save_config(cfg)
    print(f"  GitHub: pushing as {owner} to {owner}/{repo}")
    return {"token": token, "owner": owner, "repo": repo}


def parse_multi(text, lo, hi):
    """Parse '1,2,4' / '1 2 4' / '1-3' into a sorted unique list in [lo, hi].
    Blank or 'all' -> None (meaning everything). Raises ValueError otherwise."""
    text = text.strip().lower()
    if not text or text == "all":
        return None
    out = set()
    for part in re.split(r"[,\s]+", text):
        if not part:
            continue
        try:
            if "-" in part:
                a, b = part.split("-", 1)
                out.update(range(int(a), int(b) + 1))
            else:
                out.add(int(part))
        except ValueError:
            raise ValueError(f"cannot parse {part!r}")
    if not out:
        return None
    bad = sorted(n for n in out if not lo <= n <= hi)
    if bad:
        raise ValueError(f"out of range: {bad} (valid {lo}-{hi})")
    return sorted(out)


def pick_courses():
    """List every course on the account, numbered; accept multi-select."""
    courses = portal.list_courses()
    if not courses:
        sys.exit("portal returned no courses for this account")
    print("  Courses on your account:")
    for i, c in enumerate(courses, 1):
        code = c.get("COURSE_CODE") or c.get("_id")
        name = c.get("COURSE_NAME") or ""
        n = len(pdfgen.available_codes(code))
        mark = f"{n} worksheets in db" if n else "no boilerplate db"
        print(f"    [{i}] {code}  {name}  ({mark})")
    while True:
        raw = input("Courses to complete (e.g. 1,3 or 'all') [all]: ").strip()
        try:
            picks = parse_multi(raw, 1, len(courses))
        except ValueError as e:
            print(f"  invalid: {e} — try again")
            continue
        idx = picks or list(range(1, len(courses) + 1))
        chosen = [courses[i - 1] for i in idx]
        codes = [c.get("COURSE_CODE") or c.get("_id") for c in chosen]
        print(f"  selected: {', '.join(codes)}")
        return codes


def pick_units(course_codes):
    """One units prompt applied to every selected course. Multi-select."""
    avail = sorted({int(c[0]) for code in course_codes
                    for c in pdfgen.available_codes(code)})
    if not avail:
        return None
    while True:
        raw = input(f"Units (available: {', '.join(map(str, avail))}; "
                    f"e.g. 1,2) [all]: ").strip()
        try:
            picks = parse_multi(raw, min(avail), max(avail))
        except ValueError as e:
            print(f"  invalid: {e} — try again")
            continue
        units = picks or avail
        print(f"  units: {', '.join(map(str, units))}")
        return units


def main():
    dry = "--dry-run" in sys.argv
    print("== ecurricula-bot ==")

    cfg = load_config()
    scrub_cached_github_token(cfg)
    who = portal_login(cfg)
    print(f"  Logged in: {who['name']} ({who['reg']})")

    gh = {"owner": "dry", "repo": "dry"} if dry else get_github(cfg)

    courses = pick_courses()
    units = pick_units(courses)

    for course in courses:
        print(f"\n== {course} ==")
        results = pipeline.run_course(course, who["name"], who["reg"], gh,
                                      units=units, dry_run=dry)
        ok = sum(1 for r in results if r["status"] in ("verified", "already-correct"))
        warn = sum(1 for r in results if r["status"] == "submitted-unverified")
        bad = [r for r in results if r["status"] == "failed"]
        print(f"  summary: {ok} ok, {warn} submitted-unverified, {len(bad)} failed")
        for r in bad:
            print(f"    FAILED: U{r['unit']} S{r['session']}")

    print("\nDone.")


if __name__ == "__main__":
    main()
