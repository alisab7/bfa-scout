# Cowork Session: BFA-Scout Phase 0 Cleanup Pass

## Context

Phase 0 scaffold built the project skeleton, but several issues surfaced during local verification that need fixing before Phase 1 begins. The database itself is already clean — schema dropped, recreated under user `bfa` with `ENCODING 'UTF8'`, all seeds loaded (8 position_groups, 26 positions, 4 criteria_categories, 39 criteria, 200 position_group_criteria). The remaining work is in the **files**: documentation drift, a Jinja template bug, the unfixed `schema.sql` view definition, and CHANGELOG/PROJECT updates.

**Working folder:** `D:\BFA-Scout` (do NOT touch `D:\BFA-Analytics` or `D:\BFA-Analytics-AWS`).

**Local environment (already established — do not change):**
- PostgreSQL 15 native install (NOT Docker)
- Database: `bfa_scout`, owner `bfa`, password `bfa2025`
- DATABASE_URL: `postgresql://bfa:bfa2025@localhost:5432/bfa_scout`
- Python venv at `D:\BFA-Scout\.venv`, dependencies installed
- Flask runs successfully — `/health` returns `{"db":"connected","status":"ok"}`

## Goal

End state after this session:
1. `/` route returns 200 with no Jinja errors
2. `schema.sql` file is consistent with what's actually in the live DB (so a fresh `psql -f schema.sql` on a new machine works end-to-end)
3. README, `.env.example`, PROJECT.md, CHANGELOG.md all reflect the native-dev workflow we've adopted
4. Docker files stay in place but README documents that they are optional/future-use
5. Full Phase 0 acceptance checklist passes against the real running Flask process

## Issue 1 — Jinja error in `app/templates/base.html`

The earlier Phase 0 session put a Jinja expression inside an HTML comment, expecting it to be ignored:

```html
<!-- Phase 1: {{ current_user.role | upper }} -->
```

Jinja still evaluates expressions inside `<!-- -->` because Jinja runs before HTML rendering. Result: `jinja2.exceptions.UndefinedError: 'current_user' is undefined` whenever any page renders.

**Fix:** Replace the line with a Jinja-native comment:

```html
{# Phase 1: render current_user.role badge here when auth is wired up #}
```

The visible placeholder (`&mdash;` etc.) on the next line stays as-is. Search the entire `app/templates/` tree for any other instance of `{{` inside `<!-- -->` and replace those too — same fix.

## Issue 2 — `schema.sql` still has the GROUP BY bug

The live DB has the corrected view (we patched it manually), but the file on disk still has the broken version. A fresh `psql -f schema.sql` on a new machine would fail.

**Fix:** Find near the bottom of `schema.sql`:
```sql
GROUP BY pg.code
ORDER BY pg.sort_order;
```
Change to:
```sql
GROUP BY pg.code, pg.sort_order
ORDER BY pg.sort_order;
```

