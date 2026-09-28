#!/usr/bin/env python3
"""ecurricula-bot — autonomous solved-worksheet pipeline.

Runs anywhere Python 3 runs. No browser, no extension, no daemon.
Auth: paste the portal JWT once (copy(localStorage.jwtToken) in any logged-in
browser) — cached in bot_config.json and auto-refreshed thereafter.
Optional: a 2captcha API key enables full username+password login.

Usage:
    python bot.py                 # interactive
    python bot.py --dry-run       # render + plan only, no portal/GitHub writes
"""
import json, os, sys, getpass

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
    from core import github
    gh = cfg.get("github", {})
    token = gh.get("token")
    if not token:
        token = getpass.getpass("GitHub personal access token (repo scope): ").strip()
    owner = github.whoami(token)
    repo = gh.get("repo") or input("GitHub repo name [course-worksheets]: ").strip() or "course-worksheets"
    cfg["github"] = {"token": token, "owner": owner, "repo": repo}
    save_config(cfg)
    print(f"  GitHub: pushing as {owner} to {owner}/{repo}")
    return cfg["github"]


def main():
    dry = "--dry-run" in sys.argv
    print("== ecurricula-bot ==")

    cfg = load_config()
    who = portal_login(cfg)
    print(f"  Logged in: {who['name']} ({who['reg']})")

    courses = [d for d in os.listdir(os.path.join(ROOT, "db"))]
    print("  Boilerplate database:")
    for c in courses:
        print(f"    {c}: {len(pdfgen.available_codes(c))} worksheets")

    gh = {"owner": "dry", "repo": "dry"} if dry else get_github(cfg)

    pick = input(f"Course to complete [{courses[0]}] (or 'all'): ").strip() or courses[0]
    targets = courses if pick == "all" else [pick]
    if any(t not in courses for t in targets):
        sys.exit(f"unknown course {pick}; available: {courses}")

    units_in = input("Units [all available]: ").strip()
    units = [int(u) for u in units_in.split(",")] if units_in else None

    for course in targets:
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
