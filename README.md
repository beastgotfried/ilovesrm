# ecurricula-bot

Autonomous solved-worksheet pipeline for the SRM eCurricula portal.
Boilerplate answer DB → personalized PDF → GitHub hosting → portal link submission → verification. No manual steps.

## Prereqs
- Chrome running with the WebBridge extension (daemon on 127.0.0.1:10086), tab session `srm-curriculum`
- The portal logged in (any profile — identity is auto-detected from the session)
- A GitHub personal access token (repo scope) for whoever hosts the PDFs

## Run
```
python bot.py            # interactive: picks course, runs unattended
python bot.py --dry-run  # render + plan only, zero writes
```

On first run it asks for the GitHub token once and stores it in `bot_config.json`.

## What it does per session
1. Renders `db/<course>/<code>.json` → PDF with the logged-in student's name + reg no (reportlab)
2. Pushes to `github.com/<owner>/<repo>/<course>/<reg>/<code>_solved.pdf` (Contents API; skips unchanged files)
3. Opens the session arc on the portal, pastes both SLO links, clicks UPDATE
4. Re-reads the slot and confirms the portal now serves the GitHub URL

## Safety
- **Course guard**: every portal write first verifies the target course code is on screen (arc IDs repeat across courses — this prevents cross-course contamination)
- **Idempotent**: slots already holding the correct link are skipped
- **Retries**: portal render flakes are retried with backoff (up to 4×)

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
bot.py            CLI
core/portal.py    WebBridge client (identity, course open, read, submit, guard)
core/pdfgen.py    PDF renderer
core/github.py    GitHub Contents API hosting
core/pipeline.py  orchestrator
db/               boilerplate answers (224 worksheets)
build/            rendered PDFs per student
seed_db.py        one-time importer from legacy answers_*.py
```

MCQs are intentionally out of scope for now (questions reshuffle per attempt; needs a question bank — later phase).
