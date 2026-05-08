# BFA Scouting & Evaluation System — Project Brief

**Codename:** `bfa-scout`  
**Owner:** Ali (BFA Technical Analyst)  
**Status:** Pre-build (Phase 0 ready to start)  
**Repo location:** `D:\BFA-Scout` (new, independent from BFA-Analytics)

---

## Vision

A standalone, mobile-first, web-based scouting and evaluation platform for BFA's National Team Committee. Scouts evaluate players live or post-match using position-aware forms; the system fuses subjective committee scores with objective Wyscout statistics into a unified Player Passport report.

**Independent from BFA-Analytics.** Different audience (committee/scouts vs. coaching staff), different data flow (Wyscout xlsx vs. BePro JSON), different deployment.

---

## Stack

| Layer | Choice |
|---|---|
| Backend | Flask 3.x + Python 3.11 |
| Database | PostgreSQL 15 (managed on DigitalOcean) |
| ORM | psycopg2 + raw SQL (same pattern as BFA-Analytics) |
| Auth | Flask-Login + PBKDF2 |
| Frontend | Jinja + HTMX + Alpine.js + Tailwind CSS |
| PDF export | WeasyPrint |
| AI | Google Gemini API |
| PWA | Hand-rolled Service Worker + IndexedDB |
| Container | Docker + docker-compose |
| Hosting | DigitalOcean Droplet + managed PostgreSQL + Cloudflare |

**Rationale:** Boring on purpose. Reuses Ali's BFA-Analytics muscle memory. No SPA build complexity. No new languages. Production-ready from session 0.

---

## Roles

| Role | Permissions |
|---|---|
| `admin` | Full access. Manage users, criteria taxonomy, system config. |
| `technical_director` | Read all. Manage players, lock evaluations. Cannot edit users or criteria. |
| `scout` | Create/edit own evaluations. Read all players & evaluations. Cannot lock or admin. |
| `viewer` | Read-only access to players, evaluations, reports. |

---

## Database — high-level

13 tables grouped into 7 domains:

1. **Auth** — `users`
2. **Position taxonomy** — `position_groups` (8), `positions` (~26 Wyscout codes)
3. **Players** — `players`
4. **Criteria config** — `criteria_categories` (4), `criteria` (~37 seed), `position_group_criteria` (mapping)
5. **Evaluations** — `evaluations`, `evaluation_scores`
6. **Wyscout** — `wyscout_imports`, `wyscout_match_stats`
7. **AI & audit** — `ai_artifacts`, `audit_log`

**Position groups (8):** GK, CB, FB, DM, CM, AM, W, ST  
**Criteria categories (4):** Technical, Tactical, Physical, Mental  
**Score scale:** 1–10, half-points allowed, configurable per criterion

Full schema: `schema.sql`.

---

## Dynamic-form mechanism (the key abstraction)

When a scout opens an evaluation form for a player:

1. Resolve `player.primary_position_id → positions.position_group_id`
2. Query `position_group_criteria JOIN criteria JOIN criteria_categories` filtered by group
3. Render form grouped by category, sorted by `sort_order`
4. Submit creates `evaluations` + N `evaluation_scores` rows

Admins add/edit criteria through `/admin/criteria`. New criterion → tick which position groups it applies to → appears in form on next load. **Zero redeploys for taxonomy changes.**

---

## Locked decisions

| Decision | Choice |
|---|---|
| Score scale | 1–10, half-points, per-criterion override available |
| Evaluation timing | Both modes: match-tied (live) and freestanding (post-window) |
| Multi-position handling | One evaluation per observation, scout picks dominant position from dropdown defaulted to first Wyscout token |
| Position groups | 8 (not 4, not 16) |
| Frontend approach | Server-rendered + HTMX + Alpine.js (no SPA) |
| PWA scope | Offline draft persistence + installable, not full offline app |

---

## v1 feature set

### Core
- Auth + RBAC (4 roles)
- Player CRUD with photo upload
- Wyscout xlsx import per player
- Dynamic position-aware evaluation form
- Player Passport report (HTML + PDF)

