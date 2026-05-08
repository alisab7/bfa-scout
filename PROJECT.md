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
