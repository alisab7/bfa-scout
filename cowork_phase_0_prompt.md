# Cowork Session: BFA-Scout Phase 0 — Project Scaffold

## Context

We are starting a **brand new** Flask + PostgreSQL project for the Bahrain Football Association called **BFA-Scout**. It is fully independent from the existing BFA-Analytics project. Production target is DigitalOcean.

**Working folder:** `D:\BFA-Scout` (create fresh — do NOT touch `D:\BFA-Analytics` or `D:\BFA-Analytics-AWS`).

I am attaching three files to this session:
- `project_brief.md` — full project plan, locked decisions, roadmap (drop into repo root)
- `schema.sql` — complete PostgreSQL DDL with seed data (drop into repo root)
- This prompt

## Goal of this session

Stand up the project scaffold. End state: `docker-compose up` brings up Flask + Postgres, schema is initialized, seed data loaded, `GET /health` returns 200, landing page renders with BFA branding.

**No business logic yet.** Just the skeleton.

## Stack (locked — do not substitute)

- Python 3.11
- Flask 3.x, psycopg2-binary, python-dotenv, Flask-Login (install only, wire up Phase 1)
- Gunicorn (production), Flask dev server (dev)
- PostgreSQL 15
- Jinja + HTMX (via CDN) + Alpine.js (via CDN) + Tailwind CSS (via CDN — build pipeline later)
- Docker + docker-compose

## Files & folders to create

```
D:\BFA-Scout\
├── app/
│   ├── __init__.py              # Flask factory: create_app()
│   ├── config.py                # Config class loading from env
│   ├── db.py                    # psycopg2 connection pool + get_db() + init_db()
│   ├── auth/__init__.py         # Blueprint stub
│   ├── players/__init__.py      # Blueprint stub
│   ├── evaluations/__init__.py  # Blueprint stub
│   ├── criteria/__init__.py     # Blueprint stub
│   ├── wyscout/__init__.py      # Blueprint stub
│   ├── reports/__init__.py      # Blueprint stub
│   ├── ai/__init__.py           # Blueprint stub
│   ├── api/__init__.py          # Blueprint stub
│   ├── templates/
│   │   ├── base.html            # BFA branding shell
│   │   └── index.html           # Landing page
│   └── static/
│       ├── css/style.css        # BFA color tokens as CSS vars
│       └── manifest.json        # PWA manifest (placeholder)
├── migrations/                  # empty for now (Alembic in Phase 1)
├── tests/                       # empty for now
├── schema.sql                   # ATTACHED — copy in
├── project_brief.md             # ATTACHED — copy in
├── PROJECT.md                   # initialize: link to project_brief.md, current phase = 0
├── CHANGELOG.md                 # initialize with v0.0.1 entry
├── README.md                    # setup instructions
├── Dockerfile                   # Python 3.11-slim base
├── docker-compose.yml           # flask + postgres services
├── requirements.txt
├── .env.example
├── .gitignore
└── wsgi.py                      # gunicorn entry: from app import create_app; app = create_app()
```

## Implementation specifics

### `app/__init__.py`
```python
from flask import Flask
from .config import Config

def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(config_class)

    # DB
    from . import db
    db.init_app(app)

    # Blueprints (placeholders — each registered with a TODO route)
    from .auth import bp as auth_bp;               app.register_blueprint(auth_bp,        url_prefix='/auth')
    from .players import bp as players_bp;         app.register_blueprint(players_bp,     url_prefix='/players')
    from .evaluations import bp as evaluations_bp; app.register_blueprint(evaluations_bp, url_prefix='/evaluations')
    from .criteria import bp as criteria_bp;       app.register_blueprint(criteria_bp,    url_prefix='/criteria')
    from .wyscout import bp as wyscout_bp;         app.register_blueprint(wyscout_bp,     url_prefix='/wyscout')
    from .reports import bp as reports_bp;         app.register_blueprint(reports_bp,     url_prefix='/reports')
    from .ai import bp as ai_bp;                   app.register_blueprint(ai_bp,          url_prefix='/ai')
    from .api import bp as api_bp;                 app.register_blueprint(api_bp,         url_prefix='/api')

    # Root + health
    @app.route('/')
    def index():
        from flask import render_template
        return render_template('index.html')

    @app.route('/health')
    def health():
        from flask import jsonify
        try:
            conn = db.get_db()
            with conn.cursor() as cur:
                cur.execute('SELECT 1')
                cur.fetchone()
            return jsonify({'status': 'ok', 'db': 'connected'}), 200
        except Exception as e:
            return jsonify({'status': 'error', 'db': 'disconnected', 'error': str(e)}), 503

    return app
```

