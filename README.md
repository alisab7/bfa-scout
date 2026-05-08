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