After the change, sanity-check by running:
```powershell
$env:PGPASSWORD = "bfa2025"
$env:PGCLIENTENCODING = "UTF8"
psql -U bfa -d bfa_scout -f D:\BFA-Scout\schema.sql
```
This should run end-to-end with only `NOTICE: relation already exists, skipping` warnings — **no `ERROR` lines**. (It's idempotent — every CREATE uses `IF NOT EXISTS`, every INSERT uses `ON CONFLICT DO NOTHING`.)

## Issue 3 — `.env.example` is Docker-only, doesn't match native workflow

Current file is shaped for Docker:
```
DB_PASSWORD=change_me
SECRET_KEY=generate_a_long_random_string_here
FLASK_ENV=development
```

**Fix:** Replace with the unified version that supports both native and Docker, with native as the documented default:

```
# === Native dev (recommended) ===
# Flask reads this directly via os.environ.get('DATABASE_URL')
DATABASE_URL=postgresql://bfa:CHANGE_ME_TO_REAL_PASSWORD@localhost:5432/bfa_scout

# Generate with: python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=CHANGE_ME_TO_64_CHAR_HEX_STRING

FLASK_ENV=development
UPLOAD_FOLDER=./uploads

# === Initial admin (consumed once on first boot, ignored thereafter) ===
INITIAL_ADMIN_EMAIL=admin@bfa.bh
INITIAL_ADMIN_PASSWORD=ChangeMeOnFirstLogin!

# === Docker only (ignored in native dev) ===
# Used by docker-compose.yml to set the postgres container password.
# DATABASE_URL above is what Flask actually reads in both modes.
DB_PASSWORD=CHANGE_ME_TO_REAL_PASSWORD
```

## Issue 4 — README needs a native-dev quickstart

Current README likely has only Docker instructions. Rewrite as **native first, Docker as alternative**.

Replace the contents of `README.md` with:

```markdown
# BFA Scouting & Evaluation System

Standalone Flask + PostgreSQL platform for the Bahrain Football Association's
National Team Committee. Mobile-first scouting evaluations fused with Wyscout
statistics, deployed to DigitalOcean (AWS migration later).

See `project_brief.md` for full architecture, `PROJECT.md` for current phase,
and `CHANGELOG.md` for version history.

## Quickstart — Native (recommended for dev)

Prerequisites: Python 3.11, PostgreSQL 15 running locally.

```powershell
# 1. Clone or cd into project
cd D:\BFA-Scout

# 2. Create database (one time, as postgres superuser)
psql -U postgres -c "CREATE USER bfa WITH PASSWORD 'choose_a_password';"
psql -U postgres -c "CREATE DATABASE bfa_scout OWNER bfa ENCODING 'UTF8';"

# 3. Load schema (as bfa, with UTF-8 encoding for Arabic seed data)
$env:PGPASSWORD = "choose_a_password"
$env:PGCLIENTENCODING = "UTF8"
psql -U bfa -d bfa_scout -f schema.sql

# 4. Verify schema (should print 8 / 26 / 4 / 39 / 200)
psql -U bfa -d bfa_scout -c "SELECT 'position_groups' AS t, COUNT(*) FROM position_groups UNION ALL SELECT 'positions', COUNT(*) FROM positions UNION ALL SELECT 'criteria_categories', COUNT(*) FROM criteria_categories UNION ALL SELECT 'criteria', COUNT(*) FROM criteria UNION ALL SELECT 'position_group_criteria', COUNT(*) FROM position_group_criteria;"

# 5. Python venv + dependencies
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 6. Configure environment
copy .env.example .env
# Edit .env — set DATABASE_URL password, generate SECRET_KEY, set INITIAL_ADMIN_*
# Generate SECRET_KEY: python -c "import secrets; print(secrets.token_hex(32))"

# 7. Run
flask --app wsgi run --debug
```

Verify in browser or with curl:
- http://localhost:5000/health → `{"db":"connected","status":"ok"}`
- http://localhost:5000/ → BFA Scouting landing page

### Daily workflow

Each new PowerShell session:
```powershell
cd D:\BFA-Scout
.\.venv\Scripts\Activate.ps1
flask --app wsgi run --debug
```

## Quickstart — Docker (optional, used at production deploy)

The repo includes `Dockerfile` and `docker-compose.yml` for production deployment
to DigitalOcean (and later AWS). For local dev, native is faster. To run via Docker:

```powershell
copy .env.example .env
# Edit .env — set DB_PASSWORD, SECRET_KEY, INITIAL_ADMIN_*
docker compose up --build
```

## Tech stack

- Flask 3.x + Python 3.11
- PostgreSQL 15 (native locally, managed on DigitalOcean in production)
- Jinja + HTMX + Alpine.js + Tailwind (CDN)
- Flask-Login + PBKDF2 (Phase 1)
- WeasyPrint (Phase 6 reports)
- Google Gemini API (Phase 7 AI features)

## Project structure

```
bfa-scout/
├── app/                    # Flask application
│   ├── __init__.py         # Factory + 8 blueprint registrations
│   ├── config.py           # Env-driven config
│   ├── db.py               # psycopg2 connection pool
│   ├── auth/               # Phase 1
│   ├── players/            # Phase 3
│   ├── evaluations/        # Phase 5
│   ├── criteria/           # Phase 2
│   ├── wyscout/            # Phase 4
│   ├── reports/            # Phase 6
│   ├── ai/                 # Phase 7
│   ├── api/
│   ├── templates/
│   └── static/
├── schema.sql              # Full PostgreSQL DDL + seeds
├── project_brief.md        # Architecture + locked decisions
├── PROJECT.md              # Current phase + status
├── CHANGELOG.md
├── Dockerfile              # For production deploy
├── docker-compose.yml      # For production deploy
├── requirements.txt
├── .env.example
└── wsgi.py                 # Gunicorn entry point
```

## Roadmap

See `project_brief.md` for full phase plan. Current phase: see `PROJECT.md`.
```

## Issue 5 — Update `PROJECT.md`

Replace contents with:

```markdown
# BFA-Scout — Current Status

**See `project_brief.md` for full architecture, locked decisions, and roadmap.**

## Current phase

**Phase 0: Project scaffold — COMPLETE**

All Phase 0 acceptance criteria met. Database clean, Flask runs, all 8 blueprint
stubs respond, dynamic-form mechanism verified via `v_position_group_form_counts`.

## Next phase

**Phase 1: Auth & RBAC** — Flask-Login + PBKDF2, 4 roles (admin,
technical_director, scout, viewer), user CRUD, last-active-admin guard, audit log.

## Local environment

- PostgreSQL 15 native, database `bfa_scout` owned by `bfa`
- Python 3.11 venv at `.venv`
- Flask reads `DATABASE_URL` from `.env`

## Working agreement

| Tool | Use for |
|---|---|
| **claude.ai** | Planning, prompt-writing, schema edits, triage |
| **Cowork** | Build sessions (Phases 0–8), refactors |
| **Claude Code** | Local debug loops |

When starting a Cowork session, paste current `PROJECT.md` + `CHANGELOG.md`
+ `project_brief.md` for state continuity.
```

## Issue 6 — Update `CHANGELOG.md`

Append (do not bump major version — this is still v0.0.x scaffold work):

```markdown
## v0.0.2 — Phase 0 cleanup

### Fixed
- `app/templates/base.html`: Jinja expression `{{ current_user.role | upper }}` was inside
  an HTML comment, causing `UndefinedError` on every page load. Switched to Jinja-native
  `{# ... #}` comment syntax.
- `schema.sql`: `v_position_group_form_counts` view violated PostgreSQL strict GROUP BY —
  added `pg.sort_order` to the GROUP BY clause. (Live DB was patched manually earlier.)

### Changed
- `.env.example`: rewritten for native-dev workflow as the default path.
  `DATABASE_URL` is now the canonical Flask config var. `DB_PASSWORD` retained
  for optional Docker use only.
- `README.md`: native-dev quickstart promoted to primary path. Docker quickstart
  retained as optional / production-deploy path.
- `PROJECT.md`: marked Phase 0 complete, pointed at Phase 1 next.

### Notes
- Database state was reset during cleanup (DROP DATABASE + CREATE DATABASE)
  to fix table ownership (was `postgres`, now `bfa`) and encoding (now UTF-8
  with `PGCLIENTENCODING=UTF8` on load). All seeds reloaded cleanly.
```

## Verification protocol

After all file changes, verify against the **real running Flask process** —
NOT `flask.test_client()`. (test_client re-imports the module and hides
stale-process bugs we hit 3× in BFA-Analytics.)

```powershell
cd D:\BFA-Scout
.\.venv\Scripts\Activate.ps1
$env:PGPASSWORD = "bfa2025"
$env:PGCLIENTENCODING = "UTF8"

# Verify schema.sql is now idempotent and clean
psql -U bfa -d bfa_scout -f schema.sql
# Expected: zero ERROR lines

# Verify view works
psql -U bfa -d bfa_scout -c "SELECT * FROM v_position_group_form_counts;"
# Expected: 8 rows, each criteria_count >= 18

# Start Flask (in this terminal)
flask --app wsgi run --debug
```

In a second PowerShell window:

```powershell
# 1. Health check
curl http://localhost:5000/health
# Expected: {"db":"connected","status":"ok"}

# 2. Landing page (was broken — must work now)
curl http://localhost:5000/ | Select-String "BFA Scouting"
# Expected: line containing "BFA Scouting"

# 3. All 8 blueprint stubs respond (TODO message in each)
curl http://localhost:5000/auth/
curl http://localhost:5000/players/
curl http://localhost:5000/evaluations/
curl http://localhost:5000/criteria/
curl http://localhost:5000/wyscout/
curl http://localhost:5000/reports/
curl http://localhost:5000/ai/
curl http://localhost:5000/api/
# Expected: each returns its TODO Phase X message
```

## Acceptance checklist (print at end of session)

- ✅ `app/templates/base.html` line 62 uses `{# ... #}` not `<!-- {{ ... }} -->`
- ✅ No other Jinja expressions remain inside HTML comments anywhere in `app/templates/`
- ✅ `schema.sql` view has `GROUP BY pg.code, pg.sort_order`
- ✅ Re-running `psql -f schema.sql` produces zero ERROR lines
- ✅ `.env.example` has `DATABASE_URL` as primary, `INITIAL_ADMIN_*` added
- ✅ `README.md` documents native-dev as primary, Docker as optional
- ✅ `PROJECT.md` marks Phase 0 complete
- ✅ `CHANGELOG.md` has v0.0.2 entry
- ✅ Live Flask process: `/health` returns 200 with `db: connected`
- ✅ Live Flask process: `/` returns 200 HTML containing "BFA Scouting"
- ✅ Live Flask process: all 8 blueprint stubs return their TODO message

## Hard rules

- ❌ Do NOT modify `Dockerfile` or `docker-compose.yml` (they're for production deploy)
- ❌ Do NOT delete the Docker files — they're staying for Phase 8
- ❌ Do NOT touch `D:\BFA-Analytics` or `D:\BFA-Analytics-AWS`
- ❌ Do NOT use `flask.test_client()` for verification — restart the Flask process and curl it
- ❌ Do NOT change the database password or DATABASE_URL — `bfa2025` is what's set, leave it
- ❌ Do NOT initialize git or commit — Ali will do `git init && git commit` from PowerShell after the session
- ✅ ALL verification against the real running Flask process via curl

## Out of scope (do NOT build in this session)

- Phase 1 auth (next session)
- Any business logic in blueprint stubs (they stay as placeholders)
- Tailwind build pipeline (CDN is fine for v1)
- Tests (Phase 2)
- Alembic migrations (Phase 1)

## Session discipline

- Target: 4–6 messages
- After every code change: restart Flask + curl real process to verify
- End with the full acceptance checklist printed (✅/❌ each)
- After session ends, Ali runs from PowerShell:
  ```powershell
  cd D:\BFA-Scout
  git init
  git add -A
  git commit -m "Phase 0: project scaffold + cleanup pass"
  ```
