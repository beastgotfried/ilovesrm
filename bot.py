#!/usr/bin/env python3
"""ecurricula-bot — autonomous solved-worksheet pipeline.

Prereqs: Chrome with WebBridge extension, logged into the eCurricula portal
(any profile — the bot reads name + reg no from the live session).

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

    if not portal.up():
        sys.exit("WebBridge daemon not reachable (127.0.0.1:10086). Start Chrome with the extension.")

    who = portal.detect_identity()
    if not who["logged_in"] or not who["reg"]:
        sys.exit("No logged-in portal session detected in the WebBridge tab. Log in first.")
    print(f"  Logged in: {who['name']} ({who['reg']})")

    courses = [d for d in os.listdir(os.path.join(ROOT, "db"))]
    print("  Boilerplate database:")
    for c in courses:
        print(f"    {c}: {len(pdfgen.available_codes(c))} worksheets")

    cfg = load_config()
    gh = None if dry else get_github(cfg)
    if dry:
        gh = {"owner": "dry", "repo": "dry"}

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
