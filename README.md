# ecurricula-bot

Autonomous solved-worksheet pipeline for the SRM eCurricula portal.
Boilerplate answer DB → personalized PDF → GitHub hosting → portal link submission → verification. No manual steps.

## Prereqs
- Python 3 — that's it. No browser, no extension, no daemon. The bot talks to
  the portal's REST API directly (`core/portal_http.py`).
- Portal auth (one of):
  - **JWT paste (default)**: log into the portal in any browser, devtools
    console → `copy(localStorage.jwtToken)`, paste into the bot. Cached in
    `bot_config.json` and auto-refreshed via `/curricula/gettoken`.
  - **Username + password**: the portal enforces hCaptcha server-side, so this
    path needs a 2captcha API key stored as `captcha_key` in `bot_config.json`.
- A GitHub personal access token (repo scope) for whoever hosts the PDFs

## Run
```
python bot.py            # interactive: picks course, runs unattended
python bot.py --dry-run  # render + plan only, zero writes
```

On first run it asks for the portal token and GitHub token once and stores
them in `bot_config.json`.

## What it does per session
1. Renders `db/<course>/<code>.json` → PDF with the logged-in student's name + reg no (reportlab)
2. Pushes to `github.com/<owner>/<repo>/<course>/<reg>/<code>_solved.pdf` (Contents API; skips unchanged files)
3. Submits both SLO links via `student/session/submitlink` (same payload the portal UI sends)
4. Re-reads via `student/session/getsessionstatus` and confirms the portal now serves the GitHub URL

## Safety
- **Course binding**: all reads/writes carry the course's own `COURSE_INFO`
  object (incl. its `BATCH_ID`) fetched from the account's course list — a
  wrong-course write is impossible even though session codes repeat across courses
- **Idempotent**: slots already holding the correct link are skipped
- **Verify-after-write**: every submit is re-read before being counted as done

## Boilerplate database
| Course | Code | Coverage |
|---|---|---|
| Universal Human Values II | 21LEM202T | U1–U5, all 90 worksheets |
| Advanced Programming Practice | 21CSC203P | U1–U2 full, U3 S1–S7 (62) |
| Computer Organization & Architecture | 21CSS201T | U1–U3 full (72) |

Add new content by dropping `<code>.json` (`{"title":..., "sections":[[heading, [lines]]]}`)
into `db/<course>/` — code = unit+session+SLO, e.g. `3081` = U3 S8 SLO1.

## Layout
```
bot.py                  CLI
core/portal.py          canonical portal client (re-exports portal_http)
core/portal_http.py     pure-HTTP REST client — auth, courses, read, submit
core/portal_webbridge.py legacy DOM/WebBridge client (reference only)
core/pdfgen.py          PDF renderer
core/github.py          GitHub Contents API hosting
core/pipeline.py        orchestrator
db/                     boilerplate answers (224 worksheets)
build/                  rendered PDFs per student
seed_db.py              one-time importer from legacy answers_*.py
```

MCQs are intentionally out of scope for now (questions reshuffle per attempt; needs a question bank — later phase).
