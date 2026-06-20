# BFA-Scout — Current Status

**See `project_brief.md` for full architecture, locked decisions, and roadmap.**

## Revised roadmap

| Phase | Status | Notes |
|---|---|---|
| Phase 0: Scaffold | ✅ Committed | |
| Phase 1: Auth & RBAC | ⚠️ Working — polish deferred | See known issues below |
| Phase 2: Criteria admin | ⏭️ Skipped | Seeded criteria sufficient for Phase 5 |
| **Phase 3: Players module** | **✅ Complete** | CRUD, Pillow photo crop, HTMX search, position picker |
| **Phase 4: Wyscout import** | **✅ Complete** | xlsx parser, UPSERT ingest, radar + trend dashboard |
| **Phase 4.1: Season aggregations + comparison** | **✅ Complete** | Career-by-Season, multi-season radar, 2-3 player compare |
| **Phase 4.2: Season column + backfill** | **✅ Complete** | `wyscout_match_stats.season VARCHAR(7)` + index; ingest derives at UPSERT; 49 rows → '2025-26' |
| Phase 4.2.1: Season-toggle UI | Queued — needs 2nd season | Comparison page + profile dashboard season filter; deferred until multi-season data exists |
| **Phase 5a: Criteria reseed + NT readiness columns** | **✅ Complete** | 55 criteria, 303 mappings, audit-gated migration; schema.sql in sync |
| **Phase 5b: Matches table + Wyscout auto-link** | **✅ Complete** | 33 matches backfilled, 34 stat rows linked, shared-fixture dedup verified |
| **Phase 5c-1: Evaluation form** | **✅ Complete** | Position-aware sliders, draft/submit, inline match create, admin eligibility block |
| **Phase 5c-1.1: Tri-state slider** | **✅ Complete** | Untouched / rated / N/A; reversible; CHECK-enforced |
| **Phase 5c-2: Final form story** | **✅ Complete** | History cards, lock/unlock, admin-edit, eligibility card, residency tracking, mobile polish, Arabic |
| **Phase 5c-2.1: Patch (eligibility/sections/list)** | **✅ Complete** | Card moved up; priority order fixed; section-grouped scores w/ avgs; players list eligibility col + filter |
| **Phase 5c-3: UI/UX polish** | **✅ Complete** | Nationality+flag dropdown, clubs table+dropdown, soft-delete+recovery, bio counts, date theming |
| **Phase 5d: Comparison page scout dimension** | **✅ Complete** | Category averages, NT/recommendation, Latest/Averaged toggle, criteria-union drill-down |
| **Phase 5d-1: Scout-assessment radars** | **✅ Complete** | 1 category-level + 4 per-category Chart.js radars; HTMX-aware re-init on Latest/Averaged swap |
| **Phase 6: Player Passport (PDF)** | **✅ Complete** | Bilingual A4 PDF — bio + eligibility + Wyscout + radar (page 1) + scout evaluations + history (page 2); full + public-redacted modes; WeasyPrint |
| **Phase 6.1: PDF polish** | **✅ Complete** | Radar layout fixed (block stack, viewBox expanded), eligibility wording (no jargon), inline SVG flags (271 vendored from flag-icons MIT), Wyscout season+match-count subtitle, timing log + UI loading indicator |
| **Phase 6.2: PDF page-1 layout fix** | **✅ Complete** | Side-by-side stats(55%)+radar(45%), h3 underline removed (subpixel-render fragility in some PDF viewers), exactly 2 pages |
| **Phase 6.2.1: Admin notes hidden** | **✅ Complete** | Admin scratchpad fields (`eligibility_notes_admin`, `bahrain_residency_notes`) no longer rendered in any user-facing surface; DB columns + data preserved; admin edit form unchanged |
| **Phase 6.2.2: BFA board polish** | **✅ Complete** | Age at eligibility shown for future-eligible foreign_residency players; Bahrain flag on ✅ eligibility card; Wyscout idempotency confirmed |
| **Phase 6.2.3: Eligibility + flag display audit** | **✅ Complete** | Reusable `eligibility_badge` macro; `status_code` in eligibility dicts; flag + colored badge propagated to grid, profile, compare, search, eval form |
| **Phase 7: NT staff role + /nt workspace + visibility invariant** | **✅ Complete** | `nt_staff` role; `evaluations.created_by_role` column; scouts can't see NT evals anywhere; admin/nt_staff workspace at `/nt` showing BPL-eligible squad |
| **Phase 7.1: Widening (TD on /nt, viewer filtered)** | **✅ Complete** | `admin_or_nt_staff_required` adds TD; `_nt_visibility_clause` + 3 inline sites widen to filter viewer alongside scout |
| **Phase 9: Bulk player import** | **✅ Complete** | CSV + Excel; pandas parser; preview-first UX; composite duplicate detection; transactional commit; 500-row cap; 46/46 E2E |
| **Phase 8: Production deployment** | **✅ Complete (Cowork-side)** | Docker + compose + nginx + Spaces photo storage + healthz + backup cron + DEPLOY.md. v1.0.0. Droplet provisioning + SSH deploy tracked in DEPLOY.md |
| **Phase 8.1: Security hardening** | **✅ Complete** | nginx login rate limit (10/min, burst 5); password complexity (≥12, upper+lower+digit); 8hr sliding session timeout + secure cookie flags. v1.0.1 |
| **Youth NT section + restricted youth_nt role** | **✅ Complete** | `players.age_group` (U17/U20/U23/senior); `/youth` section; general list excludes youth; first restricted role `youth_nt` (sees only youth, query-level + 403s); 28/28 functional + 24/24 security E2E. v1.2.0 |
| **Bulk import: Registry Excel + CPR-matched photos** | **✅ Complete** | `/admin/import/players` (registry `.xlsx` → preview → confirm, CPR-keyed, age-group-highest-wins, idempotent) + `/admin/import/photos` (CPR-filename match, reuses photo pipeline); `app/players/cpr.normalize_cpr` (9-digit TEXT); admin-only; 24/24 E2E. v1.3.0 |
| **Registry import: nationality mapping** | **✅ Complete** | Age Group → age_group + nationality_status + nationality + nationality_code. Citizens (U17/U20/U23/NT/senior) auto Bahrain/BHR; residents (residency) take nationality + 3-letter code from the file (required+validated); NT accepted; INSERT+UPDATE write all four (re-import corrects NULLs); 40/40 E2E. v1.3.1 |
| **Eligibility badge "Citizen"** | **✅ Complete** | bahraini/foreign_ancestry → "Citizen" (not "Eligible now", reserved for residency past-date). Single source `compute_eligibility_status`. v1.3.2 |
| **/nt senior-only + name search** | **✅ Complete** | /nt restricted to age_group=senior (NULL-safe); client-side Alpine live EN/Arabic name search. v1.3.3 |
| **Evaluations: position played in match** | **✅ Complete** | Required per-evaluation match-position dropdown (positions table, defaults to primary); persisted on `evaluations.position_played_id`; shown on view + history. Display-only — criteria + registered position unchanged. 13/13 E2E. v1.4.0 |
| **Admin bulk position-assign screen** | **✅ Complete** | `/admin/assign-positions` (admin+TD) lists active position-less players + grouped picker; bulk-sets `primary_position_id` so imported players become evaluatable. Evaluate guard unchanged. 12/12 E2E. v1.4.1 |
| Phase 8.2: Auth hardening v2 | Queued (v1.1) | CSRF token review, password reset email, 2FA/MFA |
| Phase 10: AI features | Queued (post-v1) | Gemini integration |