### `app/config.py`
- Load from environment via `os.environ.get`
- Variables: `DATABASE_URL`, `SECRET_KEY`, `FLASK_ENV`, `UPLOAD_FOLDER`
- **No fallback defaults for SECRET_KEY** — raise on missing in production
- Reasonable defaults only for `FLASK_ENV` (development) and `UPLOAD_FOLDER` (`./uploads`)

### `app/db.py`
- Use `psycopg2.pool.ThreadedConnectionPool` (min 1, max 10)
- `get_db()` returns a connection from the pool, attaches to `flask.g`
- Use `psycopg2.extras.RealDictCursor` as default cursor factory
- `close_db()` returns connection to pool on app teardown
- `init_db()` reads `schema.sql` and executes it (idempotent — schema uses `IF NOT EXISTS`)
- CLI command `flask init-db` to run init on demand

### Blueprint stubs (8 of them, all identical pattern)
```python
# app/auth/__init__.py
from flask import Blueprint
bp = Blueprint('auth', __name__)

@bp.route('/')
def index():
    return 'TODO: auth blueprint — Phase 1'
```

### `app/templates/base.html`
- Dark theme using CSS variables defined in `style.css`
- Cairo font from Google Fonts (with system fallback)
- HTMX from `https://unpkg.com/htmx.org@1.9.10`
- Alpine.js from `https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js` with `defer`
- Tailwind from `https://cdn.tailwindcss.com`
- Configure Tailwind theme inline to use CSS vars: `theme: { extend: { colors: { brand: 'var(--brand)', accent: 'var(--accent)' }}}`
- Top nav placeholder: BFA logo on left, role badge on right (filled in Phase 1)

### `app/static/css/style.css`
```css
:root {
  --brand:      #C8102E;
  --accent:     #B5924C;
  --bg:         #0E1116;
  --surface:    #1A1F26;
  --text:       #F2F2F2;
  --text-muted: #9CA3AF;
  --border:     #2A2F36;
}
body {
  background: var(--bg);
  color: var(--text);
  font-family: 'Cairo', system-ui, -apple-system, sans-serif;
}
```

### `app/templates/index.html`
- Extends `base.html`
- Hero: BFA crest placeholder, title "BFA Scouting & Evaluation", subtitle "National Team Committee Platform"
- Two CTAs: "Sign In" (links to `/auth/`) and "Learn more" (anchor)
- Mobile-first layout (centered, max-w-md on mobile, max-w-2xl on desktop)

### `Dockerfile`
- Base: `python:3.11-slim`
- Install system deps for psycopg2: `gcc`, `libpq-dev`
- Copy requirements, pip install
- Copy app
- CMD: `gunicorn --bind 0.0.0.0:5000 --workers 2 wsgi:app`

### `docker-compose.yml`
- Two services: `web` and `db`
- `db` uses `postgres:15-alpine`, exposes 5432 internally only, named volume `bfa_scout_pgdata`
- `web` builds from Dockerfile, exposes 5000 → host 5000, depends_on db with healthcheck
- DB env: `POSTGRES_DB=bfa_scout`, `POSTGRES_USER=bfa`, `POSTGRES_PASSWORD=${DB_PASSWORD}`
- Web env: `DATABASE_URL=postgresql://bfa:${DB_PASSWORD}@db:5432/bfa_scout`, `SECRET_KEY=${SECRET_KEY}`
- `db` healthcheck: `pg_isready -U bfa`
- Init script: mount `./schema.sql` to `/docker-entrypoint-initdb.d/01-schema.sql` so it runs on first DB startup

