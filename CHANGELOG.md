# Changelog

## v0.0.2 — Phase 0 cleanup (2026-05-08)

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

---

## v0.0.1 — Project scaffold (2026-05-08)

- Flask factory (`create_app`) + 8 blueprint stubs (auth, players, evaluations, criteria, wyscout, reports, ai, api)
- PostgreSQL 15 schema initialized (13 tables, seed data: 8 position groups, 26 positions, 4 criteria categories, ~37 criteria, position-group-criteria mappings)
- Docker Compose stack: `web` (Flask/Gunicorn) + `db` (PostgreSQL 15-alpine)
- BFA dark-theme base template (HTMX 1.9.10 + Alpine.js 3.x + Tailwind CSS via CDN)
- BFA color tokens as CSS custom properties (`--brand`, `--accent`, `--bg`, `--surface`, `--text`, `--text-muted`, `--border`)
- Health check at `/health` — returns `{"status":"ok","db":"connected"}` with live DB ping
- Landing page at `/` — BFA branding, hero, Sign In + Learn more CTAs
- PWA manifest placeholder at `/static/manifest.json`
- `flask init-db` CLI command for manual schema init
- `.env.example`, `.gitignore`, `README.md`, `wsgi.py`