## Current phase

**Admin bulk position-assign screen — complete. v1.4.1.**

`/admin/assign-positions` (admin + TD) lists every active player with no
primary position (the ~35 registry imports) with the grouped position
picker, and sets `primary_position_id` for the chosen rows in one save
(blank rows stay unassigned). Because `players` has no `position_group_id`
column — the group is derived via JOIN — setting the primary position is
enough for the evaluate guard to pass. The evaluate guard itself is
unchanged; no inline-on-evaluate picker. `migrations/_e2e_assign_positions.py`
12/12; full regression green. No schema change.

**Deploy note (Ali):** pure-code deploy. After deploy, open
`/admin/assign-positions`, set positions for the imported players (you'll
need their positions from team sheets / coaching staff), and Save — their
evaluate pages then work.

---

**Evaluations: position played in the match — complete. v1.4.0.**

Each evaluation records the position the player actually played that match
(`evaluations.position_played_id`, an existing-but-previously-unused FK to
`positions`). Required dropdown on the eval form, defaulting to the
player's registered primary position, reusing the players' grouped
position picker. Shown on the eval view ("Position played: …") and on the
per-player history cards ("· played CODE"). **Display-only**: criteria are
still driven by `position_group_id` (the player's group) and the player's
registered position is never changed. No DDL — the column existed in
schema.sql; the migration just backfills existing rows to primary
position. `migrations/_e2e_eval_position.py` 13/13; prior eval suites
(5c2.1/5d/5d-1/5d-patch) + full regression green.

**Deploy note (Ali):** no schema change vs. the live DB (column already
present). Run `migrations/eval_position_played.sql` once against prod to
backfill historical evaluations to their players' primary positions, then
it's a normal code deploy.

---

**Registry import: nationality mapping — complete. v1.3.1.**

The registry importer's **Age Group** column now drives four fields so
imported players get real eligibility (not "unknown"):
- `U17/U20/U23` → that group + **bahraini** + Bahrain + BHR
- `NT` / `senior` → senior + **bahraini** + Bahrain + BHR (NT accepted; DB
  never stores "NT" as age_group)
- `residency` / `resident` → senior + **foreign_residency** + nationality +
  3-letter code **from the file** (required, validated; matched by header so
  citizen files don't need the columns)
- blank / unmapped label → **ERROR** (no silent default)

INSERT + UPDATE both write `nationality_status/nationality/nationality_code`;
UPDATE sets them directly so a re-import corrects earlier NULLs. Preview
shows the resolved eligibility/nationality/code. Residency template:
`sample_data/BFA_Player_Registry_Template_residency.xlsx` (gitignored).
40/40 E2E; prior suites regress clean.

**Out of scope (Ali):** the one-time SQL `UPDATE` to fix the ~35
already-imported players that have NULL nationality (or just re-run the
import for them — UPDATE now corrects NULLs).

---

**Bulk import: Player Registry Excel + CPR-matched photos — complete. v1.3.0.**

Two admin-only preview→confirm import pages so management injects the
roster instead of hand-entering it.

- **`/admin/import/players`** — the BFA Player Registry `.xlsx` (sheet
  `➡ Player Registry`, data row 4+). `app/players/cpr.normalize_cpr`
  restores Excel-stripped leading zeros to 9-digit TEXT (the master key;
  born-2000 `503061`→`000503061`). CPR-keyed dedupe, **highest age group
  wins** (U23>U20>U17>senior), example rows skipped, idempotent, every
  rejected row reported. Sets `players.age_group` → imported youth route
  into `/youth/<group>`. Parsed with **openpyxl directly** (pandas would
  destroy the int/text/datetime distinctions the CPR/DOB rules need).
- **`/admin/import/photos`** — multi-file upload matched by CPR in the
  filename; reuses the existing photo pipeline (`save_player_photo` →
  `storage.put_player_photo`, keyed by player_id). `photo_path` is
  vestigial and intentionally left untouched (matches manual upload).
- Reuses the Phase 9 parked-session store; the existing generic
  `/admin/players/bulk-import` is untouched.
- **Verification:** `migrations/_e2e_bulk_import.py` 24/24; Phase 9 46/0,
  youth 28/0 + 24/0, residents 15/0, v1.0.2 audit pass.
- **Note for Ali:** test with the REAL files (`BFA_Player_Registry_
  Template_u23.xlsx` + the 1st-team file in `sample_data/`). Run a
  **dry-run preview FIRST** on production with a real file — the preview is
  your safety check that CPR normalization + age-group assignment look
  right before anything is written.

---

**Youth NT section + restricted youth_nt role — complete. v1.2.0.**

The codebase's first **restricted role**. `youth_nt` users see ONLY
youth players (U17/U20/U23); every other surface (general list, compare,
NT workspaces, admin, passport, wyscout, reports/api/ai) returns a real
403. Enforcement is query-level + 403s (`require_youth_access(player)`
object guard + `deny_youth_nt` route guard in `app/auth/decorators.py`),
never hidden-UI-only — it's a board-level data-separation boundary.

- **Schema:** `players.age_group VARCHAR(16) DEFAULT 'senior'` (CHECK
  U17/U20/U23/senior or NULL); `users_role_check` widened for `youth_nt`.
  Migration `migrations/phase_youth_nt.sql` (idempotent DO-block).
  ⚠️ `players.age_group` is UPPERCASE; the unrelated `matches.age_group`
  is lowercase (match level, not squad) — intentionally distinct.
- **Surfaces:** `app/youth/` blueprint (`/youth`, `/youth/<group>`,
  `/youth/<group>/new`); general `/players` + compare exclude youth
  (`age_group = 'senior' OR IS NULL`); edit-form age-group selector for
  senior staff only (promotion). youth_nt lands on `/youth`.
- **Verification:** Suite A `_e2e_youth_functional.py` 28/28; Suite B
  (HARD GATE) `_e2e_youth_security.py` 24/24; prior suites regress clean.
- **Recommended:** a one-time manual browser spot-check post-deploy —
  log in as a youth_nt test user and actively try to reach senior data
  by direct URL (automated gate is green, but a human probe is warranted
  for a governance boundary).

---

**Residents view (/nt/residents) — complete. v1.1.0.**

Post-launch feature: a second coaching-team track. `/nt/residents`
lists `foreign_residency` players split into **Eligible Now** (5-year
clock complete) and **Still Counting** (future-eligible with date, or
"date not set"). Additive only — no schema/role changes; reuses the
shared `compute_suggested_eligibility` date math and the existing
`admin_or_nt_staff_required` gate (admin + TD + nt_staff). Existing
`/nt` left UNCHANGED per the hard rule (it shows eligible players of
any route, not just citizens — the spec's "citizen-only" framing was
aspirational; the regression test asserts "/nt unchanged").

New: `app/nt/helpers.py:get_resident_players()`, `nt.residents` route,
`nt/residents.html` + `nt/_residents_table.html`, Citizens↔Residents
tab strips, "Residents" nav link (desktop + mobile). 15/15 new E2E;
272/272 prior-suite regression.

---

**Phase 8.1: Security hardening — complete. v1.0.1.**

Pre-launch hardening. No schema changes. Nginx rate limits brute-force
on `/auth/login`; password complexity enforced at all three
password-setting flows; sessions expire after 8hr idle with secure
cookie flags. Ali to complete Item 1 (admin password rotation) on the
droplet per DEPLOY.md §11.

Next: Phase 8.2 (v1.1) — password reset email + 2FA. Queued for first
month of usage, not blocking launch.

**This is a multi-actor phase. Status by actor:**

| Actor | Scope | Status |
|---|---|---|
| Cowork (this commit) | All repo config + photo-storage abstraction + healthz + scripts + DEPLOY.md | ✅ Done, 272/272 regression |
| Ali | DO droplet + Managed PG + Spaces + Cloudflare DNS/SSL | ⏳ Console work — DEPLOY.md §2-3 |
| Claude Code (on droplet) | SSH deploy + schema load + bootstrap + 10 smoke tests + backup cron | ⏳ After Ali — DEPLOY.md §4 |

**Substantive code change — photo storage abstraction.**
`app/storage.py` switches photos between DO Spaces (prod) and local
FS (dev) on `SPACES_BUCKET`. The Pillow re-encode invariant and the
passport-PDF self-containment are both preserved (the spec's 2-fn
sketch would have broken both). Single read chokepoint via the
existing `get_player_photo` Jinja global → every photo render works
on Spaces with one edit. Filenames stay `player_id`-keyed.

**Infra (NEW):** Dockerfile (py3.13-slim + WeasyPrint native deps +
Noto fonts), docker-compose.prod.yml (app+nginx), gunicorn.conf.py
(2×4, 120s), nginx reverse proxy, .env.*.example, scripts/ (deploy,
bootstrap_admin, backup_to_spaces, restore_from_spaces), DEPLOY.md
(10-section runbook). `.gitignore` hardened (no `.env.production`, no
origin certs). `requirements.txt` += boto3.

**Verified locally (Cowork-side):** app imports clean; `/healthz`
→200; storage local-mode round-trip; bootstrap_admin idempotent
(2 runs); full regression **272/272 across 9 suites** — storage
abstraction is transparent, passport PDF still green.

**Blocked on infra actors (not code defects, tracked in DEPLOY.md):**
`docker build` (no Docker on the dev box), Spaces-mode storage (needs
real DO creds), the 10 post-deploy smoke tests (need the live
droplet).

**Phase 9: Bulk player import + Phase 7.1 widening — complete (one commit).**

Project status ~98%. Final feature phase before deploy. Both shipped
together so bisect stays clean.

**Phase 7.1 — widening (5 lines).** Two of the four design calls made
during Phase 7 flipped:

| Decision | Phase 7 | Phase 7.1 |
|---|---|---|
| `/nt` access | admin + nt_staff | admin + **TD** + nt_staff |
| NT visibility filter | `scout` only | `scout` + **viewer** |

The visibility-filter change touched 4 sites in `app/evaluations/helpers.py`
(the central `_nt_visibility_clause` plus 3 inline copies in bare-table
queries). Half-applied widening would have left viewer filtered on some
helpers but not others — a silent partial info leak — so all 4 sites
moved as a set.

**Phase 9 — bulk player import.** Admin-only 3-step workflow at
`/admin/players/bulk-import`:

1. **Upload** — CSV or xlsx, max 500 rows, `full_name` required, every
   other column optional. Empty / "N/A" / "nan" all normalise to NULL.
2. **Preview** — parsed rows classified green (CREATE) / yellow
   (DUPLICATE — per-row select skip/update) / red (INVALID — error
   shown). Per-row warnings rendered too.
3. **Commit** — atomic transaction: INSERT new players, UPDATE
   duplicates marked 'update', skip the rest. One audit_log row per
   imported player + one summary row, both inside the same transaction.
   Any failure → ROLLBACK; no partial imports.

**Architecture**
- `app/admin/bulk_import.py` — 7 routes (index, upload, preview, commit,
  result, discard, two template-download endpoints).
- `app/admin/bulk_import_helpers.py` — pure functions: pandas-backed
  parser, validator with errors+warnings, duplicate detection
  (national_id first, then name+DOB+position fuzzy), DB-params builder
  resolving position FK + clubs.name → club_id.
- `app/admin/bulk_import_session.py` — in-memory parked-import store
  keyed by `secrets.token_urlsafe(16)` (token in Flask session cookie,
  rows in module-level dict, 30-min TTL, lazy GC). Persistence absent
  for v1; admin re-uploads on Flask restart.

**Bugs caught during build (documented in CHANGELOG):**
1. **pandas 3.x StringDtype + .map() skips NaN cells** — fixed by
   normalising at the dict layer after `to_dict('records')`.
2. **`'float' object has no attribute 'strip'`** — defensive `_str()`
   coerce at the top of `validate_row`.
3. **`cursor already closed`** — `cur.fetchone()` was outside the `with
   conn.cursor() as cur:` block. Moved inside.

**Verified end-to-end:**
- Phase 9 E2E: 46/46 PASS (15 spec cases + bonus template-download checks)
- Phase 7.1 verifier: 8/8 PASS (TD on /nt, viewer filtered, admin unchanged)
- Regression: 218/218 across 7 prior suites (4.2, 5d-1, 6.0, 6.1, 6.2,
  6.2.1, 7) — unchanged
- **Total: 272 checks across 9 suites, 0 failures**

**Schema unchanged.** national_id UNIQUE constraint + idx_players_national_id
already exist from prior phases. No migration needed.

**Spec-vs-codebase mismatches caught in pre-flight:**
- Spec field `dominant_foot` ↔ DB column `players.foot` — validation
  accepts the spec name, `build_db_params` writes to the DB name.
- Spec example position codes "CB, AM" — actual table has `AMF`, `DMF`.
  Validation uses the live `positions.code` set so it stays accurate
  regardless of seed data.

**Next:** Phase 8 (auth polish + production deploy) is the final queued
phase.

**Phase 7: NT staff role + /nt workspace + visibility invariant — complete.**

Project status ~96%. First non-Phase-6 schema change since 6.0 — adds
`evaluations.created_by_role` (NOT NULL, default `'scout'`) and widens
the `users_role_check` constraint to include `nt_staff`. The widening
is **additive** — the spec proposed replacing the role set with
`(admin, scout, coach, management, nt_staff)` (silently dropping TD
and viewer), but a (1.5) pre-flight catch reconciled that to
`(admin, technical_director, scout, viewer, nt_staff)` — preserving
the four existing roles so the existing role-decorators
(`admin_or_td_required`, `any_authenticated`, etc.) keep working.

**Three deliverables:**

1. **`nt_staff` role added.** New auth decorators `nt_staff_required`
   and `admin_or_nt_staff_required`. `any_authenticated` widened to
   include `nt_staff` so they can hit existing pages. Right-of-nav
   role badge for NT users renders in emerald (`#10B981`) — distinct
   from BFA red (admin) and gold (TD).
2. **NT VISIBILITY INVARIANT.** Sibling to the soft-delete invariant
   from Phase 5c-3: every evaluation read helper in
   `app/evaluations/helpers.py` accepts an optional
   `requesting_user_role` kwarg. When `'scout'`, the SQL filters
   `AND created_by_role != 'nt_staff'`. Routes pass
   `current_user.role` through; Jinja-global template callsites pass
   it too. Threaded through 6 helpers, 6 routes, 2 templates.
   Evaluation create paths (`get_or_create_draft`) stamp the
   creator's role at insert time.
3. **`/nt` workspace.** New `/nt/` page — admin + nt_staff only;
   403 for scout, viewer, TD; anon bounces to login. Renders a
   table of BPL-eligible players (Bahraini citizens, ancestry-route,
   explicit eligibility date in the past, or 5-yr residency
   complete). Per-row NT-evaluation count. Nav link visible to
   admin + nt_staff only (BFA gold accent).

**Evaluation role badge** (new macro at
`_macros/evaluation_role_badge.html`): emits `NT` / `Admin` badges
next to evaluator names on the history card, compare scout-section
latest-by line, and passport (latest-eval + recent-evaluations
table). Scout role intentionally renders no badge — default state
keeps the UI quiet for the common case.

**Verified:**
- Phase 7 E2E: 29/29 PASS (5 permission · 7 visibility · 4
  aggregate · 2 squad · 3 create-path · 3 nav · 5 setup/schema).
  Test fixtures snapshot+restored in `finally:` — DB left
  unchanged.
- Regression: **218/218 across 7 suites** (4.2, 5d-1, 6.0, 6.1,
  6.2, 6.2.1, 7). Threading the new kwarg with `None` defaults
  preserved all existing helper behaviour.
- Schema-level: throwaway-namespace verify confirms `flask init-db`
  reproduces the column + index + widened constraint; INSERT with
  role='nt_staff' succeeds, INSERT with bogus role rejected.
- Visual: `/nt` table renders cleanly — Arthur (Brazilian,
  residency complete 2025-12) and Bader (Bahraini citizen) listed.
  Bouhra (Moroccan, residency completes 2027-08) correctly absent.

**4 design calls made during build** (all reversible, documented in
CHANGELOG so the next maintainer doesn't undo them silently):
1. Role constraint additive (preserves TD/viewer).
2. `/nt` access = admin + nt_staff only (TD deliberately not
   included).
3. Visibility filter applies to `scout` role only (viewer not
   filtered).
4. "Coach → 403" assertion in spec — no coach role exists; E2E
   substitutes viewer.

**Phase 6.2.3: Eligibility + nationality flag display audit — complete.**

Standing rule enforced: every surface showing a player's name must show their flag +
eligibility badge. Implemented via a new reusable `eligibility_badge` Jinja macro
(`app/templates/_macros/eligibility_badge.html`) that renders the player's nationality
flag (SVG inline) plus a colored status badge (`eligible_now` green / `eligible_future`
amber / `not_eligible` red / `unknown` gray).

Propagated to: player card grid (`_grid.html`), player profile header,
compare view bio header, compare search dropdown, evaluation form header.

Data layer updated: `compare_players()` and `_load_player()` now include
`nationality_code` + `nationality_status` + eligibility date fields.

**Previous: Phase 6.2.2: BFA board polish — complete.**

Three items from post-6.2 board review:

1. **Age at eligibility** — `foreign_residency` players with a future
   elig date + known DOB now show "Age at eligibility: N" on the profile
   card and passport PDF. Logic in new `age_at_eligibility()` helper
   (eligibility.py). Uses `_resolve_eligibility_date()` as single source
   of truth. Only renders when relevant (future date, known DOB,
   foreign_residency route).

2. **Bahrain flag on eligible card** — Players with `is_eligible_now=True`
   (Bahraini, foreign-ancestry, or residency complete) now get the BHR
   inline SVG flag next to their ✅ on the profile eligibility card.
   `get_flag_svg` registered as Jinja global in app/__init__.py.

3. **Wyscout idempotency audit** — Code review + diagnostic confirmed no
   duplicates can accumulate via normal ingest. UNIQUE constraint and
   ON CONFLICT clause match exactly. New `_e2e_phase_6_2_2.py` diagnostic
   script logs Q1/Q2/Q3 for future reference.

**Previous: Phase 6.2.1: Admin notes hidden from user-facing surfaces — complete.**

Browser spot-check after 6.2 revealed sentinel test data leaking into
Arthur's passport ("Eligibility notes (admin):" + "Residency notes
(admin):" lines populated with `E2E-SENTINEL-…-DO-NOT-PUBLISH`
strings written by a prior crashed E2E). Data layer was correct;
real lesson: admin notes are admin scratchpad and don't belong in
any user-facing artefact.

**Two-item patch:**
1. Removed the two `{% if player.<admin_note> %}` blocks from
   `app/templates/passport/passport.html` (the only user-facing
   surface that rendered them). Dropped the orphaned
   `.elig-admin-note` CSS rule.
2. Grep-audited the rest of `app/` for `eligibility_notes_admin` /
   `bahrain_residency_notes` references. Classified every hit:
   backend SQL/form handling stays; admin forms (`edit.html`,
   `new.html`) stay; profile / eligibility-card / history templates
   already didn't render them. No other user-facing surface
   touched these fields, so nothing else to remove.

**Contract change** (logged in CHANGELOG): admin notes now hidden
in BOTH passport modes (full + public), not just public. The data
layer's existing public-mode scrub is now redundant but kept as
belt-and-braces. DB columns and data preserved.

**Verified:**
- 6.2.1 E2E: 23/23 PASS (sentinel-injection round-trip; assertions
  cover both PDF modes, profile page HTML, admin edit form,
  template literal check, and DB restore-on-finally)
- 6.0 E2E updated: 26/26 PASS (Case 3 contract flipped from "admin
  visible in full mode, scrubbed in public" to "hidden in both
  modes")
- 6.1, 6.2 regressions: 57/57 + 26/26 PASS unchanged
- 132 checks total across all four suites

Visual spot-check: PDF generated with sentinels actively in the DB
showed only the eligibility status line + residency-since line. No
admin notes, no orphan whitespace; eligibility section flows
cleanly into the Wyscout section below.

**Phase 6.2: PDF page-1 layout fix — complete.**

Two-item patch on top of 6.1. Project status ~95% (no incremental
progress vs 6.1; same demo-ready milestone, page-1 layout now
genuinely 2-page and visually clean across PDF viewers).

**Item 1 — "decorative wave" hunted and eliminated.** Pre-flight grep
turned up no `wavy` text-decoration, no `<hr>`, no decorative SVGs.
4x-zoom rasterization showed all horizontal rules as perfectly
straight 1pt lines. Root cause: Edge/Chrome's built-in PDF viewers
anti-alias `border-bottom: 1pt solid` rules at non-integer pixel
positions into wavy/dithered gradients — what Ali saw was real
subpixel render noise. Durable fix: strip the h3 `border-bottom`
entirely; the BFA-red bold heading (bumped to 11.5pt / 700) is plenty
of separation. The `.passport-header` 2pt rule stays (robust against
the same subpixel quirk).

**Item 2 — side-by-side stats + radar on page 1.** `.wyscout-grid`
flipped from `display: block` (the over-conservative 6.1 fix) back
to `display: flex` with a 55%/45% column split. h3 + stats-subtitle
stay outside the flex container so they span the full row above
both columns. `page-break-inside: avoid` keeps the layout intact
across the natural page break. Radar SVG geometry re-tightened
(viewBox 360→320, margin 22%→18%) so all 6 axis labels still fit
inside the narrower column, including the multi-word "Work Rate".

**Page-budget contract.** Page 1 has the bio strip, eligibility card,
Wyscout heading + subtitle, and stats|radar side-by-side. Page 2 has
only the scout assessment + footer. PDFs verified for Arthur, Arthur-
public, and Bouhra — all exactly 2 pages, all 6 radar axes readable,
0 axes leak to page 2.

**Verified end-to-end:**
- 6.2 E2E: 26/26 PASS (page-count contract, side-by-side CSS, no
  border-bottom on h3, no `text-decoration: wavy`, no `<hr>`)
- 6.1 regression E2E: 57/57 PASS (after a small E2E hardening: end-
  of-run artefact saves are now best-effort against locked-file
  errors from prior sessions)
- 6.0 regression E2E: 26/26 PASS

**Phase 6.1: PDF polish — complete.**

Project status ~95% (no incremental progress vs 6.0; same demo-ready
milestone, now visually polished).

Five items addressed against Phase 6's first-cut PDF:

1. **Radar layout & geometry.** Two compounding bugs — flex layout
   starved the radar of column width AND SVG viewBox was too tight for
   label headroom. Switched `.wyscout-grid` to block stack; expanded
   viewBox 280→360 user-units. All 6 axis labels now readable
   (Scoring/Passing/Dribbling/Defending/Aerial/Work Rate).
2. **Eligibility wording.** New `_build_passport_eligibility(player)`
   for the formal-document context: "Eligible from 2027-08-15 (in 1
   year, 3 months) / Bahrain residency since 2022-08-15" replaces the
   live-UI wording "Eligible in 1y 3m / (Article 5; admin to confirm)".
   7 branches asserted in E2E.
3. **Inline SVG flags.** Vendored 271 SVGs from upstream `flag-icons`
   (MIT). Replaces emoji flags which rendered as monochrome boxes
   under WeasyPrint's Pango font chain.
4. **Wyscout subtitle.** "YYYY-YY season · N matches" (or "A to B")
   from the `wyscout_match_stats.season` column added by Phase 4.2.
   Kept hyphen format to match the DB.
5. **Timing instrumentation + UI loading indicator.** Renderer logs
   `template=Xs weasyprint=Ys total=Zs bytes=N` at WARNING. Sample on
   this Windows dev box: template ~20ms, WeasyPrint ~12s, total ~12s.
   Profile-page button shows "⏳ Generating…" via inline JS on click,
   with `pointer-events: none` to swallow double-clicks. PDF
   generation latency documented as ~12s on Windows / ~2-3s expected
   on production Linux.

**Page-budget regression fixed mid-build.** The bigger radar + new
subtitle line initially pushed scout-section to a 3rd page. Removed
the explicit `<div class="page-break">` and added
`page-break-inside: avoid` on `.scout-section` / `.latest-eval`; PDF
settled cleanly at 2 pages: bio+eligibility+stats on page 1,
radar+scout on page 2.

**Verified end-to-end + visually:**
- 6.1 E2E: 57/57 PASS
- 6.0 regression E2E: 26/26 still PASS
- 3 PDFs rasterized via pypdfium2 (Arthur full, Arthur public, Bouhra
  full) — all 2 pages, all spec-table wording matches verbatim
  ("Eligible from 2027-08-15 (in 1 year, 3 months)" for Bouhra etc.)

**Known follow-ups (out of 6.1 scope):**
- Eligibility status icons (✅/⏳/❌) still render as monochrome outline
  glyphs — same emoji-font fragility we fixed for flags. Swappable
  to inline SVG with the same pattern if needed.
- `season_label_for_date` (Phase 4.1 helper, returns slash format
  '2024/25') is unused anywhere; flag for rename-or-delete when the
  Phase 4.2.1 season UI lands.

**Phase 6: Player Passport PDF — complete. Demo-ready.**

Project status ~95%. The printable artifact BFA committee members
take home from selection meetings. Two-page A4 PDF; bilingual EN/AR;
two modes (full / public-redacted); no schema changes.

- New `app/passport/` package: data aggregator, hand-built 6-axis radar
  SVG (no Chart.js — WeasyPrint doesn't run JS), WeasyPrint renderer,
  Blueprint route at `GET /players/<id>/passport.pdf`.
- Page 1: bio grid (name EN/AR, DOB+age, position, club, nationality+
  flag, build, ID), eligibility card with icon/label/note, 10-metric
  Wyscout table + 6-axis radar (axes: Scoring/Passing/Dribbling/
  Defending/Aerial/Work Rate — matches existing player-dashboard radar
  for visual consistency).
- Page 2: latest-evaluation panel with NT-level + recommendation
  badges, 4 category-average horizontal bars, optional summary
  (truncated to 500 chars), recent-evaluations table (date / scout /
  match / NT level / recommendation, up to 5 rows), generation
  footer.
- Public mode (`?public=1`): scout names → `Scout 1`/`Scout 2`/...
  (stable mapping across both the latest panel AND history table);
  `eligibility_notes_admin` + `bahrain_residency_notes` scrubbed;
  generator name → `BFA Scouting Department`; `PUBLIC` badge on
  header; footer notes "scout identities redacted".
- Filename: `BFA-Scout_Player-{id}_{slug}_{YYYY-MM-DD}.pdf`
- Audit log: one `player.passport_generated` row per render with
  `{player_id, mode}` in details.
- Soft-delete invariant honoured (Phase 5c-3); locked evals INCLUDED
  (locked is workflow protection, not data hiding).
- `is_active=FALSE` players return 404.
- 26/26 synthetic E2E PASS — real Flask + real HTTP (NOT
  `flask.test_client` per hard rule); pypdf text-extraction used
  for the redaction assertions.

**Environment dependency:** WeasyPrint 68.1 requires the GTK runtime on
Windows (Pango / GLib / cairo native DLLs). One-time install per
machine. Pre-flight caught GTK absent on this box and surfaced a
three-way choice (install GTK / xhtml2pdf / ReportLab); Ali picked GTK
install. After that the spec's HTML/CSS template landed verbatim with
proper Arabic shaping for names like `سيف الدين بوحرة`.

**Design call made during build (documented in CHANGELOG so the next
maintainer doesn't accidentally undo it):** public mode redacts the
generator name to `BFA Scouting Department`. The spec said
"scout names → Scout N" but didn't address the generator (downloader).
The "for sharing externally" use case extends naturally — an external
recipient doesn't need to know which BFA staffer hit "Download".

**Phase 4.2: Season column + backfill — complete (minimal)**

Project status ~92%. Schema + ingest only — no UI work (that's Phase 4.2.1,
gated on a second season of data existing). Closes the long-standing gap
where `wyscout_match_stats` had no first-class season notion despite the
data clearly spanning multiple BPL seasons in the long run.

- New `season VARCHAR(7)` column (nullable; defended against future
  NULL `match_date` ingest paths even though the column is currently
  NOT NULL); `idx_wyscout_match_stats_season` for the UI filter that
  4.2.1 will add.
- `app/wyscout/season.py:derive_season(match_date)` — source of truth.
  BPL season runs Aug–May; cutoff month is `SEASON_START_MONTH = 8`.
  5 unit tests asserted inside the generator (cross-year boundary cases:
  Jul/Aug pivot, Apr-of-following-year, next-season start).
- Ingest (`app/wyscout/ingest.py`) computes `season` from `match_date`
  and threads it through the existing dict-based UPSERT pattern.
  Because column lists are derived from `vals.keys()`, both the INSERT
  column list and the `season = EXCLUDED.season` UPDATE SET fire
  automatically — no hand-rolled SQL changes.
- Backfill: SQL CASE mirrors `derive_season()` exactly. 49 existing
  rows (Arthur 18 + Gelonson 15 + Bouhra 16) all backfilled to
  `'2025-26'`; date range verified 2025-09-12 .. 2026-04-16.
- 18/18 synthetic E2E PASS — including a per-row cross-check that
  `derive_season(match_date)` matches the SQL backfill output for all
  27 distinct dates in the live DB. Re-upload of Arthur's xlsx
  produced 0 inserts / 18 updates / 0 skips with season preserved.

**(1.5) catches surfaced before any code landed.** Three spec-vs-codebase
mismatches caught in pre-flight:
1. Spec said 34 rows; live DB has 49 (testing during 5d added 15 more).
   Audit gate switched to deriving `expected` dynamically from
   `COUNT(*) WHERE match_date IS NOT NULL` so it's correct regardless
   of when this lands.
2. Spec justified `season` being nullable because "future rows might
   come in with NULL match_date" — but the schema has `match_date NOT
   NULL`. Kept `season` nullable defensively (zero cost; survives a
   future schema relax) but corrected the justification in the doc.
3. Spec's backfill SQL used `LPAD(...)[3:4]` — Postgres array-slicing
   syntax that doesn't parse on TEXT. Rewrote with `% 100` arithmetic
   + `LPAD(..., 2, '0')`, which matches `derive_season()` exactly
   including the year-2000 boundary case (`00` not `0`).

**Phase 5d-1: Scout-assessment radars — complete**

Project status ~92%. UI-only follow-up to 5d: 5 Chart.js radars on the
scout section (1 category-level overview + 4 per-category drill-downs).
No schema changes, no DB hits below `build_scout_radar_data` (pure
shape transform on the data 5d already aggregated).

- Top "category averages" radar: 4 fixed axes (TECH/TACT/PHYS/MENT),
  one polygon per selected player. Built from `category_averages` from
  Phase 5d's `get_player_evaluation_aggregate`.
- Per-category radars: one inside each category's `<details>` block;
  axes = criterion `name_en` for the category. AM ∪ DM union → 8/20/15/6
  axes per category = 49 total (same as the drill-down table row count).
- N/A and absent criteria plot as 0 with annotation overlay (tooltip
  reads "N/A" or "—") so polygons stay closed without losing truth.
- HTMX-aware: Latest ↔ Averaged toggle swaps `#scout-section`;
  `scout_radars.js` listens for `htmx:afterSwap` (target-id-guarded) and
  re-inits all 5 radars after destroying prior Chart instances.
- Eager init (DOMContentLoaded), not lazy: Phase 5d's `<details open>`
  decision means all 4 sub-collapses are visible on first render, so
  lazy-init would just delay rendering the user already wants.
- Scale 0..10 (matches `criteria.scale_max`); BFA red+gold+blue palette.
- 39/39 synthetic E2E PASS

**Pre-flight catch worth naming.** I assumed a 0..5 scale from memory of
the slider component; the schema has `scale_max=10` and DB scores live
in [2.0, 10.0]. Caught and fixed before commit. The (1.5)-class
playbook step ("if a spec instruction contradicts a committed codebase
decision, surface it before building") now also covers spec-vs-schema
assumptions, not just spec-vs-prior-UX.

**Phase 5d: Scout dimension on comparison page — complete (with 3-item patch)**

Project status reached ~91% with this phase. Pure read-side aggregation
— no schema changes. 5d + patch landed as one commit per the patch
spec's "one logical unit" rule.

Patch items (all in the same commit as 5d):
- Latest-mode header card now shows match label (LEFT JOIN matches in
  the helper); averaged mode shows "Averaged across N evaluations"
- Mode toggle uses HTMX (`hx-get` to new `/players/compare/scout-section`
  partial route, `hx-target="#scout-section"`, `hx-swap="outerHTML"`,
  `hx-push-url`) — no full-page reload, no scroll jump, browser back
  button works
- Drilldown previously rendered only the first category due to a Jinja
  `{% set _ = list.append(...) %}` pattern silently failing past
  iteration 1. Moved grouping into Python via new
  `group_criteria_by_category()` helper. All 4 categories now render.
- Enrichment logic extracted into `_enrich_for_scout_section()` so the
  full-page route and the HTMX partial route share it (DRY)

- Three new helpers in `app/evaluations/helpers.py`:
  `compute_category_averages`, `get_evaluation_count_active`,
  `get_player_evaluation_aggregate(mode='latest'|'averaged')`
- Soft-delete invariant honoured everywhere; locked evaluations included
  (locked is workflow protection, not data hiding)
- Averaged mode resolves NT-readiness + recommendation via most-frequent-
  with-recency-tiebreak; per-criterion `eval_count` annotation surfaces
  in the drill-down as `(N)` next to averaged values
- `compare_players` extended to expose `position_group_id` so the route
  can compute the criteria union via existing `get_form_criteria`
- New section on `/players/compare/view`: per-player headline cards with
  category averages + badges, Latest/Averaged toggle, expandable
  per-category drill-down with cross-position "—" cells where a
  criterion doesn't apply to a player's position group
- Two new Jinja globals: `CATEGORY_LABEL_EN`, `urlencode_with`
- 26/26 synthetic E2E checks PASS
- Scout-vs-Wyscout dual radar **deferred** per spec's deferral path —
  textual category averages already convey the information

**Phase 5c-3: UI/UX polish — complete**

Project status ~88%. Six items + the soft-delete invariant.

- New `clubs` table (24 seeded) + `players.nationality_code` + `club_id`
  + `evaluations.deleted_at/by/reason` (with all-three-or-none CHECK)
- Backfill SQL extended beyond spec — all 3 existing players linked
  correctly (Sayed → Al-Riffa, Arthur → Al-Muharraq, Bouhra → Al-Khalidiya)
- Soft-delete invariant baked in: every read query in evaluations
  filters `WHERE deleted_at IS NULL`. Each helper has a docstring
  noting this so future maintainers don't bypass it.
- 309 nationality entries (Bahrain pinned first), generated once via
  pycountry (build-time only); flag emoji via Unicode regional
  indicators
- Soft-delete permission matrix: scout=own-drafts only; admin/TD=any
  non-locked; locked=blocked. Reason min 10 chars enforced both
  server-side and by DB CHECK.
- Admin recovery page at `/admin/deleted-evaluations` with restore
  action. Restore clears all 3 deleted_* columns atomically.
- 43/43 synthetic E2E checks PASS + 2 FK lifecycle invariants verified
  (clubs delete → player.club_id nulled and player survives; users
  delete with active soft-delete records → blocked by CHECK constraint
  preserving accountability)

**Phase 5c-2.1: Patch — complete**

Browser-spotted issues from 5c-2 cleaned up. No schema changes.

- Eligibility card moved above Wyscout dashboard on profile (most
  committee-relevant info first)
- `compute_eligibility_status` rewritten with 6-priority logic:
  birthright (`bahraini`/`foreign_ancestry`) is eligible regardless
  of date; explicit `eligible_from_date` overrides residency-derived;
  residency-derived (`foreign_residency` + `bahrain_residency_start_date`)
  computes Article 5 suggested date; pending and unknown branches
  separated cleanly
- Redundant "Status:" line removed from eligibility card; replaced with
  smaller "Route:" line using new `NATIONALITY_ROUTE_LABEL_EN` dict
- `group_scores_by_category` helper + section-collapsible expanded
  view in history cards, with per-category average + N/A counts
- Players list grew an `Eligibility` line per card + an HTMX-driven
  filter dropdown wired to `_ELIG_FILTER_CLAUSES` SQL constants
  (5-year residency math hard-coded, mirrors `RESIDENCY_YEARS_REQUIRED`)
- 48/48 synthetic E2E checks PASS (covers all 7 priority cases A–G
  plus 3 edge cases plus filter-inclusion matrix)

**Phase 5c-2: Final form story — complete**

True MVP: ~85% project status. The form story is closed.

- Schema: 2 cols on `players` (residency tracking) + 3 cols on
  `evaluations` (locked_reason, last_edited_by, last_edited_at);
  `locked_by` + `last_edited_by` FKs both ON DELETE SET NULL
- App: lock + unlock + admin-edit routes (admin/TD only, audit-logged);
  eligibility helpers (`compute_eligibility_status`,
  `compute_suggested_eligibility`, `RESIDENCY_YEARS_REQUIRED = 5`)
- Templates: profile renders eligibility card + history cards (replacing
  the placeholder); per-evaluation card has expandable scores grid +
  role-gated lock/unlock; player edit has Bahrain residency input with
  5-year Article-5 suggested-date UX + orphan-scores confirm modal on
  position change; form has sticky mobile save bar + soft-warning modal
  for <5 ratings + Arabic on action buttons
- Arabic translations baked verbatim from the spec's translation table
  on NT readiness section, eligibility options, action buttons
- 55/55 synthetic E2E checks PASS across all 17 acceptance criteria
- Lifecycle FK invariant verified: deleting a user who locked or edited
  an evaluation nulls the FK columns; evaluation + status preserved

**Phase 5c-1.1: Tri-state slider — complete**

- `evaluation_scores`: `score` nullable; new `is_not_applicable` BOOL;
  CHECK constraint enforces (rated XOR N/A); 14 existing rows backfilled
  cleanly via the DEFAULT clause
- Slider Alpine component now has 3 states: untouched / rated / N/A,
  with a ✕ reset button (visible only when rated) and an N/A toggle
  button. Both transitions are fully reversible.
- DELETE-then-INSERT semantics in `save_evaluation_scores` — untouched-
  after-rated naturally removes the row; no awkward "delete if cleared"
  branching
- View template renders N/A as a "N/A · غير متخصص" badge distinct from
  numeric scores
- 28/28 synthetic E2E checks PASS (pre-flight, schema convergence,
  POST tri-state matrix, DELETE-then-INSERT, CHECK enforcement,
  pre-fill on draft reload, submit, view-template badge, regression
  on 3 pre-migration evaluations)

**Phase 5c-1: Evaluation form — complete**

- 3 admin-set NT-eligibility cols on `players`; `evaluations.match_id`
  added with FK to `matches` ON DELETE SET NULL
- New evaluations blueprint: form (`/players/<id>/evaluate`), view
  (`/evaluations/<id>`), inline match create (`/matches/new-inline`)
- 7 templates including position-aware slider grid, NT readiness
  section, save-draft/submit workflow, inline match modal
- Untouched-slider behaviour: Alpine `dirty` flag toggles slider's
  `name` attribute so untouched sliders submit no key — DB stays NULL
- Admin/TD-only eligibility block on player edit form; "New Evaluation"
  button on player profile (scout role and above)
- 27/27 E2E acceptance checks PASS; lifecycle FK invariant verified
  (match delete nulls `evaluations.match_id`, evaluation preserved)

**Phase 5b: Matches table + Wyscout auto-link — complete**

- New `matches` table (15 cols, UNIQUE + 4 indexes); `wyscout_match_stats`
  gains `match_id` FK with `ON DELETE SET NULL`
- `app/wyscout/ingest.py` auto-links via case-insensitive lookup —
  re-uploads of the same xlsx don't create duplicates and preserve
  every existing `match_id`
- Backfill linked all 34 existing stat rows to 33 unique matches
  (one shared fixture between Arthur and Bouhra correctly dedup'd)
- Read-only `/wyscout/matches` admin/TD list with source badges +
  linked-stats counts
- Throwaway-namespace replay confirmed `schema.sql` and live DB
  converge; full lifecycle (create/read/update/delete) verified end-to-end

**Phase 5a: Criteria reseed + NT readiness columns — complete**

- `schema.sql` declarative source-of-truth updated in place:
  - `evaluations` table CREATE now includes 4 NT-readiness columns
    (`nt_readiness_level`, `eligibility_status`, `eligibility_notes`,
    `comparable_player`) and the new `evaluations_recommendation_check`
    value set (drops `not_ready`, gains `not_at_level`)
  - Criteria seed and position_group_criteria mappings replaced wholesale
    with the v2-LOCKED Phase 5 taxonomy (55 items, 303 mappings)
- `migrations/phase_5a_reseed.sql` — imperative migration applied to live
  DB; pre-flight + DO-block audit gate forced ROLLBACK on any mismatch
- `migrations/_generate_phase_5a.py` — taxonomy → SQL generator (rerun
  to update mid-pre-prod)
- `migrations/_verify_throwaway_db.py` — proved schema.sql and live DB
  converge by replaying schema.sql in an isolated namespace
- Per-position form sizes (verified twice — live DB + throwaway schema):
  GK 24, CB 42, FB 42, DM 40, CM 37, AM 42, W 38, ST 38

**Phase 4.1: Season aggregations + player comparison — complete**

Added on top of Phase 4:
- `app/wyscout/helpers.py` — `season_label_for_date()` (Aug 1 → May 31, `'YYYY/YY'`)
- `app/wyscout/aggregations.py` — `get_player_seasons()`, `get_player_radar_seasons()`,
  `compare_players()` + `validate_comparison()` (GK ↔ outfield restriction enforced;
  2-3 players; no zero-division)
- `app/players/__init__.py` — `/players/compare`, `/players/compare/search`,
  `/players/compare/view`
- New templates: `players/compare.html`, `players/_compare_search.html`,
  `players/compare_view.html`
- `app/templates/players/profile.html` — Career-by-Season table; radar refactored
  to multi-season overlay via `data-radar-seasons` JSON attribute
- `app/static/js/player_dashboard.js` — `initRadar()` rewritten for N datasets
- `app/static/js/compare.js` — overlapping radar for 2-3 players
- `app/templates/base.html` — `Compare` link in desktop + mobile nav
- 3 new Jinja globals registered

**Phase 4: Wyscout import — complete**

Implemented:
- `app/wyscout/parser.py` — `parse_wyscout_xlsx()` with `WYSCOUT_COLUMN_MAP`, match regex, date/position parsing
- `app/wyscout/helpers.py` — `RADAR_AXES`, `RADAR_THRESHOLDS`, `normalize_radar_axis()`
- `app/wyscout/ingest.py` — `ingest_wyscout()`: full transaction, UPSERT `ON CONFLICT (player_id, match_label, match_date)`, xmax insert-vs-update detection, audit log
- `app/wyscout/aggregations.py` — `get_player_summary()`, `get_player_match_history()`, `get_player_radar_scores()`, `get_player_trends()`
- `app/wyscout/__init__.py` — full blueprint: upload, result, imports list, delete, trends JSON API
- Templates: `wyscout/upload.html`, `wyscout/result.html`, `wyscout/imports.html`
- `app/templates/players/profile.html` — Wyscout placeholder replaced with live dashboard (summary cards, radar, 3 trend charts, match history table)
- `app/static/js/player_dashboard.js` — Chart.js 4 radar + 3 line charts
- Chart.js 4 CDN added to `base.html`
- `pandas>=2.0`, `openpyxl>=3.1` added to `requirements.txt`
- `age()` Jinja global added (players.helpers)
- 3 new Jinja globals registered: `get_wyscout_summary`, `get_player_match_history`, `get_player_radar_scores`

## Next phase

**Phase 6: Player Passport (PDF)** — the demo-ready milestone. Generates
a single-page PDF combining the player profile (bio, photo, position,
eligibility card), Wyscout aggregates (career-by-season table,
performance radar), and the latest committee evaluations (NT readiness
verdict, recommendation, key criterion scores). Likely uses WeasyPrint
or ReportLab. After 6 lands, the BFA-leadership demo story is closed.

**5d-follow-up (optional, small):** the scout-vs-Wyscout dual radar
deferred from 5d. Adds a second Chart.js canvas alongside the existing
Wyscout radar, plotting the four scout category averages per player.
Bundle into 5e if 5e ships first.

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

## Deferred polish (do before Phase 8 deploy)

### Phase 5d — Scout dimension on comparison
- Comparison page includes scout aggregates (category averages, NT readiness summary, divergence flag)
- Same-position-group restriction for per-criterion comparison
- Scout-radar-vs-stats-radar overlay on player profile (the "do the numbers and the eye agree?" view)

### Comparison view UX
- Bio↔column visual binding (mini player headers above table, player-tinted column bands)
- Drop green-highlight from raw counting metrics (matches, minutes, shots, cards) — misleading
- Mobile responsive pivot

### Phase 1 auth polish
- Login UI redesign
- Password reset flow (email-based)
- "My Profile" edit form
- Replace Werkzeug 401 default page

### Data hygiene
- Bouhra's nationality typo: "Marocoo" → "Morocco"
- Scout user (`scout@bfa.bh`) created during Phase 1 testing — confirm still needed or remove

### Cross-cutting
- Mobile responsiveness pass across player profile / comparison / Phase 5c form