### Differentiators
- **Offline-first PWA** for stadium use
- **Consensus & divergence tracking** across multi-scout evaluations
- **Hybrid form** — Wyscout pre-fills objective metrics (read-only), scout fills subjective only
- **AI Scouting Companion (Gemini):**
  - Auto-narrative summaries (EN + AR)
  - Nearest-neighbor player comparison
  - Voice-to-note transcription via Web Speech API

### Deferred to v1.1+
- Wyscout API integration (v1 = manual xlsx upload)
- Multi-language UI toggle (v1 = EN with AR labels in DB)
- Telegram/WhatsApp notifications

---

## Roadmap

| # | Phase | Sessions | Deliverable |
|---|---|---|---|
| 0 | Scaffold | 1 | Docker stack up, schema migrated, `/health` returns 200 |
| 1 | Auth & RBAC | 1 | Login, 4 roles, decorators, user CRUD |
| 2 | Position taxonomy + criteria CRUD | 2 | Admin can edit categories/criteria/mappings |
| 3 | Players module | 1–2 | CRUD, photo upload, search dropdown |
| 4 | Wyscout import | 1–2 | Upload xlsx, parse, dedup, store |
| 5 | Evaluation form | 2 | Mobile-first dynamic form, draft auto-save, submit/lock |
| 6 | Player Passport | 1–2 | HTML + PDF report fusing eval + Wyscout |
| 7 | PWA + AI | 1–2 | Service Worker, Gemini narrative + comparison |
| 8 | Deploy | 1 | DigitalOcean droplet, managed PG, Cloudflare, daily backup |

**Estimated total: 10–14 Cowork sessions to deployable v1.**

---

## Hard rules (carried over from BFA-Analytics learnings)

1. No hardcoded credentials. All secrets via environment variables.
2. No fallback defaults like `'MID'` or `ADMIN_PASSWORD`. Fail loud.
3. Every player query selects `id`, `national_id`, `primary_position_id` explicitly.
4. Every helper that resolves player data goes through a single `get_player_position()` / `get_player_photo()` style helper from day 1.
5. Parameterized queries only (`%s`). Never f-string SQL.
6. `psycopg2.extras.RealDictCursor` everywhere — named row access, no positional.
7. All ingest scripts have audit invariants (assert no cross-player data leakage at end of run).
8. Containerized from session 0. AWS migration later = `docker push`, not rewrite.
9. `PROJECT.md` + `CHANGELOG.md` updated every Cowork session for state continuity.
10. Target 8–10 messages per Cowork session.

---

## Branding

| Token | Value |
|---|---|
| Primary | `#C8102E` (BFA Red) |
| Accent | `#B5924C` (BFA Gold) |
| Background | `#0E1116` (dark) |
| Surface | `#1A1F26` |
| Font | Cairo (Google Fonts), system fallback |
| Theme | Dark, mobile-first |

---

## Repository layout

```
bfa-scout/
├── app/
│   ├── __init__.py          # Flask factory
│   ├── config.py            # env-driven config
│   ├── db.py                # psycopg2 helpers
│   ├── auth/                # login, RBAC, user CRUD
│   ├── players/             # profile pages, photo uploads
│   ├── evaluations/         # the form, draft/submit/lock
│   ├── criteria/            # admin CRUD for taxonomy
│   ├── wyscout/             # xlsx parser, import endpoint
│   ├── reports/             # Player Passport HTML + PDF
│   ├── ai/                  # Gemini wrappers
│   ├── api/                 # JSON endpoints HTMX talks to
│   ├── templates/           # Jinja
│   └── static/              # PWA, manifest, SW, css
├── migrations/              # Alembic (set up Phase 1)
├── tests/
├── schema.sql
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
├── PROJECT.md               # this file (kept current)
├── CHANGELOG.md
└── README.md
```

---

## Working agreement

| Tool | Use for |
|---|---|
| **claude.ai** (chat) | Planning, prompt-writing, schema edits, triage, AI prompt design |
| **Cowork** | Build sessions (Phases 0–8) |
| **Claude Code** | Local debug loops once Flask runs |

When starting a new Cowork session, paste current `PROJECT.md` + `CHANGELOG.md` first so Cowork has state.