### `.env.example`
```
DB_PASSWORD=change_me
SECRET_KEY=generate_a_long_random_string_here
FLASK_ENV=development
```

### `.gitignore`
- `.env`
- `__pycache__/`, `*.pyc`
- `uploads/`
- `.venv/`, `venv/`
- `.idea/`, `.vscode/`
- `*.log`

### `PROJECT.md`
- Title, status (Phase 0 complete after this session)
- Reference: "See `project_brief.md` for full plan"
- Current phase, next phase
- Update this file at end of every Cowork session

### `CHANGELOG.md`
```
# Changelog

## v0.0.1 — Project scaffold (YYYY-MM-DD)
- Flask factory + 8 blueprint stubs
- PostgreSQL 15 schema initialized (13 tables, seed data)
- Docker Compose stack: web + db
- BFA dark-theme base template (HTMX + Alpine + Tailwind via CDN)
- Health check at /health
- Landing page at /
```

### `README.md`
Setup steps:
1. Copy `.env.example` to `.env` and fill in values
2. `docker-compose up --build`
3. Visit `http://localhost:5000`
4. `/health` should return `{"status":"ok","db":"connected"}`
5. `docker-compose exec db psql -U bfa -d bfa_scout -c "\dt"` should list 13 tables

## Acceptance criteria

Before ending the session, verify all of these:

1. ✅ `docker-compose up --build` succeeds with no errors
2. ✅ `docker-compose exec db psql -U bfa -d bfa_scout -c "\dt"` lists exactly 13 tables
3. ✅ `docker-compose exec db psql -U bfa -d bfa_scout -c "SELECT code, name_en FROM position_groups ORDER BY sort_order;"` returns 8 rows (GK → ST)
4. ✅ `docker-compose exec db psql -U bfa -d bfa_scout -c "SELECT * FROM v_position_group_form_counts;"` shows each group with 18+ criteria
5. ✅ `curl http://localhost:5000/health` returns `{"status":"ok","db":"connected"}`
6. ✅ `curl http://localhost:5000/` returns 200 and HTML containing "BFA Scouting"
7. ✅ Each of the 8 blueprint placeholder routes returns its TODO message (e.g. `/auth/`, `/players/`, …)
8. ✅ `git init && git add -A && git commit -m "Phase 0: project scaffold"` succeeds (you do this from PowerShell after the session)

## Hard rules (do not violate)

- ❌ NO hardcoded passwords or secrets in any file
- ❌ NO fallback default for `SECRET_KEY` in production code path
- ❌ NO `cursor.execute(f"... {var} ...")` — parameterized queries only
- ❌ NO touching `D:\BFA-Analytics` or `D:\BFA-Analytics-AWS`
- ✅ All DB queries use `RealDictCursor`
- ✅ All env vars accessed via `os.environ.get()` with explicit handling for required-but-missing
- ✅ `schema.sql` is copied verbatim — do not modify it in this session

## Out of scope (do NOT build in this session)

- Auth implementation (Phase 1)
- Any actual business logic in blueprints (placeholders only)
- Tailwind build pipeline (CDN is fine for v1)
- Tests (Phase 2)
- Alembic migrations (Phase 1)
- Player photos (Phase 3)
- Wyscout parser (Phase 4)

## Session discipline

- Target: 8 messages or fewer
- End by updating `PROJECT.md` with "Phase 0 complete, next: Phase 1 (Auth & RBAC)"
- End by appending to `CHANGELOG.md`
- Last action: print acceptance-criteria checklist with ✅/❌ per item
