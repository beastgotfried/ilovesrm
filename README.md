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
- A GitHub personal access token (repo scope) for whoever hosts the PDFs.
  **Asked on every run — never stored.**

## Run
```
python bot.py            # interactive: pick courses + units, runs unattended
python bot.py --dry-run  # render + plan only, zero writes
```

The TUI lists every course on the account (numbered, with boilerplate
coverage) and accepts multi-selects for both courses and units:
`1,3` · `1 3 4` · `1-3` · `all`.

## What it does per session
1. Renders `data/<course>/unit-N/<code>/boilerplate.json` → PDF with the
   logged-in student's name + reg no (reportlab)
2. Pushes to `github.com/<owner>/<repo>/<course>/<reg>/<code>_solved.pdf`
   (Contents API; skips unchanged files)
3. Submits both SLO links via `student/session/submitlink` (same payload the
   portal UI sends)
4. Re-reads via `student/session/getsessionstatus` and confirms the portal now
   serves the GitHub URL
5. Sweeps the course's MCQ assessments: any score below 100 is topped up to
   100 (`student/session/mcq` — same trusted-client payload the UI sends)

## Safety
- **Course binding**: all reads/writes carry the course's own `COURSE_INFO`
  object (incl. its `BATCH_ID`) fetched from the account's course list — a
  wrong-course write is impossible even though session codes repeat across courses
- **Idempotent / completion-aware**: a session is skipped entirely when its
  MCQ is already 100 AND both SLO PDF slots hold links; slots holding the exact
  target link are never re-submitted, and filled (possibly verified) slots are
  never re-touched — only empty slots get a link
- **Verify-after-write**: every submit is re-read before being counted as done
- **Resilient**: transient portal failures (connection resets, 5xx) are
  retried with backoff; a failed session is logged and the run continues

## Data layout
```
data/<course>/unit-<N>/<code>/
    boilerplate.json   PDF answer-key boilerplate  {"title":..., "sections":[[heading,[lines]]]}
    solutions.json     100% solution key from the portal question bank
                       (MCQ options+answer, short Q+A, long Q+A, SLO titles)
```
`<code>` = unit+session+SLO, e.g. `3081` = U3 S8 SLO1.

### Boilerplate coverage (PDF answer keys)
| Course | Code | Coverage |
|---|---|---|
| Universal Human Values II | 21LEM202T | U1–U5, all 90 worksheets |
| Advanced Programming Practice | 21CSC203P | U1–U2 full, U3 S1–S7 (62) |
| Computer Organization & Architecture | 21CSS201T | U1–U3 full (72) |

### Solution keys (question bank, all courses on the account)
| Course | Code | Sessions |
|---|---|---|
| Advanced Programming Practice | 21CSC203P | U1–U3 (36) |
| Computer Organization & Architecture | 21CSS201T | U1–U3 (36) |
| Universal Human Values II | 21LEM202T | U1 (9) |
| Operating Systems | 21CSC202J | U1–U5 (57) |
| Data Structures & Algorithms | 21CSC201J | U1–U5 (53) |
| Maths (PDE) | 21MAB201T | U1–U5 (60) |

Refresh with `python3 fetch_solutions.py [COURSE ...]` — re-probes every
session grid cell, so newly published sessions are picked up automatically.

## Layout
```
bot.py                  CLI (multi-course / multi-unit TUI)
core/portal.py          canonical portal client (re-exports portal_http)
core/portal_http.py     pure-HTTP REST client — auth, courses, read, submit
core/portal_webbridge.py legacy DOM/WebBridge client (reference only)
core/pdfgen.py          PDF renderer
core/github.py          GitHub Contents API hosting
core/pipeline.py        orchestrator (per-session error isolation)
data/                   boilerplate + solution keys (see above)
build/                  rendered PDFs per student
seed_db.py              one-time importer from legacy answers_*.py
fetch_solutions.py      question-bank answer-key fetcher
```

## Notes
- The portal's MCQ assessment trusts the client-reported score
  (`student/session/mcq` accepts a percentage); the question bank in `data/`
  is the answer key if that ever gets validated server-side.
- Worksheet file downloads (slc/slppdf) ride the old `etecurricula` file
  store, which is frequently down; the REST API (`ktretecurricula`) is
  independent and stays up.
