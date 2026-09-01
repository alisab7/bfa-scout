# Changelog

## v1.10.0 — First-Team Squad: admin-curated squad table + NT squad view (2026-09-01)

### What this is

After the 26/27 residents intake the players list mixes established
first-team / call-up-ready players with 88 freshly-imported prospects
(incomplete data, still counting toward eligibility). A coach opening the
app cannot see "the squad". This adds a manually-curated squad: an admin
picks who is in it, and a coaching view shows only those players.

Deliberately **no eligibility gate** — a still-counting `foreign_residency`
prospect and a born citizen are equally addable. Membership is an editorial
decision; the eligibility badge rides along for context, never as a filter.
Removing a player from the squad removes the **membership row only** — the
player record is never deleted.

### Changes

**Schema** — `squad_members(id, player_id UNIQUE FK→players ON DELETE
CASCADE, added_by FK→users, added_at)`. Mirrors `youth_shortlist` exactly:
`CREATE TABLE IF NOT EXISTS` + inline `UNIQUE (player_id)` (NOT the invalid
`ADD CONSTRAINT IF NOT EXISTS`), plus an index on `player_id`. Adds use
`INSERT … ON CONFLICT (player_id) DO NOTHING`, so adding twice never
duplicates and never rewrites the original `added_by`/`added_at`. Migration
`migrations/squad_members.sql` closes with a DO-block audit gate that
RAISEs (→ ROLLBACK) if the table or the UNIQUE constraint is missing —
without the constraint the route's `ON CONFLICT (player_id)` would fail at
runtime.

**Management screen** — `/admin/squad` (**admin only**, `admin_required` —
tighter than assign-clubs/assign-positions, which are `admin_or_td_required`,
because squad selection is the admin's editorial call). Bulk-select
mechanics copied from `/admin/assign-clubs`: `name="player_ids"` checkboxes
+ a select-all header box + one submit. Because the candidate pool is now
~88 prospects plus the existing roster, the list carries server-side
filters: search (name EN/AR or National / BFA ID), position, club
(including "No club set"), and a squad-membership filter
(Everyone / Not in squad / In squad). Filters survive the POST → redirect,
so a save lands back on the same filtered page. Already-in-squad rows show
a disabled checkbox and an "In squad" marker. Each member has a Remove
button (membership only, with a confirm). Explicit `conn.commit()` on every
write; add / remove both `log_audit`'d (`player.squad_added`,
`player.squad_removed`).

**Squad view** — `/nt/squad`, a third tab in the National Team workspace
next to Citizens and Residents (`admin_or_nt_staff_required` → admin + TD +
nt_staff; scout / viewer / youth_nt get a real 403, and the tab is hidden
from scouts on `/nt/residents`, the one /nt page they can see). Shows ONLY
`squad_members` rows: photo via `get_player_photo(player_id)` with an
`onerror` placeholder fallback, name + National / BFA ID, position via
`get_player_pos(position_id)`, club, the shared
`_macros/eligibility_badge.html` badge driven by
`compute_eligibility_status`, and who added them when.

**Placement rationale** — the squad view is a coaching read surface, not an
admin tool, and its audience (admin + TD + nt_staff) is exactly the /nt
workspace audience. It mirrors the youth shortlist, which is likewise a
curated list surfaced as a tab inside its own section (`/youth/shortlist`)
rather than a filter bolted onto the general players list. A "Squad only"
filter on `/players` was rejected: `/players` excludes youth players and is
open to viewers, so it is both too narrow (no youth call-ups) and too wide
(wrong audience) for this list.

**E2E** (`migrations/_e2e_squad.py`) — real HTTP on :5057 (no
flask.test_client), 46 checks, all passing. Every player AND user fixture is
seeded by the suite and torn down in `finally:` — nothing is read out of
ambient DB state. Covers: bulk-add 3 → rows persist → all 3 render after a
reload; remove 1 → gone from the view while the `players` row stays intact;
idempotent re-add (COUNT stays 1, original `added_at` preserved); a
never-added player absent from the view; no eligibility gate (a
2-years-into-residency prospect is addable and renders its "Eligible in Xy
Ym" counting badge; a citizen renders the Citizen badge — both cross-checked
against `compute_eligibility_status`' own return value); auth (TD /
nt_staff / scout / viewer / youth_nt all 403 on add and remove, with the DB
asserted unchanged after each attempt; view 200 for admin/TD/nt_staff, 403
for the rest); commit persistence across a fresh connection.

### Files

- `migrations/squad_members.sql` — table + index + audit gate (run on prod BEFORE the app restart)
- `migrations/_apply_squad_members.py` — apply script (same semantics as the other `_apply_*.py`)
- `migrations/_e2e_squad.py` — E2E suite
- `app/nt/helpers.py` — `get_squad_member_ids`, `add_players_to_squad`, `remove_from_squad`, `get_squad_members`
- `app/nt/__init__.py` — `/nt/squad` route (`first_team_squad`)
- `app/admin/squad.py` — `/admin/squad{,/add,/remove}` routes
- `app/admin/__init__.py` — registers the squad routes
- `app/templates/nt/squad.html` — squad view
- `app/templates/admin/squad.html` — management screen
- `app/templates/nt/index.html`, `app/templates/nt/residents.html` — third tab in the strip
- `app/templates/base.html` — "First-Team Squad" in the admin-only block of Admin Tools (desktop + mobile)
- `schema.sql` — `squad_members` section added after `youth_shortlist`

---

## v1.9.6 — 26/27 residents intake: Report.xlsx → Phase-9 bulk import + gap-list (2026-08-31)

Imports the 88 wanted resident/passport players from the 112-row management file
(`Report.xlsx`, sheet "Main") through the EXISTING Phase-9 bulk importer — no parallel
import path. Honest import: blanks stay blank, no invented dates or origins.

**Whole-row highlight exclusion (24 rows NOT imported)** — the source file marks players
not wanted this season by filling the whole row yellow (`FFFFFF00`) or red (`FFFF0000`).
The transform reads the workbook WITH styles (openpyxl, NOT `data_only`) and excludes any
data row with ≥7 solid-filled cells of one of those colors across the 10 columns (a single
highlighted cell is a column note — the player is kept). Result: 21 yellow + 3 red = 24
excluded / 88 kept, hard-cross-checked in the script against the ratified 24-BFA-ID
exclusion list — any disagreement aborts before writing anything. The 4 withdrawn (سحب)
rows are all inside the excluded 24.

1. **Transform script** (`scripts/transform_report_residents.py`) — deterministic file-level
   mapping only (no DB access): English full name from First+Family; `BFA ID Number` →
   `national_id` (the 4 placeholder-"New" rows stay blank + gap-listed); DOB from datetime
   cells and DD/MM/YYYY strings (2 blanks kept blank); Arabic club → `current_club_name`
   via an exact 16-entry ratified table (strips U+200E; unmapped = hard failure, NO fuzzy
   matching); `Tumooh Feedback == 'لديه الجواز'` → `nationality_status='bahraini'` (passport
   holder, origin PENDING), everything else → `'foreign_residency'`;
   `bahrain_residency_start_date`/`origin_country`/position NEVER set. Years bucket +
   Tumooh feedback + source Comment land in `players.notes`, labelled as management's
   interim estimate (NOT an entry date). Outputs `exports/residents_2627_import.csv`
   (feed to /admin/players/bulk-import) + `exports/residents_2627_gap_list.csv`
   (88 need entry date; the 44 passport holders need origin; flags for missing
   BFA ID ×4, missing DOB ×2, blank nationality ×1). `exports/` is git-ignored
   (generated, derived from a management source file).

2. **Bulk importer extensions** (`app/admin/bulk_import_helpers.py`) — additive:
   `notes` joins `ACCEPTED_COLUMNS`/`build_db_params`; `find_duplicate` gains two
   tightly-gated fallbacks for id-less rows (name+DOB when no position code is supplied;
   name-only matching ONLY a dob-IS-NULL player when the row has no id/dob/position) so
   re-importing the registry stays idempotent. Existing strategies untouched.

3. **Relabel (display only)** — the `national_id` field now shows as "National / BFA ID"
   in the player new/edit forms, profile, youth form, passport view, assign-clubs table,
   and the two validation messages. Column name unchanged.

4. **E2E** (`migrations/_e2e_residents_2627_import.py`) — real HTTP on :5057 (no
   flask.test_client): seeded-duplicate never overwritten (skip default); real import
   verifies 88 rows / 44 bahraini + 44 foreign_residency / all 24 excluded BFA IDs absent /
   0 unmapped clubs / NULL origin+residency date+position / notes labelling / relabel
   rendered; idempotent re-run creates 0 rows; eligibility surfaces render gracefully with
   NULL dates. Relabel coverage extends to `/admin/assign-clubs` (seeds one club-less row
   so the table header renders, then deletes it), the youth intake form and the passport
   PDF text layer; eligibility cases assert `compute_eligibility_status`' own return value
   alongside the rendered page, so a pending player can never be papered over as
   "Eligible now". 51 checks, all passing.

5. **Phase-9 suite hardened** (`migrations/_e2e_phase_9.py`) — the duplicate-detection
   cases needed a player carrying DOB + position + national_id and simply looked one up in
   the DB, which crashed (`NoneType`) once the DB held only registry rows with NULL
   positions. It now seeds that fixture itself when none exists and registers it for the
   existing `finally:` cleanup, so the suite is self-contained and leaves the DB untouched.

**Files**: `scripts/transform_report_residents.py`, `app/admin/bulk_import_helpers.py`,
`migrations/_e2e_residents_2627_import.py`, `migrations/_e2e_phase_9.py`,
`app/players/__init__.py`, `app/youth/__init__.py`, player/admin/passport templates,
`.gitignore`

## v1.9.5 — Draft evaluations: persist correctly + resume from profile (private to author) (2026-07-06)

**Diagnosis**: drafts already persisted (all three helpers commit explicitly). The real bugs were:

1. **Incomplete draft blocked** — the draft-save path enforced `position_played_id` as required
   even for `action=save_draft`. Fixed: this check now only applies for `action=submit`.
   Drafts are explicitly allowed to be incomplete. (`app/evaluations/__init__.py`)

2. **No "Resume draft" affordance** — the player profile had no way to surface an in-progress
   draft back to its author. Fixed: `player_profile` route now calls `get_own_draft_for_player`
   (new helper) and passes `own_draft` to the profile template. When a draft exists, the header
   "New Evaluation" button becomes "Resume Draft", and a banner appears in the Evaluations section.
   (`app/players/__init__.py`, `app/templates/players/profile.html`)

3. **Draft privacy gap** — `get_evaluation()` applied NT-visibility filtering but not
   author-only filtering for drafts. A user who guessed an eval_id could view another user's
   draft. Fixed: `get_evaluation()` now accepts `requesting_user_id`; when provided, adds
   `AND (e.status != 'draft' OR e.evaluator_id = <user_id>)` at query level. Both page-load
   routes (`view`, `update_draft`) pass `requesting_user_id=current_user.id`.
   Non-author draft requests return 404 (same shape as not-found). (`app/evaluations/helpers.py`,
   `app/evaluations/__init__.py`)

**New helper**: `get_own_draft_for_player(player_id, user_id)` — author-only draft lookup for the
profile affordance. (`app/evaluations/helpers.py`)

**Files**: `app/evaluations/helpers.py`, `app/evaluations/__init__.py`,
`app/players/__init__.py`, `app/templates/players/profile.html`

---

## v1.9.4 — Sort match lists recent-first with NULLS LAST (2026-07-04)

Both match-date queries now use `ORDER BY match_date DESC NULLS LAST` instead of
plain `DESC`, pushing any hypothetical null-date rows to the bottom rather than
the top (PostgreSQL DESC defaults to NULLS FIRST).

**Files changed:**
- `app/evaluations/helpers.py` (`get_recent_matches`): `match_date DESC NULLS LAST, id DESC`
- `app/wyscout/aggregations.py` (`get_player_match_history`): `match_date DESC NULLS LAST`

No schema or template changes.

---

## v1.9.3 — Evaluation match dropdown: vs-opponent labels + own-club filter (2026-07-04)

(See previous session for details.)

---

## v1.9.2 — Recent Matches: true vs-opponent + own-club filter via club_aliases resolver (2026-07-04)

Display-time opponent resolution for the Recent Matches table on player profiles.
No database writes — fully computed at render from existing club_aliases data.

**Opponent display:** each match row now shows "vs Al Hadd" (the opposing team)
instead of "Al-Muharraq vs Al Hadd" when the player's club is identified in
the match via the alias resolver. Falls back to the existing "home vs away"
display when the resolver returns None (unmapped team string, or player has no
club assigned).

**Own-club filter:** a "My club only" toggle appears in the Recent Matches
header when the player has a club and at least one own-club match is present.
Client-side Alpine filter — rows carry a server-rendered `data-own-match`
attribute; the toggle shows/hides them without a page reload. Hidden entirely
for players with no club assignment.

**Implementation:**
- `app/clubs/resolver.py`: adds `enrich_match_history_with_opponent(matches,
  player_club_id)` — single batch DB query over all team strings in the match
  list; sets `opponent` (str|None) and `own_match` (bool) on each row dict.
- `app/clubs/__init__.py`: exports the new function.
- `app/__init__.py`: registers `enrich_match_history_with_opponent` as a
  Jinja2 global (alongside the existing wyscout globals).
- `app/templates/players/profile.html`: wraps `get_player_match_history` with
  the enrichment call; restructures the Recent Matches header (div + two
  buttons instead of one full-width button); adds filter toggle; adds
  `data-own-match` + `x-show` to each `<tr>`.

**Graceful degradation:** players with no `club_id` get `own_match=False` and
`opponent=None` on every row; the filter button is not rendered.

**Al Hadd → Al-Hidd:** the critical spelling variant resolves correctly via
the existing alias — "Al Hadd" in a match becomes Al-Hidd's club_id, and an
Al-Hidd player sees "vs Muharraq" for that fixture.

**Files:** `app/clubs/resolver.py`, `app/clubs/__init__.py`, `app/__init__.py`,
`app/templates/players/profile.html`.

---

## v1.9.1 — Nav: collapsible "Admin Tools" section groups all admin screens (2026-07-04)

Nav-only change. No routes, auth, or admin screen logic changed.

Groups all 8 admin screens under a single collapsible "Admin Tools" entry in
both desktop and mobile nav. Previously only Users and Club Aliases had nav
links; the other 6 screens were reachable by direct URL only.

**Gating:** whole section visible to `admin + TD`; admin+TD tools (Club
Aliases, Assign Clubs, Assign Positions) shown to both; admin-only tools
(Users, Bulk Import, Registry Import, Photo Import, Deleted Evaluations)
gated by `has_role('admin')` within the section.

**Implementation:** adds `adminOpen: false` to the existing nav `x-data`
object; uses the same `x-show`/`x-cloak`/`@click` Alpine idiom already in
the codebase. Desktop: absolute-positioned dropdown. Mobile: inline expand.
Default collapsed. No new JS library.

**Files:** `app/templates/base.html` only.

---

## v1.9.0 — Club aliases table + resolver + admin management screen (2026-07-04)

### What this is

Keystone for match reconciliation. Wyscout match data stores teams as
free-text strings ("Muharraq", "Al Hadd") that share 0 exact matches with
`clubs.name` ("Al-Muharraq", "Al-Hidd"). This blocked two features: true
vs-opponent on Recent Matches, and the league-matches filter. This session
builds the mapping layer those features will ride on (Session 2 wires them up).

### Changes

**Schema** — `club_aliases(id, club_id FK→clubs, alias_text, created_at)`.
Unique constraint on `LOWER(alias_text)` (case-insensitive uniqueness, one
match-string → exactly one club). Migration: `migrations/phase_club_aliases.sql`.

**Seed** — 12 real match-team strings from `wyscout_match_stats` mapped to
canonical clubs. Mapped by `clubs.name` lookup (portable across dev/prod).
Includes the manual case: `Al Hadd → Al-Hidd` (spelling variant impossible to
resolve by normalization). Idempotent: `ON CONFLICT (LOWER(alias_text)) DO NOTHING`.

**Resolver** — `app/clubs/resolver.py: resolve_club_from_team_string(team_string)`
Case-insensitive lookup. Returns `club_id` or `None` — never guesses. Single
function all future callers use.

**Admin screen** — `/admin/club-aliases`: list all aliases, add new, reassign to
different club, delete. "Unmapped match strings" section shows any
`home_team`/`away_team` in `wyscout_match_stats` with no alias yet (currently 0
after seeding; catches future imports). Sidebar link in nav for admin users.

**Audit** — add / reassign / delete all logged via `log_audit`.

### Files

- `migrations/phase_club_aliases.sql` — table + idempotent seed (run on prod before restart)
- `app/clubs/__init__.py`, `app/clubs/resolver.py` — resolver package
- `app/admin/club_aliases.py` — admin routes
- `app/templates/admin/club_aliases.html` — admin template
- `app/admin/__init__.py` — registers club_aliases routes
- `app/templates/base.html` — adds "Club Aliases" to admin nav
- `schema.sql` — section 7b added

---

## v1.8.3 — Docs: align password-policy statements to enforced 8-char minimum (2026-06-27)

Doc-alignment fix only. No logic or behavior change.

Phase 8.1 (v1.0.1) originally specified a 12-character minimum. Phase 8.1.1
revised it to 8 characters — updating the code, the HTML forms (`minlength="8"`),
and the function docstring. The **module-level docstring** in `validators.py` and
several developer-facing docs were never updated and still said "12". This caused
the spec/code drift flagged in the security review.

**Files updated (docs/comments only — no code change):**
- `app/auth/validators.py`: module docstring updated from "Min 12 characters" to
  "Min 8 characters" with a note referencing the Phase 8.1.1 revision.
- `DEPLOY.md §11`: bootstrap-password comment updated to `≥8 chars`.
- `PROJECT.md` Phase 8.1 row: complexity note updated to `≥8`.
- `.env.production.example`: `ADMIN_PASSWORD` comment updated to `min-8-chars`.

**Confirmed unchanged:** enforcement line (`if len(password) < 8:`) · HTML form
`minlength="8"` · "Minimum 8 characters" help text in user-create/edit forms.

---

## v1.8.2 — Eligibility fetch consolidated; cross-surface consistency E2E (2026-06-27)

### Kills the starved-query bug class

The recurring "passport holder shows Citizen instead of countdown" bug was fixed
surface-by-surface multiple times. This change ends the class:

**`get_eligible_squad_players()` — fixed the one remaining gap**
- `app/nt/helpers.py`: `origin_country` and `origin_country_code` added to the
  SELECT. The WHERE clause was already correct (still-counting passport holders
  excluded via `origin_country IS NULL` gate), but the returned dict didn't carry
  the field — any future badge macro on the NT squad template would have been
  starved immediately.

**`ELIGIBILITY_REQUIRED_COLUMNS` constant**
- `app/players/eligibility.py`: module-level tuple documents the four fields every
  player SELECT for an eligibility surface must include. Codifies the invariant for
  future query authors; the E2E (below) is the live enforcement.

**Cross-surface consistency E2E — the permanent guard**
- New `migrations/_e2e_cross_surface_eligibility.py`: takes a single
  passport-holder (bahraini + origin, under 5y) and asserts the IDENTICAL
  "Eligible in 0y 6m" label across ALL surfaces:
  - players-list card badge (S1a)
  - player profile (S1b)
  - passport PDF — pypdf text extraction (S1c; same label because
    `_build_passport_eligibility` delegates to `compute_eligibility_status`
    for bahraini+origin)
  - comparison view badge (S1d)
  - /nt/residents still-counting countdown in parens (S1e)
  - /players?elig=pending filter card (S1f)
  - NOT in eligible_now filter (S1g)
  - NOT in /nt squad — WHERE still correctly excludes still-counting holders (S1h)
  - Born citizen: "Citizen" on HTML surfaces; PDF "Eligible now"/"Bahraini";
    in /nt squad with "Bahraini citizen"; in eligible_now bucket (S2)
  - Foreign resident: countdown on list + profile + /nt/residents (S3)
  - Cross-surface label agreement assertions (S4)
- Any future query that drops `origin_country` → S1a–S1d fail immediately.

No behavior change. No schema migration. Pure-code refactor + guard.

---

## v1.8.1 — Fix: players-list card badge shows countdown for bahraini+origin (2026-06-25)

Naturalized players (bahraini + `origin_country`, e.g. Juninho, Soufian
Mahrouq, Vinícius Vargas) wrongly showed the **"Citizen"** badge on the
players-list cards instead of their **"Eligible in Xy Ym"** residency countdown
— while the identical foreign-resident case (Elliot Simões) showed the
countdown correctly. Same class as the earlier origin read-bug. Pure-code, no
schema change.

### Root cause (the macro was fine — the query starved it)
The `eligibility_badge` macro already routes through `compute_eligibility_status`
(the source of truth). But that function reads `player["origin_country"]`, and
the **list query didn't SELECT it** — so origin was absent → treated as a born
citizen → "Citizen". The filter worked because it queries `origin_country`
directly in its WHERE clause; only the display query was starved.

### Fix the class — both queries feeding the badge macro
- `_search_players` ([players/__init__.py](app/players/__init__.py)) — players-list grid: added
  `pl.origin_country` to the SELECT.
- `compare_players` ([wyscout/aggregations.py](app/wyscout/aggregations.py)) — comparison cards
  (same latent bug): added `pl.origin_country` to the SELECT **and** to the
  rebuilt per-player dict (the function copies named fields, so the SELECT alone
  wasn't enough).
- The macro and `compute_eligibility_status` were already correct, so all
  surfaces now agree. Born-citizen → "Citizen" and foreign-resident → countdown
  unchanged. (Reported-but-unchanged: the `/nt` squad and eval-readiness
  hardcoded "Bahraini citizen" labels are separate, non-countdown surfaces and
  accurate in their context.)
- **Kept origin OFF the list:** feeding `origin_country` makes the badge's note
  (tooltip) carry "Origin: …" for passport holders. Since origin is
  profile/PDF-only, the badge macro gained a `show_note` param and the list +
  compare cards pass `show_note=False` — the visible countdown shows, but the
  origin note never reaches those surfaces (the `title` tooltip there is just
  the countdown label).

### Verification
- New `migrations/_e2e_list_badge_passport.py` — **14/14** (real HTTP, every
  category on rendered list HTML): bahraini+origin under-5y → "Eligible in 0y
  6m" (NOT "Citizen"); bahraini+origin past-5y → "Eligible now"; born citizen →
  "Citizen"; foreign resident → countdown; card == profile; the Pending filter
  still includes the passport holders; and the comparison view now shows the
  countdown too.
- Regression: passport-holders 47/0, eligibility-badge 13/0, residents-countdown
  5/0, nt-residents 17/0, 5c2.1 48/0, v1.0.2 pass.
- `migrations/find_passport_holders_prod.sql` — read-only SELECT for Ali to list
  every prod passport holder + their expected badge, to confirm the fix visually.

## v1.8.0 — Admin: bulk club-assignment screen (2026-06-25)

New admin screen **`/admin/assign-clubs`** to give imported players a club.
Bulk-imported players arrive with `club_id` NULL; a player's club is the
prerequisite for the upcoming match-reconciliation features (true "vs opponent"
on the profile, league-matches filter) — "which match side is the player's?"
is unanswerable without it. Pure code — no schema change (`club_id` /
`current_club` already exist).

### What landed
- Route ([admin/assign_clubs.py](app/admin/assign_clubs.py)), mirroring `/admin/assign-positions`
  (auth `admin_or_td_required`, structure, stale-form guard, `conn.commit()`,
  audit log). GET lists active club-less players (`club_id IS NULL`) with photo,
  name, position, squad, national ID. POST assigns the selected players to one
  club.
- **Bulk-select** UI ([assign_clubs.html](app/templates/admin/assign_clubs.html)): per-row
  checkboxes + select-all + a club dropdown (optgrouped Premier/First) +
  Assign. Workflow is club-by-club — tick a club's players, pick the club,
  assign, repeat. (Differs from assign-positions' per-row dropdowns, by design.)
- **Sets BOTH** `club_id` **and** `current_club` (= `clubs.name`) in one UPDATE
  so the FK and its denormalised text cache stay consistent. Stale-form guard
  (`AND is_active AND club_id IS NULL`) means a player already given a club
  isn't overwritten.
- Sidebar link added next to "Assign positions" ([list.html](app/templates/players/list.html),
  admin+TD).

### Verification
- New `migrations/_e2e_assign_clubs.py` — **15/15** (real HTTP, round-trip):
  lists club-less players (clubbed player excluded); assigns 2 players to club A
  → DB shows `club_id` + `current_club` = A's name → reload drops them from the
  list; a 3rd player assigns to a different club B; stale-form guard keeps an
  already-clubbed player; a scout is denied (403).
- Regression: assign-positions, passport-holders, eligibility-badge,
  nt-residents, youth, bulk-import, Phase 9, v1.0.2 — green (see below).

### Note
This is the **prerequisite** only. The `club_aliases` table (mapping
match-team strings → clubs) and the vs-opponent / league-filter features come
in later sessions, once players have clubs.

## v1.7.6 — Player profile: Recent Matches collapsible (2026-06-25)

The profile's **Recent Matches** card is now collapsible. Pure template change
— no schema, query, or data change.

### What landed
- [profile.html](app/templates/players/profile.html): the Recent-Matches header is now a
  toggle button (Alpine `x-data="{ rmOpen: true }"` + `@click` + `x-show`),
  with a rotating chevron and the match count in the header
  ("Recent Matches (10)"). **Defaults to open** so existing behaviour is
  preserved; click to collapse/expand. Same Alpine idiom already used by the
  shortlist-note control in this template (Alpine core only — no `collapse`
  plugin needed; `x-cloak` intentionally omitted since the section defaults
  open, and the app has no global `[x-cloak]` rule).

### Verification
- `migrations/_e2e_recent_matches_opponent.py` extended to **15/15** (real
  HTTP): collapsible wrapper (`x-data` rmOpen), toggle button
  (`@click="rmOpen = !rmOpen"`), body bound to `x-show="rmOpen"`, default-open
  (rows still server-rendered), and the count in the header — all asserted on
  the rendered profile HTML. Existing opponent cases (M1–M5) still pass.
- Regression: passport-holders 47/0, eligibility-badge 13/0, nt-residents 17/0,
  5c2.1 48/0, v1.0.2 pass.

## v1.7.5 — Player profile: show opponent in Recent Matches (2026-06-25)

The profile's **Recent Matches** rows showed only the date. Each row now also
shows who the match was against. Pure template change — no schema, no query
change, no match-data change.

### What landed
- [profile.html](app/templates/players/profile.html) Recent-Matches "Match" cell now appends the
  opponent next to the date, e.g. **"01 May 26 · Al Muharraq vs Riffa"**.
- The data was already there: `get_player_match_history`
  ([wyscout/aggregations.py](app/wyscout/aggregations.py)) already SELECTs
  `home_team, away_team, is_home` — only the template wasn't rendering them.
- **Opponent choice (data-driven):** `wyscout_match_stats.is_home` (the field
  that would identify the player's own side) is **NULL across all rows** — the
  Wyscout import doesn't populate it — so the template shows **both teams
  ("home vs away")**, which is always correct. It auto-upgrades to a single
  **"vs &lt;opponent&gt;"** if `is_home` is ever set (TRUE → away team, FALSE →
  home team). Missing teams degrade gracefully to date-only.

### Verification
- New `migrations/_e2e_recent_matches_opponent.py` — **10/10** (real HTTP,
  asserts on rendered profile HTML): both-teams row → "Al Muharraq vs Riffa";
  single team → "vs Sitra"; `is_home=TRUE` → "vs Manama" (own team hidden);
  `is_home=FALSE` → "vs Budaiya" (own team hidden); no-teams row renders
  date-only with no stray "vs"; opponent text matches the DB record.
- Regression (profile is shared — all player types render): passport-holders
  47/0, eligibility-badge 13/0, nt-residents 17/0, youth 28/0, bulk-import
  40/0, Phase 9 46/0, v1.0.2 pass. phase_6_1 = 52/3 (the documented
  pre-existing flag/timing fails; unrelated, unchanged).

## v1.7.4 — Fix: still-counting passport holders wrongly shown "eligible now" (2026-06-25)

A **code** bug (not data): the eligibility filters classified **every** Bahraini
as eligible-now, including passport holders (bahraini + origin_country) whose
5-year residency clock is **not yet complete** — so a still-counting holder
(e.g. prod player 84) wrongly appeared under "Eligible now". `compute_
eligibility_status` already handled this correctly; two SQL filters predated
passport holders and disagreed with it.

### Fixes (mirror compute_eligibility_status — passport holder = residency route)
- `players/__init__.py` `_ELIG_FILTER_CLAUSES` (the `/players?elig=` list
  filter): the birthright "always eligible now" branch now excludes passport
  holders (`bahraini AND origin_country IS NULL` = born citizen only); passport
  holders run the 5-year residency math like `foreign_residency` in BOTH the
  `eligible_now` and `pending` buckets. Extracted a shared `_RESIDENCY_ROUTE`
  predicate so the two clauses can't drift.
- `nt/helpers.py` `get_eligible_squad_players` (the `/nt` senior "eligible NOW"
  squad): same fix — a still-counting holder is no longer on the eligible
  squad; they appear (with countdown) on `/nt/residents` until 5y completes.
- Born-citizen and foreign-residency behaviour unchanged in both.

### Data fix for the 3 mis-coded players (Ali runs the SQL on prod)
- `migrations/fix_naturalized_passport_holders.sql`: a read-only candidate
  query (foreign_residency players with a foreign nationality_code + NULL
  origin) + a guarded, idempotent UPDATE template (set
  `nationality_status='bahraini'`, `nationality_code='BHR'`, `origin_country`/
  `origin_country_code`; keep `bahrain_residency_start_date`). Logic validated
  transactionally on the dev DB's same-shaped rows, then rolled back. Once a row
  is bahraini + origin, all surfaces (filter, profile, PDF, residents) are
  already correct.

### Verification
- `migrations/_e2e_passport_holders.py`: **47/47** (was 40). New **P16** locks
  the player-84 regression over real HTTP: still-counting holder NOT in
  `/players?elig=eligible_now` but IS in `?elig=pending`; 5y-complete holder +
  born citizen ARE eligible_now; foreign resident (counting) is pending. (Plus
  an in-process check of `get_eligible_squad_players`.)
- Regression: /nt senior-squad 11/0, nt-residents 17/0, eligibility-badge 13/0,
  residents-countdown 5/0, 5c2.1 48/0, v1.0.2 pass.

## v1.7.3 — Drop "Passport holder" tag; BFA logo in the passport PDF (2026-06-25)

Two display changes for naturalized Bahrainis. Pure template/code — no schema,
no eligibility-logic change.

### Change 1 — removed the "Passport holder" tag (kept origin + countdown)
A bahraini+origin player now shows simply **Bahrain (+flag) · Origin: <country>
(+flag) · countdown** — the `🛂 Passport holder` label is gone everywhere it
rendered. The underlying logic (bahraini + origin → countdown via
`compute_eligibility_status`) and the `is_passport_holder` flag (template
condition) are unchanged.
- `players/eligibility.py`: eligibility note `"Passport holder · origin {X}"`
  → `"Origin: {X}"` (single source rendered on both profile card **and** PDF).
- `profile.html`: removed the `🛂 Passport holder` line under Origin.
- `passport.html`: removed the `· Passport holder` span (kept origin + flag).
- `nt/_residents_table.html`: residents row `🛂 Passport holder · Origin: X`
  → `Origin: X`.
- Dropped the now-unused `.passport-holder-tag` CSS.

### Change 2 — BFA logo in the passport PDF header
The top-left text wordmark (`BFA` / "Bahrain Football Association") is replaced
by the real **BFA logo** (`app/static/img/bfa-logo.png`). Embedded as a base64
**data URI** via a new `_resolve_logo_data_uri()` (module-cached), mirroring the
player-photo approach so the PDF stays self-contained (WeasyPrint's network
fetcher is unreliable). Falls back to the text wordmark if the file is missing;
"Bahrain Football Association" kept as a subtitle; "Player Passport" title
unchanged on the right.

### Verification
- `migrations/_e2e_passport_holders.py`: **40/40** (was 37). Inverted the old
  "shows Passport holder" assertions to assert the string is **absent** on the
  profile, the PDF (real-HTTP + pypdf text), the players list, and the residents
  row — while keeping origin + countdown checks. New **P15**: logo embedded as a
  `data:image/png` URI in the header (`class="brand-logo"`), text wordmark
  replaced, real-HTTP PDF still generates.
- Regression: eligibility-badge 13/0, residents-countdown 5/0, nt-residents
  17/0, v1.0.2 pass. **phase_6_1 = 52/3 — the 3 fails are the documented
  PRE-EXISTING ones** (flag-inline / inline-svg / timing-log); zero new failures.

## v1.7.2 — Origin country + passport-holder + countdown in the PDF passport (2026-06-24)

Surfaces the passport-holder info (origin country, "Passport holder", NT
eligibility countdown) in the **PDF passport export**, matching the player
profile. Pure-code, no schema change.

### Root-cause finding (profile vs PDF)
- **Profile was NOT broken.** End-to-end check on current HEAD: the profile
  route SELECT already includes `origin_country`/`origin_country_code`
  ([players/__init__.py](app/players/__init__.py)), the template renders the Origin line + 🛂
  Passport holder + countdown, and a live E2E confirms it. The likely cause of
  the "not showing" report was either a player with origin set but
  `nationality_status` ≠ `bahraini` (by-definition not a passport holder → no
  display), or the **PDF** view (which genuinely omitted it) being read as "the
  profile". Locked the profile path with an edit-form round-trip E2E.
- **The PDF was broken**, two gaps: (1) its data query
  ([passport/data.py](app/passport/data.py)) didn't SELECT the origin columns; (2) it uses its
  own `_build_passport_eligibility`, whose `bahraini` branch short-circuited to
  "Eligible now / Bahraini citizen" **before** any origin/residency check — so
  a passport holder showed as a plain citizen with no countdown.

### What landed (PDF)
- Passport SELECT now pulls `origin_country` + `origin_country_code`; the data
  layer adds an `origin_label` + inline `origin_flag_svg` (profile parity).
- `_build_passport_eligibility`: for `bahraini + origin_country`, **delegates to
  `compute_eligibility_status`** (the profile's source of truth) and maps its
  keys → the passport card shape. Reuses the exact label/countdown (`Eligible
  in Xy Ym` / `Eligible now`) + the "Passport holder · origin <X>" note — **no
  new date math**. Born citizens (bahraini, no origin) and foreign-residency
  branches unchanged.
- Passport template ([passport.html](app/templates/passport/passport.html)) renders an Origin row
  (label + flag + "Passport holder" tag) next to Nationality, gated on
  bahraini + origin. The eligibility card already surfaces the countdown.

### Verification
- `migrations/_e2e_passport_holders.py` extended to **37/37** (was 26): added
  PDF cases via **real-HTTP GET of `/players/<id>/passport.pdf` + pypdf text
  extraction** — holder pending → PDF has Brazil + "Passport holder" + "Eligible
  in 0y 6m" + Bahrain; holder 5y-done → eligible now; born citizen → "Eligible
  now / Bahraini citizen", NO passport line; foreign resident → unchanged
  ("Eligible from"); and a profile↔PDF origin-consistency check.
- Regression: eligibility-badge 13/0, residents-countdown 5/0, nt-residents
  17/0, v1.0.2 pass. **phase_6_1 = 52 pass / 3 fail — the 3 fails
  (flag-inline / inline-svg / timing-log) are PRE-EXISTING**, proven via
  git-stash (identical 52/3 on clean code); my changes add ZERO new failures.

## v1.7.1 — Fix: origin_country blank on edit-form reload (2026-06-24)

**It was a READ bug, not a write bug.** The origin value saved correctly
(UPDATE/INSERT had the columns, the profile + residents view showed it, and
the DB stored both `origin_country` + `origin_country_code`) — but the player
**edit route's load query** ([players/__init__.py](app/players/__init__.py)) didn't SELECT the two
origin columns, so the edit form's `<select>` had nothing to pre-select and
read blank on reload. Looked like "not persisting."

### Fix
- Added `pl.origin_country, pl.origin_country_code` to the `edit_player`
  player-load SELECT. One line; no write/derivation/commit change (those were
  already correct). No schema change.

### Verification
- `migrations/_e2e_passport_holders.py` extended → **26/26**, incl. the
  previously-missing round-trip: after saving an origin, **GET the edit page
  and assert the dropdown pre-selects `<option value="BRA" … selected>`**
  (this would have failed before the fix), plus clearing origin → reverts to
  NULL / plain "Citizen".
- Regression: eligibility-badge 13/0, residents-countdown 5/0, nt-residents
  17/0, 5c2.1 48/0, v1.0.2 audit pass.

## v1.7.0 — Passport holders (Bahraini + origin country) (2026-06-24)

Naturalized players are framed as **Bahraini** with their original country
kept as **origin**, plus a "Passport holder" note. NT eligibility still runs
the **5-year residency clock** (eligible now, or counting down).

### The model (no boolean flag)
A passport holder is DEFINED by `nationality_status = 'bahraini'` **AND**
`origin_country` set. No `passport_holder` flag — presence of an origin
country on a Bahraini player makes them one.

### What landed
- **Schema** — `players.origin_country VARCHAR(64)` (real queryable data for
  origin-based analysis) + `origin_country_code CHAR(3)` (flag, mirrors
  `nationality_code`) + a partial index. Idempotent migration
  `migrations/passport_holders.sql` (`ADD COLUMN IF NOT EXISTS`, no invalid
  `ADD CONSTRAINT IF NOT EXISTS`); mirrored into `schema.sql`.
- **Eligibility** ([eligibility.py](app/players/eligibility.py)) —
  `compute_eligibility_status`: `bahraini + origin_country` now runs the
  **same** residency countdown as residents (reuses `_resolve_eligibility_date`
  + `humanize_time_until`, no new math) → "Eligible now" or "Eligible in
  Xy Ym", `is_passport_holder=True`, status_code eligible_now/eligible_future.
  `bahraini` with no origin → unchanged "Citizen". foreign_residency /
  ancestry / etc. → unchanged.
- **Profile** ([profile.html](app/templates/players/profile.html)) — passport holders show
  nationality **Bahraini** (+ flag), an **Origin: <country>** field (+ flag),
  and a **🛂 Passport holder** note, plus the eligibility countdown. **Origin
  is PROFILE-ONLY — never on the players list** (the list query never selects
  it).
- **Residents/eligibility view** ([nt/helpers.py](app/nt/helpers.py)) — filter widened to
  `foreign_residency OR (bahraini AND origin_country IS NOT NULL)`; passport
  holders appear with a "🛂 Passport holder · Origin: X" label and the same
  eligible-now/still-counting split + countdown.
- **Edit form** ([edit.html](app/templates/players/edit.html)) — admin/TD "Origin country"
  picker in the eligibility fieldset; the route stores the code + canonical
  name (`NATIONALITY_LABEL`), explicit `conn.commit()`. Settable on create too.

### Verification
- New `migrations/_e2e_passport_holders.py` — **23/23**: holder pending →
  Bahraini + Origin + "Passport holder" + "Eligible in 0y 6m"; holder 5y-done
  → eligible now; born citizen → "Citizen" unchanged; foreign resident →
  unchanged (foreign nationality, countdown, NOT relabeled); origin on profile
  but NOT the list; residents-view label + countdown matches the profile;
  filter returns exactly the bahraini+origin players; origin_country queryable;
  edit-form persists.
- Regression: residents-countdown 5/0, nt-residents 17/0, eligibility-badge
  13/0, 5c2.1 48/0, scout-nt-eval 20/0, /nt 11/0, phase_7 29/0, youth 28/0 +
  24/0, eval-position 13/0, assign-positions 12/0, youth-shortlist 24/0,
  bulk-import 40/0, Phase 9 46/0, v1.0.2 pass. Born-citizen + foreign-residency
  unchanged.

## v1.6.2 — BFA logo on the home/landing page (2026-06-24)

Completes the logo rollout (nav / login / favicon landed in commit
`1dd8ecd`). The home page at `/` now shows the BFA logo instead of the
placeholder triangle. Template-only; no schema, no migration.

### What landed
- **[index.html](app/templates/index.html)** — replaced the `△`/"BFA"-text crest:
  - Authenticated dashboard (post-login "Welcome back" page): BFA logo
    (80px) added above the welcome header.
  - Anonymous landing hero: the `.bfa-crest-placeholder` swapped for the
    BFA logo (96px).
  - Both reuse the established pattern:
    `url_for('static', filename='img/bfa-logo.png')` + `onerror` hide
    fallback (same as nav/login). Functional quick-action card icons are
    left as-is (they're glyphs, not the logo).

### Verification
- Post-login `/` (real HTTP, logged in) renders the hero logo + nav logo +
  favicons; logo still serves `200 image/png`; the old text crest is gone.
- Regression: v1.0.2 audit pass, nt-residents 17/0, residents-countdown
  5/0, youth functional 28/0.

## v1.6.1 — Residents table: eligibility countdown on pending players (2026-06-24)

`/nt/residents` "Still Counting" rows now show the **"Eligible in Xy Ym"**
countdown next to the date — the exact string the player profile shows.
No new date math, no schema change.

### What landed
- **Single source of the countdown** — extracted the formula (inlined twice
  in `compute_eligibility_status`) into `humanize_time_until(target_date)`
  ([eligibility.py](app/players/eligibility.py)): returns "Eligible in Xy Ym" for a future
  date, `None` for missing/today/past. The two profile branches now call
  it (byte-identical output — no behaviour change), and the residents
  helper reuses the **same** function, so values always match.
- **Residents helper** ([nt/helpers.py](app/nt/helpers.py)) — `get_resident_players`
  attaches `p['countdown'] = humanize_time_until(eligible_from_effective)`
  (None for eligible-now / no-date rows).
- **Template** ([_residents_table.html](app/templates/nt/_residents_table.html)) — pending
  ("Still Counting") rows with a date render "(Eligible in Xy Ym)" under the
  date. Eligible-now rows and the eligible-now/still-counting split are
  unchanged.

### Verification
- New `migrations/_e2e_residents_countdown.py` — **5/5**: ~6mo pending →
  "Eligible in 0y 6m"; ~14mo → "Eligible in 1y 2m"; eligible-now → no
  countdown; **residents countdown == the profile's value** for the same
  player.
- Regression: nt-residents 17/0, eligibility-badge 13/0, 5c2.1 48/0,
  scout-nt-eval 20/0, /nt 11/0, phase_7 29/0, youth 28/0 + 24/0,
  eval-position 13/0, assign-positions 12/0, youth-shortlist 24/0,
  bulk-import 40/0, Phase 9 46/0, v1.0.2 pass. (Pre-existing unrelated
  failures: 5c2 eval-lock/orphan, phase_6_1 passport rendering — not
  touched by this change.)

## v1.6.0 — Scout access: hide NT-staff evaluations + grant residents view (2026-06-24)

Two committee-access changes, governance/data-separation focused. No schema
change (`created_by_role` already exists).

### Part A — NT-staff evaluations are invisible to scouts (audit + lock)
**Audit finding: already enforced on every scout-facing surface.** The
Phase-7 rule (`_nt_visibility_clause`: scouts/viewers get
`AND created_by_role != 'nt_staff'`) is threaded through every
filter-aware helper (`get_evaluation`, `get_player_evaluations`,
`get_player_bio_counts`, `get_evaluation_count_active`,
`get_player_evaluation_aggregate`, `nt_readiness_summary`) **and every call
site passes `current_user.role`** — verified across: profile history list +
"N on record" + bio count, eligibility card, eval view (`abort(404)` when
hidden — **404, not 403**), update-draft, compare scout section, and the
passport PDF. The `/nt` NT-eval count query is on a scout-blocked page; no
JSON/API endpoint returns evals. **No code gaps — so this ships a security
E2E that proves and locks the boundary** rather than new filtering.
  - Flagged for Ali: hide set = **`nt_staff` only** (scouts still see
    scout/admin/TD evals). And one obscure non-surface — the
    position-change *orphan-score count* tallies all evals' scores incl.
    NT; left as-is (a transient number, not an eval/list/badge; fixing it
    risks the orphan add/delete flow).

### Part B — scouts can view `/nt/residents` (eligibility), not the senior squad
`/nt/` and `/nt/residents` shared `admin_or_nt_staff_required`. **Split**
into a new `residents_view_required` (admin/TD/nt_staff + **scout**, NOT
viewer) on `/nt/residents` only; the senior squad stays closed to scouts.
Nav ([base.html](app/templates/base.html)): "Residents" link now shown to scouts;
"National Team" link stays admin/TD/nt_staff. The senior `/nt` index
([nt/__init__.py](app/nt/__init__.py)) now **loops scouts to `/players/`** instead of a
bare 403 — so the residents-page "Citizens" tab (which links to `/nt`)
doesn't dead-end for a scout; they still never see the squad content.
Other non-permitted roles (viewer, youth_nt) still get 403.

### Verification
- New `migrations/_e2e_scout_nt_eval_hidden.py` — **20/20** (security gate):
  scout sees own eval not the NT eval; count = 1 not 2; direct NT-eval URL →
  **404** (not 403); own eval → 200; viewer also 404; admin/TD/nt_staff see
  both (count 2) + NT-eval 200 unchanged. Part B: scout `/nt/residents` 200,
  senior `/nt` 403, viewer residents 403, admin/TD/nt_staff 200, nav split.
- Updated `_e2e_nt_residents` (now 17/0) — the two assertions that encoded
  the old "scout blocked from residents" rule refreshed to the new boundary
  (scout 200 + sees nav link, still 403 on senior /nt).
- Regression: phase_7 29/0, phase_7.1 8/0, /nt 11/0, youth 28/0 + 24/0, 5d
  26/0, 5d-1 39/0, eval-position 13/0, assign-positions 12/0, youth-shortlist
  24/0, bulk-import 40/0, Phase 9 46/0, v1.0.2 audit pass. admin/TD/nt_staff
  views unchanged.

## v1.5.1 — Youth shortlist UX: button → modal (2026-06-20)

Front-end/template change only — **no backend, schema, route, or access
change**. The profile's permanent inline note box (clunky, cluttered every
youth profile) is replaced with a clean button-opens-modal pattern.

### What landed
- **[profile.html](app/templates/players/profile.html)** — admin/TD/nt_staff, youth players only
  (unchanged access):
  - The control is **folded into the existing action-button stack** (New
    Evaluation / Edit / Deactivate) as a subtle, equal-width button — not a
    second full-width red bar competing with the primary action.
  - **Not shortlisted:** a subtle accent-outline "★ Add to shortlist" button
    → opens an Alpine modal with an **optional** note textarea + Save / Cancel.
  - **On shortlist:** a green "★ On shortlist" pill (opens the edit modal) with
    small "Edit note" / "Remove" text-links beneath (Remove confirms).
  - The modal reuses the app's existing `_delete_modal` Alpine pattern
    (`x-show`/`x-cloak`, `fixed inset-0 bg-black/70` backdrop) and closes on
    Cancel, **Escape** (`@keydown.escape.window`), and **backdrop click**
    (`@click.self`). Both forms still POST to the unchanged
    `/players/<id>/shortlist` and `/shortlist/remove` with the CSRF token.
- Note stays optional (empty submits fine; backend already stores NULL).

### Verification
- `migrations/_e2e_youth_shortlist.py` extended — **24/24**: button shown
  before adding; modal markup present + Alpine-driven + hidden by default;
  form posts to the add route with a `note` field; backdrop/escape close
  attrs present; on-shortlist state shows Edit note + Remove; **empty-note
  add works**; access unchanged (scout/viewer/youth_nt 403); idempotent
  re-add, promotion-keep, remove all still pass.
- Regression: youth functional 28/0 + security 24/0, /nt 11/0, residents
  15/0, eval-position 13/0, assign-positions 12/0, bulk-import 40/0, Phase 9
  46/0, 5c2.1 48/0, v1.0.2 audit pass.

## v1.5.0 — Youth shortlist (tracked prospects) (2026-06-20)

A flat watchlist of youth prospects being tracked toward senior/NT call-up,
gathered into one page so coaches don't hunt across U17/U20/U23. Add/remove
from the player profile; view in a new Youth-area "Shortlist" tab. Coaching
side only — admin / TD / nt_staff.

### What landed
- **Schema** — `youth_shortlist` table (`migrations/youth_shortlist.sql`
  + `_apply_…py`, idempotent `CREATE TABLE/INDEX IF NOT EXISTS`, inline
  `UNIQUE(player_id)` — no invalid `ADD CONSTRAINT IF NOT EXISTS`). Mirrored
  into `schema.sql`. One row per player; `ON DELETE CASCADE`.
- **Add/remove from profile** ([profile.html](app/templates/players/profile.html)) — a toggle in the
  action column, gated to admin/TD/nt_staff: "+ Add to shortlist" (with a
  note) for youth players, or "★ On youth shortlist" with editable note +
  Remove. Routes `POST /players/<id>/shortlist` and
  `/players/<id>/shortlist/remove` ([players/__init__.py](app/players/__init__.py)),
  `admin_or_nt_staff_required`, explicit `conn.commit()`. Add is idempotent
  via `INSERT … ON CONFLICT (player_id) DO UPDATE` (re-add refreshes the note,
  never duplicates).
- **Shortlist tab** — `GET /youth/shortlist` ([youth/__init__.py](app/youth/__init__.py),
  admin/TD/nt_staff) + `youth/shortlist.html`, mirroring the U17/U20/U23 tab
  strip (residents pattern). Lists each tracked player with photo, age_group,
  position, note, and added-by/when. Tab link added to the squad strip + the
  youth landing (gated). Helpers in `youth/helpers.py`.
- **Access boundary** — scout, viewer, and youth_nt all get 403 on the
  shortlist routes/page (admin/TD/nt_staff only). youth_nt's existing
  restrictions are unaffected.

### (1.5) decisions (flagged)
- **Add only youth players** (U17/U20/U23); but a shortlisted player **kept**
  after promotion to senior (manual remove only) — the list shows their
  current age_group, and note-update/remove keep working. Per your "keep
  them" recommendation.
- `/youth/shortlist` is a static route → Werkzeug ranks it above
  `/youth/<slug>`, no collision with the squad sub-views.

### Verification
- New `migrations/_e2e_youth_shortlist.py` — **19/19**: admin/TD/nt_staff
  add + view; scout/viewer/youth_nt 403; profile button state; note shown;
  re-add updates note with no duplicate (UNIQUE); only-youth-add enforced;
  promoted player stays listed + note still editable; remove drops off;
  commit persists across a fresh connection.
- Regression: youth functional 28/0 + **security 24/0**, /nt 11/0, residents
  15/0, eval-position 13/0, assign-positions 12/0, bulk-import 40/0, Phase 9
  46/0, phase_7 29/0, v1.0.2 audit pass.

## v1.4.1 — Admin bulk position-assign screen (2026-06-20)

Bulk-imported players (registry Excel) arrive with no primary position —
the registry file has no position column — so the evaluate route correctly
redirects them to edit (criteria are position-group specific). Setting
positions one-by-one is slow; this adds a single screen to assign them in
bulk. The evaluate guard is unchanged.

### What landed
- **`/admin/assign-positions`** ([app/admin/assign_positions.py](app/admin/assign_positions.py),
  admin + TD) — lists active players with `primary_position_id IS NULL`
  (name EN+AR, squad, a grouped position dropdown per row), reusing the
  players' `_load_position_picker()` (identical options to the edit/eval
  forms). Save sets each chosen player's `primary_position_id`; blank rows
  stay unassigned; a stale-form guard only updates rows still NULL. Explicit
  `conn.commit()`. Audit-logged (`player.position_assigned`).
- **No group write needed** — `players` has no `position_group_id` column;
  the group is derived via JOIN (`positions.position_group_id`), so setting
  `primary_position_id` alone makes the evaluate guard pass — exactly how
  the edit form already works.
- Admin/TD-gated "Assign positions" link on the players list, next to the
  import buttons.

### (1.5) findings
- Edit sets position via plain `UPDATE primary_position_id`; group is never
  stored, always derived — confirmed. So bulk-assign mirrors that exactly.
- No schema change. Live dev DB had 0 position-less players (the ~35 are on
  prod); E2E creates fixtures.

### Verification
- New `migrations/_e2e_assign_positions.py` — **12/12**: position-less
  players listed; already-positioned excluded; assign sets
  `primary_position_id` (DB) and drops the player off the list; **evaluate
  redirects to /edit BEFORE and returns 200 on /evaluate AFTER**; blank rows
  stay unassigned; non-admin 403, TD 200; commit persists across a fresh
  connection.
- Regression: eval-position 13/0, /nt 11/0, residents 15/0, youth 28/0 +
  24/0, eligibility-badge 13/0, bulk-import 40/0, Phase 9 46/0, 5c2.1 48/0,
  5d 26/0, phase_7 29/0, v1.0.2 audit pass.

## v1.4.0 — Evaluations: record the position played in the match (2026-06-20)

Each evaluation now records the position the player actually played in
that match — which can differ from their registered primary position (a
winger fielded at ST). Per-evaluation context, **display-only**: it does
NOT change the player's registered position and does NOT affect which
criteria are shown.

### What landed
- **No schema change** — the `evaluations.position_played_id` column
  (FK → positions, nullable) already existed in `schema.sql` but was
  unused; this wires it up. Idempotent data migration
  `migrations/eval_position_played.sql` (+ `_apply_…py`) ensures the
  column (no-op `ADD COLUMN IF NOT EXISTS`, NOT the invalid
  `ADD CONSTRAINT IF NOT EXISTS`) and **backfills** existing rows to each
  player's primary position (0 rows left NULL).
- **Form** ([evaluations/form.html](app/templates/evaluations/form.html)) — a required "Position played"
  dropdown in the match-context block, reusing the players' grouped
  position picker (`_load_position_picker`), **defaulting to the player's
  primary position**. Server-side required validation in `_handle_form_post`
  (mirrors the existing match-required rule) + `update_draft`, plus
  `position_played_id` added to `_REQUIRED_ON_SUBMIT`.
- **Write** — `parse_meta_fields` parses it; `update_evaluation_meta`
  persists it via its field whitelist (existing `conn.commit()` path).
- **Display** — eval view ([view.html](app/templates/evaluations/view.html)) shows
  "Position played: CODE · Name"; the per-player history cards
  ([_history_card.html](app/templates/evaluations/_history_card.html)) show "· played CODE". `get_evaluation` +
  `get_player_evaluations` join `positions` for the code/name.
- Criteria still driven by `position_group_id` (the player's group) —
  **unchanged**; the player's registered primary/secondary position —
  **unchanged**.

### (1.5) findings
- Column already present (live DB + schema.sql), FK to positions, nullable,
  **never read/written** in code (vestigial) — so no DDL, just wiring +
  backfill.
- All 7 existing evals had NULL → backfilled to primary position.

### Verification
- New `migrations/_e2e_eval_position.py` — **13/13**: defaults to primary;
  saving a different position (ST for an LW winger) persists + shows on
  view; required-validation rejects a missing position (no draft created);
  registered primary stays LW; criteria driver (`position_group_id`)
  unchanged; submitted eval shows the played position in history; no NULLs.
- Regression: 5c2.1 48/0, 5d 26/0, 5d-1 39/0, 5d-patch 29/0, phase_7 29/0,
  phase_7.1 8/0, /nt senior+search 11/0, residents 15/0, youth 28/0 + 24/0,
  eligibility-badge 13/0, bulk-import 40/0, Phase 9 46/0, v1.0.2 audit pass.
  Updated `_e2e_youth_functional` (6h) to send the now-required position in
  its evaluate POST. Pre-existing unrelated failures (5c2 lock/orphan;
  phase_6_2_3 compare-search flag) confirmed identical at HEAD via stash.

## v1.3.3 — /nt: senior-only squad + live English/Arabic name search (2026-06-20)

Two changes to the National Team squad page (`/nt`). No role/permission
or eligibility-logic changes.

### What landed
- **Senior-only filter** — `get_eligible_squad_players()`
  ([app/nt/helpers.py](app/nt/helpers.py)) now restricts the squad to the 1st team:
  `(age_group = 'senior' OR age_group IS NULL)`, **added alongside** the
  existing eligibility clause (unchanged). Youth (U17/U20/U23) live on
  `/youth`. NULL-safe so a stray-NULL senior 1st-teamer is never hidden.
- **Live name search** — a client-side search box at the top of the /nt
  squad ([nt/index.html](app/templates/nt/index.html)). Each row carries a lowercased
  `data-name="english arabic"` ([nt/_squad_table.html](app/templates/nt/_squad_table.html)); a small Alpine
  component (`ntSquadSearch()`) filters rows live as you type, matching
  **both** English and Arabic names, case-insensitively. Clearing the box
  restores the full squad; a "no players match" message shows when a query
  hides everything. Pure client-side — no server round-trip, no
  localStorage.

### (1.5) findings
- /nt query had no age_group filter, so an eligible youth player could
  appear — fixed. Live DB: all active players `senior`, zero NULL → no one
  hidden by the new filter.
- /nt/residents (`get_resident_players`) and /youth (`get_youth_squad`)
  are independent and untouched; nt_staff access unchanged.

### Verification
- New `migrations/_e2e_nt_senior_search.py` — **11/11** (senior shown;
  youth excluded but on /youth; **NULL-age senior still shown**; residents
  + nt_staff /youth access unaffected; search input + EN/AR `data-name`
  markup present).
- Regression: residents 15/0, phase_7 29/0, phase_7.1 8/0, youth 28/0 +
  24/0, eligibility-badge 13/0, bulk-import 40/0, Phase 9 46/0, 5c2.1 48/0,
  v1.0.2 audit pass.
- **Data repair (separate from the feature):** restored player 2 (Arthur
  Rezende) to his canonical `foreign_residency` / residency-since-2020-12-06
  state. A prior `_e2e_5c2` run had left his `nationality_status` NULL
  (self-perpetuating: it snapshots whatever it finds), which made phase_7's
  /nt assertion fail at HEAD too (proven via stash). Restoring the baseline
  is self-healing — `_e2e_5c2` now captures the correct state and restores
  it; phase_7 stays green across re-runs.

## v1.3.2 — Eligibility badge: "Citizen" for bahraini/foreign_ancestry (2026-06-20)

Display-only fix. A Bahraini citizen (or ancestry-eligible player) was
showing the green badge **"Eligible now"** — a label that belongs to
*residency* players who have completed the 5-year naturalization clock. A
born citizen now reads **"Citizen"**.

### What landed
- **Single source of truth:** `compute_eligibility_status`
  ([app/players/eligibility.py](app/players/eligibility.py)) — `bahraini` and
  `foreign_ancestry` now return `label="Citizen"`, `status_code="citizen"`
  (note carries "Bahraini citizen · مواطن" / "Foreign-eligible (ancestry) ·
  مواطن"). `is_eligible_now` stays `True` (they ARE eligible) — only the
  label/colour key changed. `foreign_residency` keeps the date-based
  Eligible-now / Eligible-in / residency-not-set logic untouched.
- One fix propagates everywhere the badge renders: the
  `eligibility_badge` macro (card grid, comparison, search, eval-form
  header) and the profile eligibility card — both consume the same helper.
- **CSS:** new `.elig-badge[data-status="citizen"]` (green, same palette as
  eligible-now) in [style.css](app/static/css/style.css).
- `/nt` squad table already special-cased citizens inline ("Bahraini
  citizen"), and `/nt/residents` is foreign_residency-only — both
  unaffected. The passport PDF has its own separate label logic (out of
  scope; not the inline badge).

### (1.5) findings
- The badge label has a single source (`compute_eligibility_status`);
  `status_code` only drives CSS colour (no logic branches on it), so adding
  a `citizen` status was safe.
- `bahraini` hit "Eligible now" because Priority-2 (birthright) reused the
  eligible-now label/status; fixed there.

### Verification
- New `migrations/_e2e_eligibility_badge.py` — **13/13** (rendered profile
  card + list-grid `data-status`): bahraini/ancestry → "Citizen" (not
  "Eligible now"); residency past → "Eligible now"; future → "Eligible in";
  no-date → residency-not-set; not_eligible / unknown correct.
- Updated stale assertions that encoded the old label: `_e2e_5c2_1`
  (bahraini/ancestry expected "Eligible now" → "Citizen") and `_e2e_5c2`
  (states 3-4 used `bahraini` to test the date path — switched to
  `foreign_residency`, which also fixed a pre-existing failure there).
- Regression: residents 15/0 (eligible-now vs still-counting split intact),
  bulk-import 40/0, youth 28/0 + 24/0, Phase 9 46/0, v1.0.2 audit pass,
  5c2.1 48/0. Pre-existing unrelated failures (5c2 eval-lock/orphan-scores;
  phase_6_1 passport rendering) confirmed identical at HEAD via stash test.

## v1.3.1 — Registry import: Age Group drives nationality (status + country + code) (2026-06-20)

The registry importer now maps the **Age Group** column to FOUR fields, so
imported players get real eligibility instead of "unknown", and the
senior National Team label **NT** is accepted.

### What landed
- **`AGE_GROUP_MAP`** ([registry_import_helpers.py](app/admin/registry_import_helpers.py)) — Age Group →
  `(age_group, nationality_status, nationality, nationality_code)`:
  - `U17/U20/U23` → that group, **bahraini**, Bahrain, BHR
  - `NT` / `senior` → senior, **bahraini**, Bahrain, BHR (NT is the senior
    national team; DB never receives "NT" as age_group)
  - `residency` / `resident` → senior, **foreign_residency**, nationality +
    code **from the file** (required, validated)
  - anything else (incl. blank) → **ERROR** row, clear message (no silent default)
- **Optional nationality columns**, matched by **header text** (row 3):
  `Nationality` + `Nationality Code`. Citizen files without them still
  parse; residency files supply them. Code validated as exactly 3 letters
  (uppercased); resident rows missing nationality/code are ERROR rows.
- **INSERT + UPDATE** now write `nationality_status`, `nationality`,
  `nationality_code` (plus `age_group`). UPDATE sets them **directly** (not
  COALESCE) so re-importing **corrects earlier NULL** nationality fields.
- **Preview** ([registry_import_preview.html](app/templates/admin/registry_import_preview.html)) adds Eligibility /
  Nationality / Code columns (friendly labels: "Citizen (مواطن)" /
  "Resident (إقامة)"). Upload page documents the residency columns.
- **Residency template** generated at
  `sample_data/BFA_Player_Registry_Template_residency.xlsx` (gitignored;
  for Ali) with the two extra columns + an example row.

### (1.5) catches surfaced before building
- **Parser was fixed-position, not header-based.** Added header detection
  for the two optional columns only (A–F stay positional); "Nationality
  Code" matched before "Nationality" so the substring doesn't collide.
- **Behaviour change flagged:** blank Age Group was silently `senior`
  before; per the spec's no-silent-defaults rule it is now an **ERROR**
  (all real rows carry an explicit group).
- **UPDATE overwrites nationality** unconditionally (spec: correct prior
  NULLs); name_ar/dob keep COALESCE so they're never wiped.

### Verification
- `migrations/_e2e_bulk_import.py` extended — **40/40** (citizen
  U23/NT/senior → bahraini/Bahrain/BHR; residency Brazil/BRA from file;
  missing nationality, bad 3-letter code, bogus + blank label → ERROR;
  citizen file with no nationality columns still imports; re-import
  corrects prior-NULL fields; preview shows resolved fields).
- Regression: Phase 9 46/0, youth 28/0 + 24/0, residents 15/0, v1.0.2
  audit all-pass.

## v1.3.0 — Bulk import: Player Registry Excel + CPR-matched photos (2026-06-20)

Two admin-only, preview-then-confirm import pages so management can inject
the BFA Player Registry roster instead of hand-entering it.

### What landed
- **`/admin/import/players`** — upload the registry `.xlsx` → dry-run
  preview (NEW/UPDATE/SKIP/ERROR per row + counts) → confirm →
  transactional write. New: `app/admin/registry_import.py` (routes) +
  `registry_import_helpers.py` (parse/classify). Reads the
  `➡ Player Registry` sheet from row 4 via **openpyxl directly** (not
  pandas — preserves int-vs-text and datetime-vs-string so CPR/DOB rules
  work). Templates `admin/registry_import_{upload,preview,result}.html`.
- **`/admin/import/photos`** — multi-file image upload, matched to players
  by CPR derived from the filename → preview (MATCH/NO MATCH/ERROR) →
  confirm. New: `app/admin/photo_import.py` + 3 templates. Reuses the
  app's existing photo pipeline (`app/players/photos.save_player_photo` →
  Pillow 400×400 → `storage.put_player_photo`, keyed by player_id) so
  imported photos display identically to manual uploads.
- **`app/players/cpr.py`** — `normalize_cpr()`: the master-key normalizer.
  9-digit TEXT, restores Excel-stripped leading zeros (`503061` →
  `'000503061'`, `41209370` → `'041209370'`), rejects garbage. CPR is
  NEVER stored as a number.
- **Rules:** one player per CPR; **highest age group wins** (U23>U20>U17>
  senior) on in-file or vs-DB conflict; example rows skipped; idempotent
  (re-import → all UPDATE, no new rows); every rejected row reported with
  a reason (no silent drops). Sets `players.age_group`, so imported youth
  players route into `/youth/<group>` and out of the general list.
- Admin-only buttons "Registry import" + "Photo import" on the players
  list (next to the existing Phase 9 "Bulk import").

### (1.5) catches surfaced before building
- **`normalize_cpr()` did NOT exist** (spec assumed it did "per prior
  work"). Created it. The spec's reference impl also had a bug — it
  deleted *all* non-digits, turning `' 26/12'` into `'000002612'`, but the
  spec's own examples say reject. Implemented to the **examples** (pure-
  digit core required; embedded symbols rejected).
- **An existing generic Phase 9 importer** (`/admin/players/bulk-import`)
  already exists. This registry importer is separate (CPR-keyed, age-group
  rules, photos) but **reuses** its parked-session store
  (`bulk_import_session.py`) and the transactional commit pattern; Phase 9
  is untouched (46/46 still pass).
- **Photos are keyed by `player_id`, not CPR; `players.photo_path` is
  vestigial** (never read/written, even by manual upload). The importer
  matches CPR→player_id then reuses `save_player_photo`; it does NOT set
  `photo_path` — exactly matching manual-upload behaviour.

### Verification
- `migrations/_e2e_bulk_import.py` — **24/24** (real HTTP; builds a real
  registry `.xlsx`; born-2000 double-zero, example skip, highest-age-wins,
  malformed-CPR ERROR, idempotent re-import, youth routing, photo
  CPR-match incl. zero-stripped filename, non-admin 403; photos exercise
  the real dev local-FS pipeline).
- Regression: Phase 9 46/0, youth functional 28/0, youth security 24/0,
  residents 15/0, v1.0.2 audit all-pass.

## v1.2.0 — Youth NT section (U17/U20/U23) + restricted youth_nt role (2026-06-20)

Board-level expansion: youth scouting added as a dedicated section, plus
the codebase's **first restricted role** — `youth_nt`, which can see
**only** youth players. This is a governance/data-separation boundary, so
enforcement is at the **query level + real 403s**, never hidden-UI-only.

### What landed
- **Data layer** — `players.age_group VARCHAR(16) DEFAULT 'senior'`
  (`CHECK age_group IS NULL OR IN ('U17','U20','U23','senior')`), index
  `idx_players_age_group`, all existing players backfilled to `'senior'`.
  `users_role_check` widened (additive) to admit `youth_nt`. Idempotent
  DO-block migration `migrations/phase_youth_nt.sql` (+ `_apply_youth_nt.py`),
  mirrored into `schema.sql`. NO invalid `ADD CONSTRAINT IF NOT EXISTS`.
- **Youth section** — new `app/youth/` blueprint: `/youth` landing (U17/
  U20/U23 cards + live counts), `/youth/<group>` squad tables, and
  `/youth/<group>/new` (create with age_group FIXED to the sub-view's
  group). Templates `youth/index.html`, `youth/squad.html`, `youth/new.html`.
  Visible to all working roles except viewer (incl. youth_nt).
- **General list filter** — `/players` (and `/players/compare` search)
  exclude youth: `age_group = 'senior' OR age_group IS NULL` (NULL-safe).
  Youth players are reachable only via the youth section.
- **Age-group management** — squad selector on the player edit form,
  gated to senior staff (admin/TD/nt_staff). scout + youth_nt cannot
  change age_group (field ignored). Promotion to 'senior' moves a player
  back to the general list and out of youth_nt's visibility.
- **Restricted role + guards** (`app/auth/decorators.py`): `YOUTH_GROUPS`,
  `youth_section_access`, `youth_manage_required`, `deny_youth_nt`
  (route-level 403), `require_youth_access(player)` (object-level 403 for
  youth_nt on non-youth players). Applied to player profile/edit/
  deactivate/evaluate/eval-view; `/players` list, `/players/new`,
  `/compare`, `/nt`, `/nt/residents`, `/admin/*`, passport, wyscout,
  reports, api, ai all 403 youth_nt. youth_nt landing page = `/youth`.
- **Nav + labels** — Youth NT nav link (desktop + mobile) for all working
  roles except viewer; youth_nt sees ONLY the Youth NT link. `youth_nt`
  added to `ROLE_LABELS`/`VALID_ROLES` and the role-badge colour map.

### (1.5) catches surfaced before building
- **`age_group` name/casing collision (flagged).** `matches.age_group`
  already existed (lowercase `senior/u23/u20/u17`, = the match's level).
  The new `players.age_group` is UPPERCASE per spec and means the player's
  squad — different table, different semantics. Followed the spec exactly
  and isolated the two; flagged the dual convention.
- **Boundary wider than the spec's route table.** `/compare` (was
  `@any_authenticated` — already excludes youth_nt), passport (was
  `@login_required` only → would have leaked any senior player's PDF),
  wyscout, reports/api/ai were additional surfaces. Locked all via
  deny-by-default for the restricted role.
- **CRUD-vs-promotion tension.** youth_nt "creates" only inside a youth
  sub-view (age_group fixed); promotion stays senior-staff only.
- **NULL-unsafe exclusion filter.** `age_group NOT IN (...)` would hide
  NULL rows; used `= 'senior' OR IS NULL` + `DEFAULT 'senior'` instead.

### Verification
- `migrations/_e2e_youth_functional.py` — Suite A, **28/28** (functional).
- `migrations/_e2e_youth_security.py` — Suite B, **24/24** (security HARD
  GATE: youth_nt cannot reach any non-youth data by any probed route).
- Regression: residents 15/0, phase_7 29/0, phase_7.1 8/0, 5c2.1 48/0,
  5d 26/0, 5d-patch 29/0, 6.2.3 16/0, v1.0.2 audit all-pass (two stale
  audit assertions refreshed: role count is now 6, and a pre-existing
  false-negative `scout_or_above` check was fixed to match the assignment
  line). Pre-existing 5c3 "flag emoji" failures are unrelated drift from
  Phase 6.2.3 (emoji → SVG flags), not the youth filter.

## v1.1.0 — Residents view for the coaching team (/nt/residents) (2026-06-01)

A second coaching-team track alongside the existing `/nt` (citizens).
`/nt/residents` lists naturalization-pathway players
(`nationality_status = 'foreign_residency'`), split into **Eligible
Now** (5-year residency clock complete) and **Still Counting**
(future-eligible — shows the date, or "date not set" when no residency
start has been recorded). No schema changes, no new roles — purely an
additive view reusing existing data + date math.

### What landed
- `app/nt/__init__.py` — new `residents()` route at `GET /nt/residents`,
  same gate as `/nt` (`admin_or_nt_staff_required` = admin + TD +
  nt_staff, per Phase 7.1). `index()` untouched.
- `app/nt/helpers.py` — `get_resident_players()` → `(eligible_now,
  still_counting)`. Effective eligibility date per player =
  explicit `eligible_from_date` if set, else
  `compute_suggested_eligibility(bahrain_residency_start_date)`, else
  None. **No reinvented date math** — reuses the shared
  `app/players/eligibility.py` helper (residency_start + 5y, leap-safe),
  mirroring `compute_eligibility_status`'s priority order. Filters on
  `is_active = TRUE`.
- `app/templates/nt/_residents_table.html` — NEW. A variant of the
  `/nt` squad table that surfaces the eligibility **date** in its
  dedicated column (the base `_squad_table.html` only shows "5-yr
  residency" with no date), plus a "date not set" badge. Built as a
  variant rather than editing the shared partial → zero risk to `/nt`.
- `app/templates/nt/residents.html` — NEW. Two sections + a Citizens↔
  Residents tab strip + friendly empty states.
- `app/templates/nt/index.html` — added the matching tab strip
  (Citizens active) so the two tracks are mutually discoverable.
- `app/templates/base.html` — "Residents" nav link added next to
  "National Team" in BOTH nav blocks (desktop + mobile), same
  admin/TD/nt_staff gate.

### (1.5) catches surfaced before building
- **Spec SQL would error.** The spec's `get_resident_players()` sketch
  (and its pre-flight psql) filtered `players` on `deleted_at IS NULL`
  — but the `players` table has **no `deleted_at`** column (soft-delete
  lives at the evaluations layer, Phase 5c-3). Used `is_active = TRUE`,
  matching the existing `/nt` helper.
- **"/nt is citizen-only" is not reality.** The spec's locked decision
  called `/nt` "citizen-only", but `get_eligible_squad_players()`
  actually shows eligible players of ANY route (bahraini / ancestry /
  explicit-date / completed-5yr-residency), so eligible residents
  already appear on `/nt`. The hard rule "do NOT modify the `/nt`
  filter" resolves the contradiction: `/nt` is left UNCHANGED. The
  regression test asserts "/nt unchanged" (still shows the citizen,
  still excludes non-eligible residents), not "bahraini-only".

### Verified
- **New E2E: 15/15 PASS** ([migrations/_e2e_nt_residents.py](migrations/_e2e_nt_residents.py))
  — full permission matrix (nt_staff/admin/TD 200; scout/viewer 403;
  anon→login); section split (past→Eligible Now; future→Still Counting
  with date; no-date→Still Counting "date not set"); bahraini excluded;
  `/nt` unchanged; nav-link gating (present for nt_staff, absent for
  scout).
- **Regression: 272/272 across all 9 prior suites** (4.2, 5d-1, 6.0,
  6.1, 6.2, 6.2.1, 7, 7.1, 9). 6.1's timing-log assertion is coupled to
  a specific Flask log filename; once the dev server logs to the
  expected path it's 57/57 — not a code regression.

## v1.0.2 — Root-cause audit: missing commits + nt_staff propagation (2026-05-17)

### Audit 1 — missing conn.commit() sweep

Reviewed every write route across all blueprints. One confirmed bug found and fixed:

**HIGH** `app/wyscout/__init__.py::delete_import()` — `UPDATE wyscout_imports SET status='failed'` was missing `conn.commit()`. Admin saw the "Import marked as deleted" flash message but the database row was never changed. Fix: added `conn.commit()` immediately after the cursor context block, before the flash call.

All other write paths confirmed clean:
- `evaluations/helpers.py`: 9 write helpers — all committed ✅
- `players/__init__.py`: `new_player`, `edit_player`, `deactivate` — all committed ✅
- `admin/users.py`: `users_new`, `users_edit`, `users_reset_password`, `users_deactivate` — all committed ✅
- `auth/__init__.py`: `login` (last_login_at update) + `change_password` — both committed ✅
- `admin/bulk_import.py`: uses `with conn:` context manager — commits on success, rolls back on exception ✅
- `nt/__init__.py`: read-only ✅
- `auth/audit.py::log_audit`: has `conn.commit()` ✅

### Audit 2 — nt_staff role propagation

`nt_staff` was absent from every admin UI surface that lists roles. Fixed across 7 locations:

- `app/admin/users.py`: added `'nt_staff'` to `VALID_ROLES` tuple (was 4 roles, now 5)
- `app/admin/users.py`: added `ROLE_LABELS` dict with correct display strings (`'nt_staff': 'NT Staff'`); threaded `role_labels=ROLE_LABELS` into all 4 `render_template` calls for new.html and edit.html
- `app/__init__.py`: registered `ROLE_LABELS` as Jinja global so all templates can access it
- `app/templates/admin/users/new.html`: role dropdown uses `role_labels.get()` instead of raw `| title` filter
- `app/templates/admin/users/edit.html`: same
- `app/templates/admin/users/list.html`: added `'nt_staff': '#10B981'` to `role_color` dict
- `app/templates/auth/profile.html`: role display uses `ROLE_LABELS.get()` (was "Nt Staff", now "NT Staff")
- `app/templates/index.html`: same fix for signed-in-as label

### Audit 2b — role-gated UI conditionals

Root cause of the concrete bug (nt-test@bfa.bh: "New Evaluation" hidden on player profile): `scout_or_above` decorator excluded `nt_staff` so the backend 403'd; the templates mirrored the same exclusion. Fixed at both layers:

**Backend (root fix)**
- `app/auth/decorators.py`: `scout_or_above` now includes `'nt_staff'` — covers `evaluate`, `update_draft`, `submit_draft`, `delete_evaluation`, `restore` (evaluations blueprint), `new_player`, `edit_player`, `deactivate` (players blueprint)
- `app/wyscout/__init__.py`: `upload()` inline guard updated to include `'nt_staff'`

**Templates (13 locations)**
- `players/profile.html` ×6: New Evaluation header button, Passport PDF download, Wyscout upload (stats header + empty state), + New Evaluation in evaluations section, empty-state "Click New Evaluation" hint — all now include `'nt_staff'`
- `players/list.html`: "+ Add Player" button
- `players/_grid.html`: empty-state "Add the first player"
- `wyscout/imports.html` ×2: header "+ Upload Stats" + "Upload First File" empty state
- `index.html`: Wyscout Import quick-action card (was admin/TD only)

**Unchanged (correctly restricted)**
- `players/new.html:177`, `players/edit.html:184` — NT eligibility fieldset stays `admin | technical_director` only
- `evaluations/view.html` ×3 — Lock / Unlock / Admin-edit stays `admin | technical_director` only
- `evaluations/_history_card.html` — admin delete controls stay `admin | technical_director` only
- `wyscout/imports.html:41,70` — "Delete import" stays `admin` only

### E2E
- `migrations/_e2e_v1_0_2_audit.py`: expanded to 30+ assertions covering all three audit sub-sections (Audit 1, 2a display, 2b UI conditionals)

---

## v1.0.1 — Phase 8.1: Security hardening (2026-05-16)

Pre-launch hardening pass. No schema changes; no new user-facing features.

### Nginx rate limiting (Item 2)
- `nginx/conf.d/bfa-scout.conf`: `limit_req_zone login_zone` (10 req/min, 10MB)
- `/auth/login` gets a dedicated `location =` block with `limit_req burst=5 nodelay; limit_req_status 429`
- All other routes unchanged

### Password complexity (Item 3)
- `app/auth/validators.py` (NEW): `validate_password_strength()` — min 12 chars, upper + lower + digit, max 128
- Applied to all three password-setting flows: admin user-create, admin password-reset, user self-change-password
- HTML forms updated: `minlength="12"`, `maxlength="128"`, hint text added
- Existing stored hashes not affected; bootstrap_admin.py exempt

### Session timeout (Item 4)
- `PERMANENT_SESSION_LIFETIME = timedelta(hours=8)` — sliding window (each request resets countdown)
- `SESSION_COOKIE_HTTPONLY = True`, `SESSION_COOKIE_SAMESITE = 'Lax'`
- `SESSION_COOKIE_SECURE = True` in production, `False` in development
- `before_request` handler marks every session permanent + modified

### Ali's manual step (Item 1 — after deploy)
See DEPLOY.md §11: rotate admin password via UI, remove ADMIN_EMAIL/ADMIN_PASSWORD from `.env.production`.

### Tests
- `migrations/_e2e_phase_8_1.py` (NEW): 15 assertions covering validator, session config, nginx config structure, before_request registration, route wiring

---

## v1.0.0 — Phase 8: Production deployment infrastructure (2026-05-13)

**First production release.** Containerised deploy to DigitalOcean
behind Cloudflare, photos on Spaces, managed Postgres, nightly
off-site backups. After this commit the project enters maintenance
mode — new features become new phases.

This phase is multi-actor. **This commit is the Cowork-side share
only**: all in-repo production config + the photo-storage abstraction.
DO provisioning (Ali) and the on-droplet SSH deploy + 10 smoke tests
(Claude Code on the droplet) happen *after* this lands and are tracked
in DEPLOY.md, not here.

### Photo storage abstraction (the substantive code change)

`app/storage.py` (NEW) — pluggable backend, chosen at runtime by the
presence of `SPACES_BUCKET`:
- prod → DigitalOcean Spaces (boto3, `photos/<player_id>.jpg`,
  public-read, served via the Spaces CDN)
- dev → `app/static/photos/<player_id>.jpg` (unchanged legacy layout;
  zero migration for existing dev DBs)

Four ops: `put_player_photo`, `get_player_photo_url`,
`read_player_photo_bytes`, `delete_player_photo`.

**Why this is bigger than the spec's 2-function sketch** (documented
inline + here so the design intent survives):

1. **Pillow re-encode invariant preserved.** `app/players/photos.py`
   has a hard rule: *never store the raw upload — always Pillow
   centre-crop 400×400 + re-encode JPEG*. The spec's sketch uploaded
   the raw `file_obj`. Fixed: `save_player_photo()` keeps the entire
   Pillow pipeline and hands the processed JPEG **bytes** to
   `storage.put_player_photo()`. Prod never touches local disk for
   photos (hard rule) AND bytes are still guaranteed re-encoded.
2. **Passport PDF stays self-contained.** Phase 6 deliberately
   base64-embeds the photo (WeasyPrint's network fetcher is flaky).
   Spec's sketch had no read-bytes path. Added
   `storage.read_player_photo_bytes()` (Spaces `get_object` or local
   read) so `passport/__init__.py:_resolve_photo_data_uri` keeps
   embedding regardless of backend.
3. **Single read chokepoint.** `players/helpers.py:get_player_photo`
   (a Jinja global used by profile/list/grid/compare/eval-form +
   wyscout aggregations) now delegates to `storage`. One edit →
   every existing photo render works on Spaces transparently.
   Photo filenames stay keyed by `player_id` (NOT the spec's
   `national_id or player_id`, which would have silently broken ~6
   read sites).

`get_player_photo_url` deliberately does **no** per-render Spaces
`head_object` existence probe (that's an S3 round-trip per player card
per list page). It returns the CDN URL and relies on the templates'
existing `onerror→placeholder.svg` for photoless players. Documented
trade-off: one wasted image GET vs. an S3 HEAD on every render.

### Healthcheck

`app/healthz.py` (NEW) — `GET /healthz` → `200 {"status":"ok"}` (app
up + DB reachable) or `503 {"status":"error","detail":...}`. Uses
`_get_pool()` directly with explicit `putconn()` in `finally` (the
spec sketched `from app.db import get_connection`, which doesn't
exist; the real module exposes `get_db()` / `_get_pool()`). Registered
in `app/__init__.py`. Consumed by the Docker HEALTHCHECK, the compose
healthcheck, Cloudflare, and `deploy.sh`'s post-deploy gate.

### Admin bootstrap reconciliation

The codebase already had an idempotent `app/db.py:seed_initial_admin()`
reading `INITIAL_ADMIN_*`; the spec invented a parallel script using
`ADMIN_*`. Reconciled to ONE path: `seed_initial_admin()` now accepts
`ADMIN_EMAIL/PASSWORD` (preferred) **or** the legacy
`INITIAL_ADMIN_*`. `scripts/bootstrap_admin.py` (NEW) calls it and
verifies the post-condition (an admin row exists). Idempotent —
proven by running twice (both exit 0, no duplicate). Fixed an import
bug along the way: `python scripts/foo.py` puts `scripts/` on
sys.path, not the repo root, so the script prepends the repo root
explicitly (true in the container too).

### Infra files (NEW)

```
Dockerfile                       python:3.13-slim + WeasyPrint native
                                 deps (libpango/cairo/gdk-pixbuf) +
                                 Noto Latin/Arabic/emoji fonts + curl;
                                 non-root uid 1000; HEALTHCHECK; runs
                                 gunicorn -c gunicorn.conf.py
docker-compose.prod.yml          app + nginx; env_file: .env.production;
                                 nginx depends_on app service_healthy
gunicorn.conf.py                 2 workers × 4 gthreads, timeout 120
                                 (WeasyPrint headroom), preload, stdout
nginx/conf.d/bfa-scout.conf      :80→:443 redirect, TLS, 50M body cap,
                                 120s proxy timeout, /healthz no-log
nginx/certs/.gitkeep             dir ships; origin.{crt,key} gitignored
.env.production.example          all prod vars + placeholders + notes
.env.development.example         local-dev vars (Spaces unset → local FS)
scripts/deploy.sh                pull→build→up, fails loud if /healthz
                                 doesn't pass in 90s
scripts/bootstrap_admin.py       idempotent admin seed (see above)
scripts/backup_to_spaces.sh      nightly pg_dump→Spaces, 30-day prune
scripts/restore_from_spaces.sh   manual, typed-confirm, destructive
DEPLOY.md                        full 10-section runbook
```

`requirements.txt` += `boto3>=1.34` (single dependency source of
truth; the Dockerfile no longer pip-installs it separately).
`.gitignore` += `.env.production`, `.env.development`, `nginx/certs/*`
(hard rule: secrets + origin certs never committed; `.example`
templates ARE committed).

**Deliberate spec deviation**: no custom `nginx/Dockerfile`. Stock
`nginx:alpine` + bind-mounted config/certs is functionally identical
and simpler; documented in DEPLOY.md §1 and the compose file.

### Verified (Cowork-side, locally)

- App imports cleanly; `/healthz` live → `200 {"status":"ok"}`
- `storage.py` local-mode put/get/read/delete round-trip — bytes
  match, delete clears both URL and bytes
- `bootstrap_admin.py` — idempotent across two consecutive runs (exit
  0, no duplicate admin)
- **Full regression: 272/272 across all 9 prior E2E suites** (4.2 18,
  5d-1 39, 6.0 26, 6.1 57, 6.2 26, 6.2.1 23, 7 29, 7.1 8, 9 46) — the
  storage abstraction is transparent; the passport PDF (which now
  pulls photo bytes through `storage`) still passes 6.0/6.1/6.2/6.2.1
  unchanged.

### Blocked — NOT verifiable on this machine (no Docker installed)

- `docker build` of the Dockerfile — author-and-lint only here.
  Closes on Ali's Docker or first droplet build (DEPLOY.md §4.6).
- Spaces mode of `storage.py` — needs real DO credentials. Local-mode
  fully tested; Spaces code path is the same shape (boto3 put/get/
  delete) and exercised by smoke test #5 on the droplet.
- The 10 post-deploy smoke tests — require the live droplet
  (DEPLOY.md §4 "Post-deploy smoke tests").

These three are infra-actor items, not code defects; tracked in
DEPLOY.md so the droplet-side actor closes them.

## v0.9.0 — Phase 9: Bulk player import + Phase 7.1 widening (2026-05-12)

One combined commit. Phase 9 adds the admin-only bulk-import workflow
mandated by BFA board feedback for faster player onboarding. Phase 7.1
flips two of the four design calls documented in v0.7.0: TD now gets
`/nt` access, and the NT visibility filter now hides NT evaluations
from viewer role as well as scout. Landing them together preserves
bisect clarity — both are policy-shift changes that pair naturally.

### Phase 7.1 — widening (5 lines of code)

| Change | Before (v0.7.0) | After (v0.7.1 + v0.9.0) |
|---|---|---|
| `admin_or_nt_staff_required` | admin + nt_staff | admin + technical_director + nt_staff |
| `_nt_visibility_clause` filter set | `'scout'` only | `('scout', 'viewer')` |
| `nt_readiness_summary` inline filter | same | same |
| `get_evaluation_count_active` inline filter | same | same |
| `get_player_bio_counts` inline filter | same | same |
| `base.html` desktop /nt nav-link condition | admin + nt_staff | admin + TD + nt_staff |
| `base.html` mobile /nt nav-link condition | admin + nt_staff | admin + TD + nt_staff |

The four `_nt_visibility_clause` and inline `requesting_user_role`
sites moved as a set — half-applied widening would have left viewer
filtered on some helpers but not others, a silent partial info leak.

**Phase 7.1 verification** ([migrations/_e2e_phase_7_1.py](migrations/_e2e_phase_7_1.py)) — 8/8 PASS:
- TD GET `/nt` returns 200 (was 403 in 7.0)
- TD dashboard renders the `/nt` nav-link href
- Viewer's player profile no longer renders NT-tagged evaluations
- Viewer's `get_evaluation_count_active(2)` returns N-1 where admin sees N
- Admin still sees everything (regression: only frontline roles get filtered)

### Phase 9 — bulk player import

New admin-only workflow at `/admin/players/bulk-import` for onboarding
many players from a single CSV/Excel file. 3-step UX: upload → preview
(per-row classification, admin overrides per duplicate) → commit
(atomic transactional INSERT/UPDATE). No schema changes — `national_id`
UNIQUE column already exists and drives the primary duplicate-detection
path.

**Architecture**

- `app/admin/bulk_import_helpers.py` — pure functions: `parse_file()`
  (pandas-backed CSV+xlsx parser; normalises empty/`N/A`/`nan` cells to
  None), `validate_row()` (per-field validation with errors+warnings),
  `find_duplicate()` (national_id-first, then name+DOB+position fuzzy),
  `classify_rows()` (one pass that produces (parsed_rows, summary)),
  `build_db_params()` (resolves position FK + clubs.name → club_id).
- `app/admin/bulk_import_session.py` — in-memory parked-import store
  keyed by `secrets.token_urlsafe(16)`. The token lives in the Flask
  session cookie; the rows (up to 500) live in a module-level dict.
  30-minute TTL, lazy GC. Persistence intentionally absent for v1 —
  Flask restart wipes pending imports; admin re-uploads.
- `app/admin/bulk_import.py` — 7 routes on the existing admin
  blueprint: index, upload (POST), preview, commit (POST), result,
  discard, template.csv, template.xlsx.

**Locked decisions honoured**

| Decision | Implementation |
|---|---|
| File formats | CSV + xlsx via pandas (`dtype=str`); rejected anything else |
| Required field | `full_name` only; every other column optional |
| Empty / "N/A" / "nan" | All normalise to NULL at parse time (NULL_SENTINELS list) |
| Duplicate detection | national_id UNIQUE first; else (name+DOB+position_code) fuzzy match on active players |
| Duplicate action | Per-row select on preview: 'skip' (default) or 'update' |
| Photo handling | Not in scope — admin UI handles per-player |
| Permission | `admin_required` on every route |
| Audit log | 1 row per imported player (`player.bulk_imported`) + 1 summary row (`admin.bulk_import_completed`) — both inside the same transaction as the data write |
| Max rows | 500 per import; rejected at parse with clear error |
| Templates | CSV + Excel both downloadable, both include 2 example rows |

**Schema mapping (1.5 catch)** — the spec's `dominant_foot` field name
doesn't match the actual DB column `players.foot`. Validation accepts
`dominant_foot` from the CSV but `build_db_params` writes to `foot`.
Same with position codes — spec example used "CB, AM" but the actual
positions table has `AMF`, `DMF` etc; validation uses the live
`positions.code` set so it stays accurate.

**Validation rules** (any of these adds an error → row marked INVALID):
- `full_name` missing
- `dob` unparseable or in the future
- `national_id` shorter than 5 chars
- `primary_position_code` not in `positions.code` (case-insens)
- `nationality_code` not in NATIONALITY_LABEL (ISO alpha-3)
- `nationality_status` not in the documented enum
- `eligible_from_date` / `bahrain_residency_start_date` unparseable
- `dominant_foot` not in (right, left, both)
- `height_cm` / `weight_kg` not a number (out of range = warning only)

**Warnings** (cosmetic; don't block import):
- `dob` < 1950
- `nationality_status='foreign_residency'` without `bahrain_residency_start_date`
- `current_club_name` doesn't match a `clubs.name` (stored as free-text in `players.current_club`)
- `height_cm` / `weight_kg` outside reasonable range

**Bugs caught + fixed during build**

1. **pandas 3.x StringDtype + .map() skips NaN cells** — `dtype=str, keep_default_na=False` doesn't fully suppress NaN inference; `DataFrame.map(_norm)` doesn't pass NaN to the function in pandas 3.x (different from pandas 2.x `applymap`). Fixed by normalising at the dict layer after `to_dict('records')` instead of at the DataFrame layer.
2. **`'float' object has no attribute 'strip'`** in `validate_row` — defensive `_str()` coerce added; fields dict re-normalised at the top of the function so subsequent `.strip()` / `.lower()` calls never see a float.
3. **`cursor already closed`** during INSERT — `cur.fetchone()` was AFTER the `with conn.cursor() as cur:` block. Moved it inside.
4. **Multiple inline `requesting_user_role == 'scout'` sites** — 4 sites in `helpers.py` needed widening for the 7.1 viewer-filter. All updated together; a grep confirms 0 of the old narrow form remain.

**E2E suite — `migrations/_e2e_phase_9.py` — 46/46 PASS**

Real Flask + real HTTP (NOT flask.test_client). Multipart-aware
HTTP helper. Coverage:

- Case 1-2: 5-row CSV + 5-row xlsx, both preview→commit→DB
- Case 3: row missing `full_name` → INVALID
- Case 4-7: duplicate detection (national_id + fuzzy), commit with
  skip/update per row
- Case 8-9: invalid nationality_code / position_code → INVALID
- Case 10: empty cells AND "N/A" string → NULL in DB
- Case 11: audit log has per-player + summary rows
- Case 12-13: scout 403, anon 401
- Case 14: 501-row file rejected at parse
- Case 15: discard clears parked session
- Bonus: template downloads (CSV + xlsx) return correct content-types
  and contain the expected column headers

All test fixtures (users + players + evaluations) snapshot+restored
in `finally:` — DB left as it was.

### Files

```
migrations/
  _e2e_phase_9.py                NEW  46-check E2E
  _e2e_phase_7_1.py              NEW  8-check 7.1 widening verifier

app/admin/
  __init__.py                    MOD  import bulk_import (registers routes)
  bulk_import.py                 NEW  7 routes on the admin blueprint
  bulk_import_helpers.py         NEW  parsing, validation, dedup, DB params
  bulk_import_session.py         NEW  in-memory parked-import store

app/auth/decorators.py           MOD  admin_or_nt_staff_required widened to include TD
app/evaluations/helpers.py       MOD  _nt_visibility_clause + 3 inline sites widened to ('scout','viewer')

app/templates/admin/
  bulk_import_upload.html        NEW
  bulk_import_preview.html       NEW
  bulk_import_result.html        NEW
app/templates/base.html          MOD  /nt nav-link condition widened (desktop + mobile)
app/templates/players/list.html  MOD  +Bulk import button next to +Add Player (admin only)
app/static/css/style.css         MOD  +bulk-preview-table row colours, badges

CHANGELOG.md                     MOD  this entry
PROJECT.md                       MOD  Phase 9 ✓, Phase 7.1 ✓, queue Phase 8 deploy
```

No schema changes. No Python deps added.

### Verified

- **Phase 9 E2E: 46/46 PASS**
- **Phase 7.1 verifier: 8/8 PASS**
- **Regression: 218/218** across the 7 prior suites (4.2, 5d-1, 6.0,
  6.1, 6.2, 6.2.1, 7) — threading the wider viewer-filter and adding
  the bulk-import routes didn't disturb any existing assertion.
- **Total: 272 checks across 9 suites, 0 failures.**

### Out of scope / queued

- Photo upload in bulk import — single-add UI handles this
- ZIP-of-CSVs / multi-file upload — single file per session
- Background job processing — synchronous (500 rows fits in ~3s)
- Bulk EDIT (only bulk CREATE + update-on-duplicate)
- Import history page — `audit_log` captures it
- Field-level diff display on update
- DB-backed parked-import store — in-memory acceptable for v1
- Phase 8 (auth polish + production deploy) is the final queued phase

## v0.7.0 — Phase 7: NT staff role + /nt workspace + visibility invariant (2026-05-12)

BFA board feedback from May 12 mandated three things: a dedicated
National Team account with admin-like access, scout-side privacy
(scouts cannot see what NT staff have evaluated), and a dedicated
NT workspace. v0.7.0 lands all three. Major version bump — first
schema change since Phase 6, first new role, and a new codebase-wide
visibility invariant.

### Schema

- `evaluations.created_by_role VARCHAR(32) NOT NULL DEFAULT 'scout'`
  — every existing evaluation backfilled to `'scout'` (the only
  frontline role at the time). 7 rows touched (6 active + 1
  soft-deleted). Indexed via `idx_evaluations_created_by_role`.
- `users_role_check` constraint **widened additively** to
  `(admin, technical_director, scout, viewer, nt_staff)`. The
  spec proposed replacing the set with
  `(admin, scout, coach, management, nt_staff)`, which would have
  silently dropped TD and viewer and broken four existing role-
  decorators. The (1.5) pre-flight catch flipped this to additive.
- `schema.sql` updated declaratively — no ALTER statements.

### NT VISIBILITY INVARIANT (new, sibling to soft-delete from 5c-3)

**Every evaluation read helper accepts `requesting_user_role`.**
When `'scout'`, the SQL appends `AND created_by_role != 'nt_staff'`,
hiding NT-staff evals from scouts. Any other value (None, admin,
nt_staff, viewer, TD) applies no filter.

Helpers threaded (6):
`get_evaluation`, `get_player_evaluations`, `nt_readiness_summary`,
`get_evaluation_count_active`, `get_player_bio_counts`,
`get_player_evaluation_aggregate`.

Routes/templates threaded:
- `players.player_profile`, `players.compare_view`,
  `players.compare_scout_section`, `evaluations.view`,
  `evaluations.update_draft`, `passport.player_passport`
- `players/profile.html`, `evaluations/_eligibility_card.html`

### Evaluation create — role stamping

`get_or_create_draft(..., creator_role='scout')` accepts the
role; both callers (`evaluations.evaluate` and
`evaluations._handle_form_post`) pass `current_user.role`. NT
staff authoring an evaluation through the standard form gets a
row tagged `created_by_role='nt_staff'`, hidden from scouts.

### Auth decorators

- `any_authenticated` widened to include `nt_staff`.
- New: `nt_staff_required` (NT only).
- New: `admin_or_nt_staff_required` — gates `/nt`. TD deliberately
  NOT included; flagged as a design call below.

### /nt workspace

- `GET /nt/` (admin + nt_staff) — table of BPL-eligible players:
  `nationality_status IN ('bahraini','foreign_ancestry')` OR
  explicit `eligible_from_date <= CURRENT_DATE` OR
  `foreign_residency` + residency-start + 5y already passed.
- Per-player NT-eval count column via `get_nt_evaluation_count`
  (registered as a Jinja global).
- Nav link (desktop + mobile) in `base.html` — admin + nt_staff
  only; uses BFA gold (`var(--accent)`) to stand out.
- Right-of-nav `nt_staff` user role badge in emerald `#10B981`.

### Role badge macro

`app/templates/_macros/evaluation_role_badge.html` — emits `NT` /
`Admin` badges next to evaluator names. Scout gets no badge
(default state keeps the UI quiet for the common case). Applied
in: history card, compare scout-section, passport
(latest-eval panel + recent-evaluations table). CSS in both
`style.css` (live) and `_passport.css` (print).

### Design calls made during build (documented; reversible)

1. **Constraint widened additively** — preserves TD and viewer.
2. **`/nt` access = admin + nt_staff only** — TD does NOT get the
   workspace by default. Widen `admin_or_nt_staff_required` to
   change.
3. **Visibility filter applies to `scout` role only** — viewer
   sees NT evals today. Edit `_nt_visibility_clause` to change.
4. **"Coach GETs /nt → 403"** in the spec — no coach role
   exists; E2E substitutes viewer.

### Files

```
migrations/
  _generate_phase_7.py           NEW
  phase_7_nt_role.sql            NEW
  _dryrun_7.py                   NEW
  _apply_7.py                    NEW
  _verify_throwaway_7.py         NEW
  _e2e_phase_7.py                NEW
schema.sql                       MOD
app/auth/decorators.py           MOD
app/evaluations/helpers.py       MOD
app/evaluations/__init__.py      MOD
app/players/__init__.py          MOD
app/passport/data.py             MOD
app/passport/__init__.py         MOD
app/templates/players/profile.html               MOD
app/templates/evaluations/_eligibility_card.html  MOD
app/templates/evaluations/_history_card.html      MOD
app/templates/players/_compare_scout_section.html MOD
app/templates/passport/passport.html              MOD
app/templates/passport/_passport.css              MOD
app/static/css/style.css                          MOD
app/templates/base.html                           MOD
app/__init__.py                  MOD
app/nt/__init__.py               NEW
app/nt/helpers.py                NEW
app/templates/nt/index.html      NEW
app/templates/nt/_squad_table.html               NEW
app/templates/_macros/evaluation_role_badge.html NEW
```

No Python dep changes.

### Verified

- **Phase 7 E2E: 29/29 PASS** — 5 permission, 7 visibility, 4
  aggregate-helper, 2 squad-list, 3 create-path, 3 nav-link,
  2 pre-flight schema. Test fixtures (3 throwaway users + 4
  evals) snapshot+restored in `finally:`.
- **Regression: 218/218 across 7 suites** — 4.2 (18), 5d-1 (39),
  6.0 (26), 6.1 (57), 6.2 (26), 6.2.1 (23), 7 (29). Threading
  `requesting_user_role=None` defaults preserved all existing
  behaviour.
- **Schema convergence** — throwaway-namespace verify confirms
  fresh `flask init-db` reproduces the column + index + widened
  constraint; INSERT(nt_staff) succeeds; INSERT(bogus) rejected.
- **Visual** — `/nt` squad table shows Arthur (residency
  complete) + Bader (Bahraini citizen). Bouhra (residency
  completes 2027) correctly excluded.

### Out of scope / queued

- Per-scout configurable visibility (out of scope)
- Bulk player import (Phase 9)
- Production deploy (Phase 8)
- Arabic translations for "National Team" / "NT"

## v0.6.2.3 — Phase 6.2.3: Eligibility + nationality flag display audit (2026-05-12)

Standing rule enforced for the first time: **before any user-facing field rendering
feature merges, audit ALL surfaces that display that field**. Phase 6.2.2's Bahrain
flag fix was scoped only to the eligibility card; this phase propagates it everywhere.

### Grep audit performed before any code change

Searched `app/**/*.{py,html}` for `nationality_status`, `nationality_code`,
`eligibility`, `is_eligible_now`, `flag_emoji`, `get_flag_svg`. Classified every hit:

| Surface | Prior state | Action |
|---|---|---|
| Home dashboard `index.html` | Navigation cards only, no player list | KEEP |
| Players list `list.html` | HTMX calls `_grid.html` | KEEP (inherits grid) |
| **Player card grid `_grid.html`** | `flag_emoji()` (unicode text) + plain icon+label, no color badge | **FIX** |
| **Player profile header `profile.html`** | `flag_emoji()` in bio grid | **FIX** |
| Eligibility card `_eligibility_card.html` | 6.2.2 complete | KEEP |
| **Compare view bio `compare_view.html`** | `p.nationality` text only, no flag, no badge | **FIX** |
| **Compare search `_compare_search.html`** | Name+pos+club, no flag | **ADD** |
| **Evaluation form `form.html`** | Name+pos+age, no flag | **ADD** |
| Player edit/new forms | Form inputs for nationality fields | KEEP |
| Evaluation view | Evaluation's own `eligibility_status` | KEEP |
| Passport PDF | 6.2.2 complete | KEEP |
| Backend `.py` files | Data layer, not user-facing | KEEP |

### Changes

#### New: Reusable `eligibility_badge` Jinja macro
`app/templates/_macros/eligibility_badge.html` — single source of truth for inline
eligibility display. Renders: player's nationality flag (SVG) + colored status badge.
Badge color driven by new `status_code` field in `compute_eligibility_status()`.

```jinja2
{% from '_macros/eligibility_badge.html' import eligibility_badge %}
{{ eligibility_badge(player) }}
{{ eligibility_badge(player, show_flag=False, size='md') }}
```

#### New: `status_code` field in `compute_eligibility_status()` / `_build_passport_eligibility()`
All return dicts gain `status_code: str` (one of `eligible_now`, `eligible_future`,
`not_eligible`, `unknown`). Drives CSS `data-status` attribute on `.elig-badge` elements.

| Branch | status_code |
|---|---|
| `not_eligible` | `not_eligible` |
| `bahraini` / `foreign_ancestry` | `eligible_now` |
| explicit date ≤ today | `eligible_now` |
| explicit date > today | `eligible_future` |
| residency-derived ≤ today | `eligible_now` |
| residency-derived > today | `eligible_future` |
| pending / foreign_other / unknown | `unknown` |

#### New CSS: `.elig-badge` family (`app/static/css/style.css`)
Dark-theme–aware badge classes. Color via `data-status` attribute (no JS needed).
`.elig-flag` inside badge sized 14×10px for inline SVG flag.

#### Data layer: eligibility fields propagated to two previously-missing backends
- `app/wyscout/aggregations.py:compare_players()` — added `nationality_code`,
  `nationality_status`, `eligible_from_date`, `bahrain_residency_start_date` to SELECT
  and player dict. Templates can now call `eligibility_badge(p)` for compare players.
- `app/evaluations/__init__.py:_load_player()` — added `nationality_code` to SELECT
  so the evaluation form header can show the player's flag.
- `app/players/__init__.py:compare_search()` — added `nationality_code` to SELECT
  so the compare picker search dropdown can show flags.

#### Template changes
- `players/_grid.html` — macro replaces `flag_emoji` + plain eligibility text.
  `flag_emoji()` removed entirely from this surface.
- `players/profile.html` — `flag_emoji()` replaced with `get_flag_svg()` inline SVG
  in the bio grid's Nationality row.
- `players/compare_view.html` — macro added below each player's club/age line in bio header.
- `players/_compare_search.html` — inline SVG flag added before player name.
- `evaluations/form.html` — inline SVG flag added before player name in header strip.

### Files

```
app/players/eligibility.py                     MOD  — status_code added to all branches
app/templates/_macros/eligibility_badge.html   NEW  — reusable eligibility badge macro
app/static/css/style.css                       MOD  — .elig-badge family added
app/wyscout/aggregations.py                    MOD  — compare_players() gains nationality/eligibility fields
app/evaluations/__init__.py                    MOD  — _load_player() gains nationality_code
app/players/__init__.py                        MOD  — compare_search() gains nationality_code
app/templates/players/_grid.html               MOD  — macro replaces flag_emoji + eligibility text
app/templates/players/profile.html             MOD  — flag_emoji → get_flag_svg inline SVG
app/templates/players/compare_view.html        MOD  — macro in bio header
app/templates/players/_compare_search.html     MOD  — inline flag in search results
app/templates/evaluations/form.html            MOD  — inline flag in header strip
migrations/_e2e_phase_6_2_3.py                NEW  — E2E: badge+flag on 5 surfaces, 3 player states
```

---

## v0.6.2.2 — Phase 6.2.2: BFA board polish (2026-05-12)

Three items from the BFA board meeting post-6.2 review.

### Item 1 — Age at eligibility

For `foreign_residency` players with a **future** eligibility date and
a known DOB, the eligibility card on the player profile and the passport
PDF now show:

> Age at eligibility: **N**

This lets the committee see at a glance how old a player will be when
first available, without opening the full bio.

**Logic:** `age_at_eligibility(player)` in `app/players/eligibility.py`.
Returns `None` (and the line is suppressed) for: already-eligible players,
players with no DOB, and non-`foreign_residency` routes. Uses the same
`_resolve_eligibility_date()` helper that powers the status label — single
source of truth for the eligibility date (explicit `eligible_from_date`
first; then `bahrain_residency_start_date + 5y`).

### Item 2 — Bahrain flag for immediately-eligible players

Players who are eligible **right now** (Bahraini citizen, foreign ancestry,
or residency complete) now show an inline Bahrain flag next to their ✅
status label on the profile page eligibility card.

**Implementation:** `compute_eligibility_status()` and
`_build_passport_eligibility()` both now return `is_eligible_now: bool`
in their dict. The `_eligibility_card.html` template uses the existing
`get_flag_svg('BHR')` Jinja global (registered in `app/__init__.py`)
to render the inline SVG flag from `app/static/flags/bh.svg`.

### Item 3 — Wyscout accumulation audit (code-review + diagnostic)

Confirmed by both code review and new diagnostic script that re-uploading
a Wyscout xlsx is correctly idempotent (UPSERT, no duplicates):

- `schema.sql`: `UNIQUE (player_id, match_label, match_date)` ✅
- `ingest.py`: `ON CONFLICT (player_id, match_label, match_date) DO UPDATE` ✅
- `xmax = 0` trick for insert-vs-update counting ✅

No code changes needed. New `migrations/_e2e_phase_6_2_2.py` script
runs three diagnostic queries: duplicate check (Q1), constraint presence
(Q2), row count baseline (Q3).

### Files

```
app/players/eligibility.py                   MOD  — added _resolve_eligibility_date(), age_at_eligibility(); all compute_eligibility_status() branches gain is_eligible_now + age_at_eligibility keys
app/passport/data.py                         MOD  — _build_passport_eligibility() gains is_eligible_now + age_at_eligibility; imports age_at_eligibility from eligibility
app/templates/evaluations/_eligibility_card.html  MOD  — Bahrain flag for is_eligible_now; age_at_eligibility line
app/templates/passport/passport.html         MOD  — age_at_eligibility line after elig-note
app/templates/passport/_passport.css         MOD  — .elig-age rule added
app/__init__.py                              MOD  — get_flag_svg Jinja global registered (wraps _flag_svg_inline from passport.data)
migrations/_e2e_phase_6_2_2.py               NEW  — 4-check Wyscout idempotency diagnostic (Q1 duplicates, Q2 constraint, Q3 row count)
```

---

## v0.6.2.1 — Phase 6.2.1: Admin notes hidden from user-facing surfaces (2026-05-11)

Browser spot-check after 6.2 surfaced sentinel test data
(`E2E-SENTINEL-…-DO-NOT-PUBLISH-elig` / `…-resid`) rendering as
**"Eligibility notes (admin):"** and **"Residency notes (admin):"** in
Arthur's passport. The data layer was correct — those strings came
from real `players.eligibility_notes_admin` /
`players.bahrain_residency_notes` values written by a prior E2E run
that didn't get to its `finally:` restore.

The real lesson: **admin notes are admin scratchpad. They don't
belong in any user-facing artefact, formal documents in particular.**

### Contract change

| Surface | 6.0 contract | 6.2.1 contract |
|---|---|---|
| Passport PDF — full mode | renders admin notes | **does NOT render** |
| Passport PDF — public mode | scrubbed | **does NOT render** |
| Player profile page | (didn't render) | (still doesn't render) |
| Eligibility card include | (didn't render) | (still doesn't render) |
| `/players/<id>/edit` admin form | renders form fields | **renders form fields** (kept — admin authors them here) |
| `/players/new` admin form | renders form fields | **renders form fields** (kept) |
| DB columns | preserved | **preserved** |
| DB data | preserved | **preserved** (sentinel test data NOT scrubbed per Ali's call) |

### Grep audit performed before edits

Searched `app/**/*.{py,html}` for `eligibility_notes_admin` and
`bahrain_residency_notes`. Classified every hit:

- Backend Python (`app/players/__init__.py`, `app/passport/data.py`) —
  KEEP (form handling, SQL plumbing)
- Admin forms (`templates/players/edit.html`, `templates/players/new.html`)
  — KEEP (where admin authors them)
- **`templates/passport/passport.html`** — the only user-facing surface
  rendering these fields. REMOVED the two `{% if %}` rendering blocks.
- `templates/players/profile.html`, `templates/evaluations/_eligibility_card.html`,
  `templates/evaluations/_history_card.html` — confirmed they don't
  reference these fields (no edit needed).

### Files

```
app/templates/passport/passport.html    MOD  — removed the two `{% if player.<admin_note> %}` blocks + corresponding top-of-file docstring update
app/templates/passport/_passport.css    MOD  — removed `.elig-admin-note` rule (was only used by the deleted blocks)
migrations/_e2e_phase_6.py              MOD  — Case 3 contract flipped: admin notes now hidden in BOTH modes, not just public
migrations/_e2e_phase_6_2_1.py          NEW  — 23-check E2E (inject sentinels → assert non-render in full PDF + public PDF + profile HTML → assert presence in admin edit form → restore DB)
```

The passport data layer's public-mode scrub in
`app/passport/data.py:_build_passport_eligibility` is now redundant
(the fields aren't rendered at all) but kept as belt-and-braces.

### Verified end-to-end

- **6.2.1 E2E: 23/23 PASS** ([migrations/_e2e_phase_6_2_1.py](migrations/_e2e_phase_6_2_1.py))
  - Sentinels (`S621-ELIG-<pid>-DO-NOT-PUBLISH`, `S621-RESID-…`)
    injected into Arthur's DB columns, then:
  - Full PDF text does NOT contain either sentinel
  - Full PDF text does NOT contain the `Eligibility notes (admin)` or
    `Residency notes (admin)` labels
  - Public PDF: same assertions hold (already redacted before 6.2.1;
    now hidden at the template layer too)
  - Profile page HTML: does NOT contain sentinels (regression guard —
    the profile already didn't render these, but the assertion makes
    that explicit)
  - Admin edit page HTML: DOES contain both sentinels (proves DB
    plumbing intact — form fields prefilled with the values)
  - Template literal check: `passport.html` has no
    `{% if player.eligibility_notes_admin %}`, no
    `{{ player.eligibility_notes_admin }}`, etc.
  - DB values restored to prior state in `finally:`
- **6.0 regression: 26/26 PASS** after Case 3 contract update
  (admin notes now hidden in BOTH modes, not just public)
- **6.1 regression: 57/57 PASS**
- **6.2 regression: 26/26 PASS**

132 checks across all four suites. Visual spot-check confirmed: a
PDF generated with sentinels actively present in the DB shows only
the eligibility status line + residency-since line. No admin notes,
no orphan whitespace, eligibility section flows cleanly into the
Wyscout section below.

### Out of scope (unchanged)

- DB columns and existing values: untouched.
- Admin edit form (`players/edit.html`, `players/new.html`): unchanged.
- `app/passport/data.py` public-mode scrub: kept (redundant but harmless).
- Passport mode split (full vs public): unchanged.

## v0.6.2 — Phase 6.2: PDF page-1 layout fix + passport button reposition (2026-05-11)

Three items on top of 6.1 — two PDF-layout regressions surfaced on
browser spot-check, plus a profile-page UX nit:

1. A faint **"decorative wave / scribbled red line"** between sections
   on page 1 (above "National-Team Eligibility" most visibly). At
   high-DPI rasterization the lines render as perfectly straight
   solid 1pt rules — but Edge/Chrome's built-in PDF viewers
   anti-alias 1pt rules at non-integer pixel positions into
   wavy/dithered gradients. Ali was seeing real subpixel render
   noise, not a stray asset.
2. **Radar banished to page 2 alone.** The 6.1 "remove explicit page-
   break, let WeasyPrint paginate" change was too conservative — page
   1 ended mid-content (bio + eligibility + stats) and page 2
   contained just the radar + scout assessment. Unprofessional white
   space at the foot of page 1.
3. **Passport download buttons buried at the bottom of the profile
   page.** Committee reviewers had to scroll past the entire Wyscout
   dashboard + scout-evaluation history just to find the printable
   artefact. Moved the block to sit directly below the header strip
   and directly above the eligibility card.

### Fixes

**Item 1 — h3 underline removed.**
- Stripped `border-bottom: 1pt solid #B5924C` and `padding-bottom`
  from the global `h3` rule. The BFA-red bold heading (now bumped
  one notch to 11.5pt / 700) is plenty of visual separation on its
  own.
- Kept the `.passport-header` 2pt red rule — 2pt is robust against
  the subpixel-rasterization noise that bit the 1pt rules.
- No `<hr>` was ever present; no `wavy` text-decoration anywhere;
  pre-flight grep confirmed both before any edit. The fix is
  defensive: thin solid rules are inherently fragile in PDF
  viewers, so dropping them altogether is the durable answer.

**Item 2 — side-by-side stats + radar.**
- `.wyscout-grid` flipped from `display: block` (6.1) back to
  `display: flex` with a 55% / 45% split. Stats table on the left,
  radar on the right. Heading + season subtitle stay outside the
  flex container so they span the full row width above both columns.
- `page-break-inside: avoid` on `.wyscout-grid` so the layout never
  splits across pages.
- Radar SVG geometry re-tightened: viewBox `360 → 320`, margin
  `22% → 18%`. The narrower viewBox fits the 45% column while
  keeping label headroom (incl. "Work Rate" — the longest axis
  label). CSS now sizes the SVG to `width: 100%; height: auto;`
  (was a hardcoded `height: 220pt` in 6.1) so it scales to whatever
  the column width is.

### Page-budget contract for page 1

After these changes, page 1 contains (top→bottom):
```
Header (BFA brand · Player Passport · 2pt red rule)
Bio strip (photo · name · DOB · position · club · nationality+flag)
National-Team Eligibility (icon · label · residency-since)
Wyscout Career Statistics (h3) + season subtitle
[ Stats table  55% | Radar SVG 45% ]
```
Page 2 = scout assessment only (latest panel + history table + footer).
**Exactly 2 pages**, no overflow, no banished elements.

### Item 3 — passport button moved below header

The passport download block (Player Passport h2 + full-mode and
public-redacted buttons) was last in `app/templates/players/profile.html`
in 6.0–6.1, below the scout-history panel. Cut and re-inserted between
the header strip's closing `</div>` and the eligibility card include.
Now sits directly below the player header strip and directly above
the eligibility card. The block's `id="player-passport"` is preserved
(so any existing deep-link / anchor still resolves). Move, not duplicate
— grep confirms exactly one `id="player-passport"` and exactly two
`/passport.pdf` anchors in the rendered HTML. Loading state +
pointer-events:none CSS travelled with the block; behaviour
unchanged.

DOM-order verification of the rendered profile page (`/players/2`):
```
Header strip image (player photo)         @ 5419
Player Passport h2                        @ 8879
Download Passport button                  @ 9478
Public PDF button                         @ 9923
National-Team Eligibility h2              @ 10324
Wyscout Dashboard                         @ 11368
```

### Files

```
app/templates/passport/_passport.css   MOD — h3 rule sans border, wyscout-grid flex 55/45 with page-break-inside avoid
app/passport/radar_svg.py              MOD — viewBox 360→320, margin 22%→18% (default size param updated)
app/templates/players/profile.html     MOD — passport block moved from end-of-page to between header strip and eligibility card
migrations/_e2e_phase_6_1.py           MOD — best-effort artefact writes (locked-file resilience)
migrations/_e2e_phase_6_2.py           NEW — 26-check E2E for the layout deltas
```

The passport HTML template was unchanged — its structure already had
the h3 + stats-subtitle outside `.wyscout-grid`. The fix landed
entirely in CSS + the SVG generator's geometry constants.

### Verified

- **6.2 E2E: 26/26 PASS** ([migrations/_e2e_phase_6_2.py](migrations/_e2e_phase_6_2.py))
  - Arthur PDF exactly 2 pages
  - All 6 radar axis labels present on page 1
  - 0 radar axes leak to page 2
  - h3 rule has no `border-bottom:` or `border:` property
    (CSS comments stripped before matching, so the explanatory
    backtick-quoted `border-bottom:` doesn't trick the assertion)
  - No `text-decoration: wavy` rule anywhere; no `<hr>` element
  - `.passport-header` still has its robust 2pt red rule (regression
    guard — we didn't strip the page-header's landmark, just the
    fragile h3 ones)
  - `.wyscout-grid` uses `display: flex` with `page-break-inside:
    avoid`; stats column is `flex: 0 0 55%`, radar is `0 0 45%`
  - h3 and stats-subtitle appear before `.wyscout-grid` in the
    template DOM order (so they span the full width above both
    columns)
  - Bouhra and the public-mode PDF also exactly 2 pages with all 6
    radar axes on page 1
- **6.1 regression E2E: 57/57 PASS** (after a small E2E hardening:
  the end-of-run artefact dumps are now best-effort, so a locked
  file in `D:\tmp\` from a prior session doesn't fail the whole run)
- **6.0 regression E2E: 26/26 PASS**
- **Visual spot-check** (pypdfium2 rasterize at 2x):
  - Arthur full (63KB, 2pp): clean page 1 with side-by-side stats +
    radar, all 6 axes readable, scout-section on page 2
  - Arthur public (63KB, 2pp): same layout + `PUBLIC` badge,
    redactions intact (`Scout 1`, "BFA Scouting Department")
  - Bouhra full (57KB, 2pp): same layout; eligibility wording from
    6.1 still verbatim — "⏳ Eligible from 2027-08-15 (in 1 year,
    3 months) / Bahrain residency since 2022-08-15"

### Out of scope (carried forward)

- Eligibility status icons (✅/⏳/❌/?) still render as monochrome
  outline glyphs in some viewers — same emoji-font fragility as the
  flags before 6.1; could be swapped to inline SVG using the same
  pattern when committee reviewers flag it.
- PDF caching (deferred).
- `season_label_for_date` (4.1 helper, unused, slash format) — flag
  for rename-or-delete when Phase 4.2.1 lands.

## v0.6.1 — Phase 6.1: PDF polish (2026-05-11)

Five-item patch on top of the v0.6.0 Player Passport landing. Browser
spot-check by Ali surfaced clipped radar labels, FIFA-jargon wording in
the eligibility card, unreliable emoji flags, missing season context on
the Wyscout heading, and "did my click register?" ambiguity on slow
PDF generations. All five addressed; PDF stays at the spec's two-page
maximum.

### Item 1 — radar layout & geometry

Two compounding causes for the clipped axis labels:
- **CSS**: the previous `.wyscout-grid` flex layout put the stats table
  on the left and the radar on the right; the radar's flex column
  was narrow, so the SVG scaled down — labels at θ=±60° crossed the
  column edge and were clipped by container `overflow`.
- **SVG**: the viewBox was 280×280 user-units with internal margin 12%
  (33 units). "Passing" at axis 2 (θ=−π/6) had its label anchor at
  x≈245 with the text extending right to x≈295 — past the right edge
  of the 280-unit viewBox.

Fix: switched `.wyscout-grid` from flex to block (stats top, radar
below); expanded SVG viewBox to 360×360 with 22% margin; tightened the
page-1 vertical rhythm so the radar still fits without overflow
(h3 margin 14→10pt; bio photo 100→84pt; bio margins trimmed; stats-
table row padding 3→1.5pt; radar height 320→220pt). Removed the
explicit `<div class="page-break">` — relied on natural pagination
plus `page-break-inside: avoid` on `.scout-section` and `.latest-eval`.
End result: page 1 = bio + eligibility + stats table; page 2 = radar
+ scout assessment + footer. Verified all 6 axis labels readable
("Scoring 39", "Passing 57", "Dribbling 23", "Defending 48", "Aerial 16",
"Work Rate 79").

### Item 2 — eligibility wording

`compute_eligibility_status` in `app/players/eligibility.py` (the
live profile UI's source of truth) returns "Eligible in 1y 3m /
Suggested 2027-08-15 (Article 5; admin to confirm)" — too casual for
the PDF's formal context and exposes regulation jargon to committee
readers.

New `_build_passport_eligibility(player)` in `app/passport/data.py`
mirrors the 6-priority branch order but with reformatted wording:
"Eligible from 2027-08-15 (in 1 year, 3 months) / Bahrain residency
since 2022-08-15". Helper `_humanize_duration(years, months)` expands
abbreviations and pluralizes correctly ("1 year" vs "2 years, 1 month";
"less than 1 month" for sub-30-day deltas). The second line (residency-
since) renders only for `nationality_status='foreign_residency'` with
a non-NULL `bahrain_residency_start_date`; other branches return
`note=None` and the template omits the second line.

7 cases asserted in the E2E (bahraini / foreign_ancestry / future-
dated / past-dated / pending / not_eligible / unknown), all PASS.

### Item 3 — flag SVG

Emoji flags ("🇧🇷") rendered unreliably under WeasyPrint — Pango's
fallback font chain on Windows doesn't always include a color-emoji
font, and the regional-indicator codepoints often degraded to
square outline boxes.

Vendored **271 SVGs** from the upstream
[flag-icons](https://github.com/lipis/flag-icons) project (MIT-licensed
— attribution copied to `app/static/flags/LICENSE-flag-icons` and
`README.md`). Total bundle ~2.4 MB; each file ~1-3 KB. Filenames are
ISO 3166-1 alpha-2 codes (`bh.svg`, `br.svg`, `ma.svg`, ...). New
`_flag_svg_inline(alpha3_code)` helper in `app/passport/data.py`
translates the platform's alpha-3 codes via the existing
`ALPHA3_TO_ALPHA2` map, reads the file, and returns the inline SVG
string (or `None` for unknown codes; template skips the flag span
when None). Inline SVG sized to 18pt × 13.5pt (4:3 ratio matching
the flag-icons "4x3" set), bordered for clarity.

### Item 4 — Wyscout subtitle

New `_build_season_subtitle(player_id)` in `app/passport/data.py`
emits one of:
- "YYYY-YY season · N matches"
- "YYYY-YY to YYYY-YY · N matches"
- (or None if no Wyscout data — template omits the subtitle line)

Format kept as `'YYYY-YY'` (hyphen — matches Phase 4.2's `derive_season`
and the live DB column). The 4.1 helper `season_label_for_date` returns
slash-format but is currently unused anywhere in the codebase, so
the format mismatch flagged at end of 4.2 is now a "rename
`season_label_for_date` or delete it" cleanup item (recorded in
PROJECT.md follow-ups, not done in this patch).

### Item 5 — timing instrumentation + UI loading indicator

`render_passport_pdf` now logs `template=...s  weasyprint=...s
total=...s  bytes=...` at WARNING level (Flask's default level filters
out INFO). Sample measurements on this Windows + GTK dev box:

```
passport PDF render: template=0.019s  weasyprint=11.95s  total=11.97s  bytes=62464
passport PDF render: template=0.000s  weasyprint=12.40s  total=12.40s  bytes=62951
```

Template phase is ~20ms (no N+1 queries); WeasyPrint dominates at
~12s. **PDF generation latency is therefore ~12s on Windows due to
GTK Pango overhead.** Production Linux deployment will be
significantly faster (typical ~2-3s for the same workload).
PDF caching not implemented in v1 — regenerated per request.

UI: the profile-page download buttons now show "⏳ Generating…" on
click via inline JS, with `pointer-events: none` to swallow
double-clicks during generation. No JS library dependency. Since
the click initiates a file download (not a navigation), the page
itself stays put — once the download arrives the user moves on.
The 5-10s expectation is also written into the button's `title`
hover tooltip.

### Files

```
app/passport/data.py                     MOD — passport-specific eligibility, flag SVG loader, season subtitle helper
app/passport/renderer.py                 MOD — timing instrumentation (WARNING-level log)
app/passport/radar_svg.py                MOD — viewBox 280→360, margin 12%→22%, label headroom
app/templates/passport/passport.html     MOD — subtitle line, inline SVG flag, page-break div removed
app/templates/passport/_passport.css     MOD — block layout for wyscout-grid, tightened page-1 rhythm, flag-inline sizing, page-break-inside avoid on scout panels
app/templates/players/profile.html       MOD — passport-btn class + onclick loading state + pointer-events:none
app/static/flags/                        NEW — 271 SVGs + README + LICENSE-flag-icons (MIT)
migrations/_e2e_phase_6_1.py             NEW — 57-check E2E for the polish deltas
```

No schema changes; no migrations; no Python deps added.

### Verified

- **6.1 E2E: 57/57 PASS** ([migrations/_e2e_phase_6_1.py](migrations/_e2e_phase_6_1.py))
  - All 6 radar axis labels present in PDF text (no clipping)
  - 'Eligible from' + 'Bahrain residency since' present; 'Article 5'
    and 'admin to confirm' absent
  - 7 eligibility branches asserted via `_build_passport_eligibility`
  - Flag SVG loads for BRA/BHR/MAR, returns None for unknown
  - `class="flag-inline"` + `<svg>` present in rendered HTML
  - Wyscout subtitle "2025-26 season · 18 matches" present
  - Profile-page button has `passport-btn` + onclick + `pointer-events: none`
  - Timing log captured in Flask log; template < 1s sanity, weasyprint > 0
- **6.0 regression E2E: 26/26 still PASS** ([migrations/_e2e_phase_6.py](migrations/_e2e_phase_6.py))
  — Phase 6's behaviours intact (filename pattern, public-mode
  redaction, 404s, audit log, etc.)
- **Visual spot-check** (rasterized via pypdfium2):
  - Arthur full (62KB, 2pp): page 1 bio+eligibility+stats; page 2 radar+scout
  - Arthur public (63KB, 2pp): identical layout + 'PUBLIC' badge + 'Scout N' redaction
  - Bouhra full (57KB, 2pp): eligibility wording matches spec table verbatim
    — "⏳ Eligible from 2027-08-15 (in 1 year, 3 months) / Bahrain residency since 2022-08-15"

### Out of scope (for v0.6.1)

- Eligibility status icons (✅/⏳/❌) still render as monochrome outline
  glyphs (same emoji-font fragility we fixed for flags); could be
  swapped to inline SVG too if the monochrome rendering bothers
  committee reviewers
- PDF caching (deferred — single-digit-second latency acceptable in v1)
- `season_label_for_date` (4.1) format alignment with the DB column
  — function is currently unused, low priority

## v0.6.0 — Phase 6: Player Passport PDF (2026-05-11)

The demo-ready milestone — the printable artifact BFA committee members
take home from selection meetings. Two-page A4 PDF: bio + eligibility +
Wyscout career stats + 6-axis radar (page 1), scout evaluations + history
table + audit footer (page 2). Bilingual EN/AR. Major version bump
(0.5.x → 0.6.0): first non-incremental user-facing artifact, not just an
admin-facing data fix.

### Locked decisions

| Decision | Choice |
|---|---|
| PDF library | WeasyPrint 68.1 (HTML+CSS → PDF; requires GTK runtime on Windows) |
| Page size | A4 portrait, 20mm margins |
| Fonts | Inter (system fallback to Segoe UI) Latin; Cairo (system fallback to Segoe UI) Arabic |
| Branding | BFA red `#C8102E` for headings, gold `#B5924C` for accents, white background (printable) |
| Photos | base64 data-URI embed (self-contained PDF, no network at render time) |
| Radar | Hand-built 6-axis SVG (`app/passport/radar_svg.py`) — no JS, no Chart.js |
| Caching | None for v1 — regenerate per request |
| Filename | `BFA-Scout_Player-{id}_{slug}_{YYYY-MM-DD}.pdf` |

### Two modes

**Full** (admin / TD / scout, default route): scout names, evaluation
summaries, admin eligibility notes — everything visible.

**Public** (`?public=1`, any authenticated user): redacted for sharing
with player agents or external clubs.
- Scout names → `Scout 1` / `Scout 2` / … (stable per-passport mapping;
  same human keeps the same number across the latest panel AND the
  history table)
- `eligibility_notes_admin` and `bahrain_residency_notes` stripped
- **Generator name redacted** to `BFA Scouting Department` in the
  footer (design call — not in the original spec, but implied by the
  "for sharing externally" use case; named explicitly here so the
  next maintainer doesn't accidentally un-redact it)
- Header gets a `PUBLIC` badge, footer notes "scout identities redacted"

### Files

```
app/passport/__init__.py           NEW — Blueprint + route + filename slugify + photo embed
app/passport/data.py               NEW — get_passport_data(player_id, mode)
app/passport/radar_svg.py          NEW — hand-built 6-axis radar SVG
app/passport/renderer.py           NEW — WeasyPrint orchestration
app/templates/passport/passport.html  NEW — page 1 + page break + page 2
app/templates/passport/_passport.css  NEW — print stylesheet
app/templates/players/profile.html    MOD — Phase 6 placeholder → real download buttons
app/__init__.py                    MOD — register passport blueprint
migrations/_e2e_phase_6.py         NEW — 26-check end-to-end (real Flask + real HTTP)
```

No schema changes.

### Data layer (`app/passport/data.py`)

Pure read-side. Composes existing helpers across `app/players`,
`app/evaluations`, and `app/wyscout` — no new SQL helpers below.

- Wyscout summary mapped from `get_player_summary()`'s actual field
  names (`matches`, `total_minutes`, `total_goals`, ..., `pass_accuracy`,
  `duel_win_rate`) — the spec template used different names like
  `wyscout.matches_count`, `pass_pct`; the data layer normalises to the
  passport template's shape so the template stays clean.
- `aerial_won_pct` computed inline from `wyscout_match_stats`
  aggregation — `get_player_summary()` doesn't include this metric.
- 6-axis radar uses **existing `RADAR_AXES`** (Scoring / Passing /
  Dribbling / Defending / Aerial / Work Rate) — the spec's described
  axes (Goals/90, Pass %, etc.) differ from what's actually in
  `app/wyscout/helpers.py`. Codebase wins per the (1.5) playbook:
  consistency with the existing player-profile radar matters more
  than spec-template fidelity.
- Soft-delete invariant honoured via `get_player_evaluations()`
  (Phase 5c-3); locked evaluations INCLUDED (locked is workflow
  protection, not data hiding).
- `is_active=FALSE` (deactivated) players return None → route emits 404.

### Renderer (`app/passport/renderer.py`)

Single function `render_passport_pdf(data)` — renders `passport.html`
with the data dict and pipes it through WeasyPrint with the print CSS.
`base_url` set to `current_app.root_path` to resolve any relative
asset references (defensive — photos are embedded as data URIs so this
is belt-and-braces only).

### Radar SVG (`app/passport/radar_svg.py`)

Self-contained 6-axis polygon SVG. Hand-built (~150 lines of Python):
- 5 concentric grid polygons at 20/40/60/80/100 (the 100 ring slightly
  darker for the bounding edge)
- 6 axis spokes from centre to outer vertex
- Polygon for player scores (BFA red, 30% alpha, dotted vertices)
- Axis labels + numeric values just outside the 100 ring
- Tick labels (20/40/60/80) on one spoke

No fonts embedded — uses `font-family="Inter, Arial, sans-serif"` as a
hint; WeasyPrint resolves via system fontconfig.

### Pre-flight environment note

WeasyPrint requires the **GTK runtime** on Windows (Pango / GLib /
cairo native DLLs). On this machine, none of the usual sources
(MSYS2, GTK3-Runtime installer, Inkscape, GIMP) were installed — caught
during pre-flight via `import weasyprint; weasyprint.HTML(...).write_pdf()`
raising `OSError: libgobject-2.0-0.dll could not be found`. Surfaced as
a three-way choice (install GTK / fall back to xhtml2pdf / fall back to
ReportLab); Ali picked GTK install. After that, WeasyPrint loaded
cleanly and the spec's HTML/CSS template landed verbatim with proper
Arabic shaping for player names like `سيف الدين بوحرة`.

### Pre-flight catches surfaced before any code landed

1. `get_player_photo(player_id, national_id)` per spec — actual signature
   is 1 arg and returns a URL not a path. Wrote `_resolve_photo_data_uri`
   in the passport package to read the file and base64-embed it.
2. Wyscout summary field names differ from spec template; mapped in data layer.
3. Radar axes differ from spec; used existing `RADAR_AXES`.
4. No BFA logo asset in repo; rendered a styled `BFA` text mark instead.
5. No fonts directory; rely on system fontconfig (Cairo if installed
   system-wide, Segoe UI for Arabic on Windows).
6. **Pre-existing 4.2 cleanup item flagged** (not in scope): two
   season helpers now exist with different output formats —
   `app/wyscout/helpers.py:season_label_for_date` (returns `'2024/25'`)
   vs `app/wyscout/season.py:derive_season` (returns `'2024-25'`).
   `season_label_for_date` is currently unused but if anything starts
   calling it the formats won't match.

### Verified end-to-end

**26 / 26 synthetic E2E checks PASS**
([migrations/_e2e_phase_6.py](migrations/_e2e_phase_6.py)):

- Case 1 — Full-mode PDF: HTTP 200, `application/pdf`, `%PDF-` magic,
  53,313 bytes, filename `BFA-Scout_Player-2_arthur-rezende_2026-05-11.pdf`
- Case 2 — Public-mode redaction (text-extracted via pypdf): real scout
  name `'Initial Administrator'` does NOT appear in public PDF text;
  DOES appear in full PDF text; `Scout 1` marker present; footer says
  "redacted"
- Case 3 — Admin notes scrubbed: live-DB sentinel strings injected into
  `eligibility_notes_admin` and `bahrain_residency_notes`; absent from
  public PDF, present in full PDF; sentinels restored to prior values
- Case 4 — 404s for nonexistent (id=10031) and deactivated (id=1, Sayed)
  players
- Case 5 — Audit log: 4 rows generated this run with `player_id` + `mode`
  in `details`; both `full` and `public` modes recorded
- Case 6 — Unauthenticated request bounces to `/auth/login?next=...`
- Case 7 — Sparsest-data player (Gelonson, 15 Wyscout rows + 0 evals):
  PDF still generates cleanly with the page-2 empty-state panel

Visual inspection (pypdf text-extract) confirmed:
- Page 1: bio grid + eligibility card + Wyscout 10-metric table +
  6-axis radar with numeric labels at vertices
- Page 2: latest-eval panel with NT-level/recommendation badges +
  4 category-average bars + recent-evaluations table (date / scout /
  match / NT level / recommendation) + footer with generator name
- Public mode: `PUBLIC` badge in header, all scout names → `Scout 1`,
  generator → `BFA Scouting Department`, footer redaction notice

## v0.5.0-4-2 — Phase 4.2: Season column + backfill (2026-05-11)

Minimal infrastructure phase — closes the gap where `wyscout_match_stats`
had no first-class season notion. Schema + ingest only; no UI work
(deferred to Phase 4.2.1 when multi-season data exists). Project status
~92%.

### Schema
- New `wyscout_match_stats.season VARCHAR(7)` column. Nullable
  (defensive — current schema has `match_date NOT NULL`, so `season`
  is effectively NOT NULL via implication, but keeping the column
  nullable survives a future relax).
- New `idx_wyscout_match_stats_season` index for the season filter
  UI that 4.2.1 will add.
- `schema.sql` updated declaratively — column inline in the CREATE
  TABLE, index next to the four existing wyscout_match_stats indexes.
  No ALTER statements in `schema.sql`.

### Python helper (`app/wyscout/season.py`)
- `derive_season(match_date: date) -> str` — single source of truth.
  BPL season runs Aug–May (`SEASON_START_MONTH = 8`); a match in
  Aug 2025 → '2025-26'; a match in Apr 2026 also → '2025-26'.
- Returns `'<startYear>-<endYearLast2>'` with zero-pad (year 2000 → '00').

### Ingest path (`app/wyscout/ingest.py`)
- Imports `derive_season`; computes per-row `season = derive_season(match_date)`
  inside the existing UPSERT loop.
- Threads `season` through the dict-based `vals = {...}` pattern. Since
  column lists are built from `vals.keys()` and the UPDATE-SET excludes
  only the conflict-key cols (`player_id`, `match_label`, `match_date`),
  the new column is automatically present in both the INSERT and the
  `season = EXCLUDED.season` UPDATE clause — no hand-rolled SQL.

### Migration artifact (`migrations/phase_4_2_season_column.sql`)
- Generator (`_generate_phase_4_2.py`) asserts 5 `derive_season` unit
  tests pass BEFORE emitting SQL (cross-year boundaries: Jul/Aug pivot,
  Apr-of-following-year, next-season start).
- Pre-flight gates:
  - `wyscout_match_stats.season` must not already exist (one-shot guard)
  - all `match_date` values must fall in [2025-08-01, 2026-08-01) —
    the verified 2025-26 window. Migration RAISEs if a multi-season
    import has already landed; in that case regenerate with a widened
    audit gate first.
- Backfill: SQL CASE mirrors `derive_season()` exactly using
  `% 100` + `LPAD(..., 2, '0')`. The spec's original
  `LPAD(...)::TEXT[3:4]` syntax doesn't parse on Postgres (array
  slicing not applicable to TEXT) — caught + fixed in pre-flight.
- Audit gate computes `expected` dynamically (`COUNT(*) WHERE
  match_date IS NOT NULL`), not hardcoded — the spec's `expected =
  34` was already stale (49 rows today). RAISEs if any
  match_date-bearing row has NULL season, or if the `'2025-26'` count
  doesn't equal the expected count.

### Verified end-to-end

**18 / 18 synthetic E2E checks PASS** ([migrations/_e2e_4_2.py](migrations/_e2e_4_2.py)):

- Column shape: `VARCHAR(7)`, nullable, present
- All 49 existing rows have season set; all are `'2025-26'`
- Python helper vs DB cross-check: `derive_season(match_date) ==
  row.season` for all 27 distinct match_dates in the live DB
- Real-pipeline re-upload of Arthur's xlsx via `ingest_wyscout()`
  (NOT `flask.test_client`): status=success, 0 inserted / 18 updated /
  0 skipped; row count unchanged at 18; all rows still
  `season='2025-26'` after UPSERT
- Per-player breakdown:
  Arthur Rezende 18, Gelonson Wilson Da Silva Moreira 15,
  Saifaldeen Bouhra 16 = 49 rows, all '2025-26'

### Migration discipline (standard pattern)
1. `_generate_phase_4_2.py` (assert 5 unit tests, emit SQL)
2. `_dryrun_4_2.py` (savepoint + rollback against live DB)
3. `_apply_4_2.py` (same SQL, COMMITs on audit pass)
4. `_verify_throwaway_4_2.py` (fresh schema, run `schema.sql`,
   confirm column shape + index + 5 wyscout indexes)
5. `_e2e_4_2.py` (cross-check Python ↔ SQL + UPSERT preservation)

### Out of scope (deferred to Phase 4.2.1)
- Season-toggle UI on `/players/compare/view` and player profile dashboard
- Multi-season aggregations in scout dimension
- Gated on a second season of data existing — adding a UI toggle for a
  single-value column would just be visual noise

## v0.5.0d.1 — Phase 5d-1: Scout-assessment radars (2026-05-10)

UI-only follow-up to 5d. Adds Chart.js radar visualisations to the scout
section: one category-level overview + one per-category drill-down (5 in
total). Pure read-side; no schema changes, no new helpers below the data
shaper. Project status ~92%.

### What landed

**Item A — Top "category averages" radar.** 4-axis (Technical / Tactical /
Physical / Mentality) overlapping radar above the per-category drill-down,
one polygon per selected player. Built from `category_averages` already
aggregated in Phase 5d. BFA red + gold + blue palette (matches the
Wyscout overlapping radar in `compare.js` for visual cohesion).

**Item C — Per-category drill-down radars.** One additional radar inside
each category's `<details>` block, with axes = criterion `name_en` for
that category. For the AM ∪ DM union covered in the 5d patch E2E, axes
counts are Technical 8, Tactical 20, Physical 15, Mentality 6 = 49 total
(matches the criteria-union row count in the existing drill-down table).

**N/A handling.** Chart.js radar treats null values as polygon gaps
(visually messy when one player has 12/16 axes filled and another has
9/16). Untouched and N/A criteria therefore plot as 0 to keep polygons
closed; tooltips read "N/A" or "— (not in player profile)" so the truth
is never lost in the hover. Wired through parallel `values` /
`annotations` arrays per dataset, computed in `build_scout_radar_data`
and consumed by `scout_radars.js`.

**HTMX-aware re-init.** All 5 radars re-render when the Latest ↔ Averaged
toggle swaps `#scout-section`. `scout_radars.js` listens for
`htmx:afterSwap` (filtered by `event.detail.target.id === 'scout-section'`),
and `Chart.getChart(canvas)?.destroy()` runs before each re-create to
avoid leaks. The partial route returns the section markup including the
canvases but NOT the script tag (the JS is already loaded from the
initial page render).

**Eager init, not lazy.** Phase 5d's `<details open>` decision means all
4 sub-collapses are visible on page load — lazy-init would just delay
rendering the user already wants to see, with zero saving. Decision
explicitly documented in `scout_radars.js`.

**Scale = 0..10 (matches `criteria.scale_max`).** Caught a pre-flight
miss before commit: I'd assumed 0..5 from memory of the slider component,
but the schema and seed both confirm 1..10 (DB scores currently span
[2.0, 10.0]). Radar axis: `min: 0, max: 10, stepSize: 2`; tooltip suffix
`/ 10`. The (1.5)-class lesson is now in the standing playbook: if a
spec assumption contradicts a codebase decision, surface it before
building.

### Files

- `app/evaluations/helpers.py` — new `build_scout_radar_data(data,
  grouped_criteria)` pure transform; returns
  `{category, per_category}` Chart.js-ready configs
- `app/players/__init__.py` — `_enrich_for_scout_section` calls the
  new helper and threads `scout_radar_data` to the template context
- `app/templates/players/_compare_scout_section.html` — new top-radar
  block above the drill-down `<details>`
- `app/templates/players/_compare_scout_drilldown.html` — per-category
  radar canvas above each category's table (inside the `<details>` block)
- `app/templates/players/compare_view.html` — `<script>` tag for
  `scout_radars.js` (defer-loaded after `compare.js`)
- `app/static/js/scout_radars.js` — NEW. Eager DOMContentLoaded init +
  htmx:afterSwap re-init; Chart.js radar with 0..10 scale, BFA palette,
  annotation-aware tooltips

### Verified end-to-end

**39 / 39 synthetic E2E checks PASS** ([migrations/_e2e_5d_1.py](migrations/_e2e_5d_1.py)):

- Page render: 5 canvases on full-page render in latest mode (1 category
  + 4 per-category); 4 fixed top axes; 2 datasets (one per player)
- Per-category axis counts [6, 8, 15, 20] = 49 total — matches the AM∪DM
  criteria union sanity-checked in the 5d patch E2E
- All values numeric in [0, 10]; no nulls (N/A and absent plot as 0)
- Annotation distribution exercises all three states: rated=41, na=1,
  absent=56 (cross-position non-applicable cells dominate, as expected)
- Averaged mode: 5 canvases on the swapped page; top-radar values differ
  from latest mode (sample diff: TECH 5.0 → 7.5 for player 6) — toggle
  visibly reshapes polygons
- HTMX partial: returns 5 canvases (so re-init has targets) but NOT the
  script tag (JS already loaded)
- JS sanity: defines `initScoutRadars`; calls
  `Chart.getChart(canvas).destroy()` before re-create; wires
  `DOMContentLoaded` and `htmx:afterSwap` (guarded by target id
  `scout-section`); `max: 10` and `/ 10` tooltip
- Regression: all 5d patch behaviours still hold (4 categories rendered,
  Wyscout `compareRadar` canvas still present, hx-get/hx-target/
  hx-push-url all on the toggle anchors)

## v0.5.0d — Phase 5d: Scout dimension on comparison page (2026-05-09)

The session that finally puts scout judgment alongside Wyscout numbers
on the comparison view. Pure read-side aggregation — no schema changes.
Project status ~91%.

### 5d patch (landed in the same commit)
Three issues surfaced during browser spot-check; all fixed before commit:

1. **Match label visible in Latest-mode header** —
   `get_player_evaluation_aggregate(mode='latest')` SELECT extended with
   `LEFT JOIN matches`. Helper now emits `match_label` (e.g. "Khalidiya
   vs Manama" or "Freestanding (no match linked)") and `match_date`.
   Averaged mode emits both as None (multiple matches; not meaningful).
   Header card renders `· {match_label}` after `· {date}` in Latest mode.

2. **HTMX swap for Latest/Averaged toggle** — new partial-only route
   `GET /players/compare/scout-section`. Toggle anchors gain `hx-get +
   hx-target="#scout-section" + hx-swap="outerHTML" + hx-push-url`
   (plain `href` retained as progressive-enhancement fallback). The
   `<section id="scout-section">` wrapper now lives inside
   `_compare_scout_section.html`, so the same template renders in both
   the full-page and partial contexts. Browser back-button restores
   prior mode (URL is pushed via `hx-push-url`).
   Enrichment logic extracted into `_enrich_for_scout_section()` helper
   in `app/players/__init__.py` so the route + partial route share it.

3. **Drilldown rendered only the first category** — diagnosed via direct
   helper call (route + helpers were producing 49 criteria correctly).
   Root cause was Jinja-side: the `{% set _ = grouped.update(...) %}`
   and `{% set _ = cat_order.append(...) %}` pattern in the original
   `_compare_scout_drilldown.html` silently failed to mutate across
   loop iterations past the first. Fixed by moving grouping into Python
   via new `group_criteria_by_category()` helper (mirror of
   `group_scores_by_category` from 5c-2.1). Template now consumes a
   pre-grouped list. All 4 categories (Tech/Tact/Phys/Ment) render
   correctly with criteria union AM ∪ DM = 49 rows.

   Spec hypothesised the bug was in `compare_players()` not propagating
   `position_group_id` — direct helper inspection ruled that out before
   any code changes. Documented in CHANGELOG so future maintainers know
   what to check first if a similar Jinja-mutate symptom appears.

   **Follow-up UX touch (same commit):** the per-category sub-collapses
   now render with `<details open>` so the data is visible immediately
   when the scout expands the outer "Detailed criteria comparison". The
   prior closed-by-default sub-collapses showed only category headers
   on first expand — looked empty until the user clicked a second time
   into each category. Confirmed via live HTML check: 4/4 categories
   now open by default in both the full-page route and the HTMX partial.

### 29/29 patch E2E PASS

### Helpers (`app/evaluations/helpers.py`)
- `compute_category_averages(scores)` — `{category_code: avg}` over the
  rated entries; N/A and `score IS NULL` excluded; empty categories
  omitted.
- `get_evaluation_count_active(player_id)` — submitted+locked, non-deleted.
- `get_player_evaluation_aggregate(player_id, mode)` — the workhorse:
  - `mode='latest'`  → most-recent qualifying eval with full scores
  - `mode='averaged'` → averages each criterion across all qualifying
    evals (rated only); NT-readiness + recommendation resolved via
    most-frequent-with-recency-tiebreak; per-criterion `eval_count`
    annotation tells the UI how many evals fed each averaged value
- `_fetch_eval_scores_with_categories()` — internal SQL helper joining
  `evaluation_scores` + `criteria` + `criteria_categories`
- `CATEGORY_LABEL_EN` dict (UPPERCASE keys to match `criteria_categories.code`)

All four respect the **Phase 5c-3 soft-delete invariant**:
`WHERE deleted_at IS NULL` everywhere. Locked evaluations are INCLUDED
(locked is workflow protection, not data hiding).

### Route (`app/players/__init__.py:compare_view`)
- Reads `?scout_mode=latest|averaged` (default `latest`); invalid →
  `latest` silently
- Calls helpers per player; sets `p['eval_count']` and `p['scout_data']`
- Computes the criteria union across selected players' position groups
  via the existing `get_form_criteria(position_group_id)` helper
- Threads `scout_mode`, `all_criteria`, `any_player_has_scout_data` to
  the template

### Wyscout aggregator (`app/wyscout/aggregations.py:compare_players`)
- `position_group_id` now included in the per-player dict (the route
  uses it to resolve criteria union for the drill-down)

### Templates
- `compare_view.html` — new section after the Wyscout radar with
  Latest/Averaged toggle (uses `urlencode_with` to preserve other args)
- `_compare_scout_section.html` — NEW. Per-player headline cards:
  category averages (4 fixed rows: TECH/TACT/PHYS/MENT, missing → "—"),
  NT-readiness + recommendation badges (EN labels + Arabic on hover),
  truncated summary in latest mode. Empty-state placeholder per column
  for players with no evals.
- `_compare_scout_drilldown.html` — NEW. Per-criterion table grouped by
  category (native `<details>` per category). One column per player.
  Cell semantics:
  - rated → numeric value (with `(N)` count in averaged mode)
  - is_NA → "N/A" badge
  - absent (cross-position non-applicable OR untouched) → "—"

### Jinja globals
- `CATEGORY_LABEL_EN` registered
- `urlencode_with(key, value)` registered — preserves other query args
  when building the toggle links

### Verified end-to-end
**26 / 26 synthetic E2E checks PASS** ([migrations/_e2e_5d.py](migrations/_e2e_5d.py)):

- Helpers: Arthur (2 evals) latest vs averaged differ on TECH (5.0 vs 7.5);
  Bouhra (2 evals from 2 different evaluators) averages compute correctly
- HTTP: Latest mode renders evaluator names, category avgs, badges
- HTTP: Averaged mode renders "N evaluations averaged" label + averaged values
- HTTP: Toggle highlights the active mode visually (background swap)
- HTTP: At least one of Arthur's category averages differs between modes
  (proves the aggregation isn't a no-op)
- Drill-down: AM-only criterion (`tech_set_pieces_attacking`) and
  DM-only criterion (`tact_long_ball_cover`) both appear in the union
- Drill-down: "—" cells appear for cross-position non-applicable criteria
  (regression on the criteria-union semantics)
- No-evals branch: ephemeral active player rendered with "No evaluations
  yet" placeholder
- Soft-delete invariant: deleting Arthur's latest eval makes the latest
  helper return the next-most-recent; averaged mode now averages 1 fewer
  eval; restore returns to original state
- Regression: Phase 4.1 Wyscout comparison heading + radar canvas + career
  stats table all still present
- Regression: Phase 4.1 GK-vs-outfield rule still applied (skip if no GK
  in DB)

### Deferred (per spec's deferral path)
- **Scout-vs-Wyscout dual radar**: marked nice-to-have in the spec with
  explicit deferral path. Category-average cards in the section convey
  the same information textually, and adding a second Chart.js radar
  would have spilled the session beyond its 5-8 message target.
  Recommend bundling into Phase 5e (NT readiness divergence flag) or
  picking up as a tiny standalone follow-up if a real scout asks for it.

### Known notes
- `urlencode_with` lives in `app/__init__.py` since the URL helper
  doesn't fit any of the existing helpers modules cleanly
- The averaged mode preserves a per-criterion `eval_count` annotation;
  the drill-down template renders it as `(N)` next to each averaged
  value so a scout can tell whether `7.5 (1)` is one rating or
  `7.5 (3)` is three convergent ratings

## v0.5.0c3 — Phase 5c-3: UI/UX polish (2026-05-09)

### 5c-3 follow-up — new-player workflow parity
The 5c-3 spec only listed `players/edit.html` for the new pickers and
admin block; `players/new.html` was overlooked, leaving the create form
stuck on the old plain-text nationality + current_club inputs and
missing the eligibility/residency fieldset entirely. Fixed:

- `app/templates/players/new.html` — same nationality dropdown
  (309 entries, Bahrain pinned first), same club picker w/ Premier +
  First Division optgroups + "Other (free text)" escape, same admin-only
  NT-eligibility/residency fieldset (mirrors edit.html exactly)
- `app/players/__init__.py:new_player()` — POST handler now reads
  `nationality_code` (validates against ISO list), `club_id` (with
  "other" → free-text fallback), and the admin-only block; INSERT
  branched on `is_admin_td` so scout-submitted eligibility fields are
  silently dropped (defense-in-depth on top of template hiding)
- `migrations/_e2e_5c3_newplayer.py` — 42/42 PASS verifying:
  - GET form has all the new structured fields
  - admin POST persists every field through to DB
  - new player's profile renders eligibility card + flag + bio counts
  - scout POST silently drops admin-only fields (4-case verification:
    nationality_status / bahrain_residency_start_date /
    eligible_from_date / eligibility_notes_admin all NULL)


Six items + the soft-delete invariant. ~88% project status.

### Schema changes
- New `clubs` table: 24 Bahraini clubs seeded (12 Premier + 12 First
  Division), with `division` CHECK enum + UNIQUE (name, division)
- `players.nationality_code` (CHAR(3), nullable) — ISO 3166-1 alpha-3
- `players.club_id` (FK to `clubs(id)` ON DELETE SET NULL)
- `evaluations.deleted_at` + `deleted_by` (FK users SET NULL) +
  `deleted_reason` (TEXT)
- `evaluations_soft_delete_consistency` CHECK enforces all-three-or-none
  with min 10-char reason

### Spec extension — backfill SQL
The spec's three fuzzy-match patterns wouldn't have matched the cases
the spec writer expected (Arthur's "Muharraq Club" / "Al-Muharraq",
Bouhra's "Khalidiya" / "Al-Khalidiya", Sayed's "Riffa" / "Al-Riffa").
Added a fourth REGEXP_REPLACE pattern that strips `^Al-` from clubs.name
AND ` Club$` from current_club, then case-insensitive compares. All 3
existing players linked correctly.

### Soft-delete invariant
Every existing read query in `app/evaluations/helpers.py` now filters
`WHERE deleted_at IS NULL`. Each helper has a docstring noting this.
Functions touched: `get_or_create_draft`, `get_evaluation`,
`submit_draft`, `lock_evaluation`, `unlock_evaluation`,
`admin_edit_evaluation`, `get_player_evaluations`, `nt_readiness_summary`.
The `list_deleted_evaluations` helper (admin recovery) is the documented
exception that explicitly inverts the filter.

### App
- `app/players/nationalities.py` — NEW. 249 nationality entries +
  alpha-3 → alpha-2 mapping + `flag_emoji()`. Generated once via
  `pycountry` (build-time only); pycountry uninstalled after generation
  so no runtime dependency.
- `app/players/clubs.py` — NEW. `get_clubs_grouped()`, `get_club_label()`.
- `app/players/__init__.py` — `_search_players` accepts `nat` + `club`
  filters; edit handler reads `nationality_code`/`club_id`/`current_club_other`
  with "other" escape; profile route fetches `bio_counts`.
- `app/evaluations/helpers.py` — `soft_delete_evaluation()`,
  `restore_evaluation()`, `list_deleted_evaluations()`,
  `get_player_bio_counts()` added.
- `app/evaluations/__init__.py` — `POST /evaluations/<id>/delete`
  (`@scout_or_above`; helper enforces scout=own-draft, admin=any non-locked),
  `POST /evaluations/<id>/restore` (`@admin_or_td_required`). Both
  audit-logged.
- `app/admin/__init__.py` — `GET /admin/deleted-evaluations`
  (`@admin_required`); pure recovery view.

### Templates
- `players/edit.html` — nationality dropdown (211+ options, Bahrain first);
  club dropdown with Premier/First optgroups + "Other (free text)" escape
  hatch (Alpine `showOther` toggles a text input)
- `players/profile.html` — bio counts strip ("📊 N matches · 📝 N evaluations")
  with deleted_at filter on the evaluation count
- `players/_grid.html` — flag emoji + ISO code per card
  (e.g. "🇧🇷 BRA")
- `players/list.html` — nationality + club filter dropdowns added to the
  existing HTMX live-update row (q + pos + elig + nat + club)
- `evaluations/_history_card.html` — Delete button (role-gated; scout
  own-drafts only; admin any non-locked); includes the new modal
- `evaluations/_delete_modal.html` — NEW. Reason textarea
  (`minlength="10"`, required) with Cancel + Delete buttons
- `admin/deleted_evaluations.html` — NEW. Recovery table with player +
  match + evaluator + deleter + reason + Restore button

### CSS
- `app/static/css/style.css` — date / number / time / datetime-local
  inputs themed for the dark UI; calendar-picker indicators inverted
  via `filter: invert(1) opacity(0.6)`; spin buttons themed similarly

### Verified end-to-end
**43 / 43 synthetic E2E checks PASS** + 2 lifecycle FK invariant tests:

- Item 1: 309 nationality options rendered, Bahrain first
- Item 2: Premier+First optgroups present, "Other" path, all 24 clubs
- Item 3: CSS theming served by Flask, includes calendar-picker filter
- Item 4: 6 permission/state combinations
  - scout deletes own draft (→ deleted_at set, deleted_by=scout) ✓
  - scout cannot delete submitted (→ rejected) ✓
  - admin deletes submitted ✓
  - reason < 10 chars rejected ✓
  - locked cannot be deleted ✓
  - admin recovery page accessible to admin (200), 403 to scout ✓
  - restore clears all 3 deleted_* columns atomically ✓
- Item 5: bio counts honour deleted_at filter (rendered count drops
  by 1 after a delete; matches DB count exactly)
- Item 6: 🇧🇷 flag emoji + BRA code on Arthur's card
- List filters: nat=BRA isolates Arthur; club=Al-Muharraq isolates
  Arthur; club=other returns no players (all 3 backfilled)

### FK lifecycle invariants (memory rule)
1. `clubs` delete → `players.club_id` set NULL, player survives. ✓
2. `users` delete when user has soft-delete records → **rejected** by
   the all-three-or-none CHECK constraint (FK ON DELETE SET NULL would
   produce half-deleted state). This emergent invariant preserves
   accountability — you can't hard-delete a user who deleted any
   evaluation without first restoring all of their deletions OR
   re-attributing them.

### Known notes
- `nationality` legacy free-text column on players is preserved but no
  longer read on edit; `nationality_code` is now the source of truth
- `current_club` is kept as a denormalised cache from `clubs.name` so
  existing code that reads `player.current_club` keeps working without
  joins (templates, downstream queries)
- Backfill resolved all 3 existing players to clubs successfully:
  Sayed → Al-Riffa, Arthur → Al-Muharraq, Bouhra → Al-Khalidiya
- E2E temporarily reset `scout@bfa.bh` password to
  `phase5c3-temp-reset-2026-05-09`; admin should rotate via UI
- pycountry was a build-time only dependency; no runtime import in
  the app

## v0.5.0c2.1 — Phase 5c-2.1 patch (2026-05-09)

Four browser-spotted issues from 5c-2. No schema changes — pure
application-layer fixes.

### Item 1 — Eligibility card moved up
- `app/templates/players/profile.html` — eligibility card now renders
  immediately after the player header strip, BEFORE the Wyscout
  dashboard. Most committee-relevant info is the first thing visible
  after identifying who the player is.

### Item 2 — `compute_eligibility_status` priority order fix
The 5c-2 implementation returned "Status unknown" whenever
`eligible_from_date` was NULL, ignoring `nationality_status` entirely.
Confusing: "?  Status unknown" with "Status: Foreign Residency" right
underneath.

`app/players/eligibility.py` — replaced with 6-priority logic:
1. `not_eligible` → ❌ Not eligible
2. `bahraini` / `foreign_ancestry` → ✅ Eligible now (birthright; date irrelevant)
3. `eligible_from_date` set → ✅/⏳ based on date (overrides residency-derived)
4. `foreign_residency` + `bahrain_residency_start_date` → derived suggested
   eligibility (Article 5; admin to confirm)
5. `foreign_residency` without residency_start → ⏳ Pending — residency start not set
6. `foreign_other` without date → ? Foreign-eligible (other route)
7. otherwise → ? Status unknown

Also handles `bahrain_residency_start_date` arriving as ISO string
(form-data path) by parsing inside the function.

### Template cleanup
- `app/templates/evaluations/_eligibility_card.html` — removed redundant
  "Status:" line (now duplicates the icon-line verdict). Replaced with
  smaller "Route:" line that's still useful — shows the EN+AR route
  label without claiming a separate eligibility verdict.
- New `NATIONALITY_ROUTE_LABEL_EN` dict in
  `app/evaluations/helpers.py` — short labels for the Route line
  ("Foreign — residency" instead of "Foreign Eligible Residency").
- Registered as Jinja global in `app/__init__.py`.

### Item 3 — Section-grouped expanded scores
`app/evaluations/helpers.py` — new `group_scores_by_category()` that
takes the flat scores list returned by `get_player_evaluations` and
groups by category. Each group has:
- per-category average (rated only; N/A excluded from avg)
- rated count + N/A count
- empty categories omitted entirely

`get_player_evaluations` SQL extended to JOIN `category_name_ar`
(spec wanted EN+AR pairs in the section header).

`app/templates/evaluations/_history_card.html` — flat scores table
replaced with native `<details>` collapse per category, summary line
per section showing `<avg> · X rated, Y N/A`.

`group_scores_by_category` registered as Jinja global.

### Item 4 — Players list eligibility column + filter
The list uses an HTMX-driven card grid (not a table — adapted Item 4's
intent to fit). Two changes:

`app/templates/players/_grid.html` — eligibility line per card showing
icon + label + condensed date suffix (parses out the `From `/`Suggested `
prefix to save space).

`app/templates/players/list.html` — third filter dropdown (`elig`)
added to the existing `q` + `pos` HTMX live-filter row. 5 options:
all / eligible_now / pending / not_eligible / unknown.

`app/players/__init__.py`:
- `_search_players(q, pos_id, elig=None)` — accepts the new filter
- `_ELIG_FILTER_CLAUSES` constant maps each value to a SQL `WHERE`
  fragment using `INTERVAL '5 years'` for the residency-derived path
- SELECT extended to pull `nationality_status`,
  `eligible_from_date`, `bahrain_residency_start_date` so the card
  template can call `compute_eligibility_status(p)` without a second
  query
- `list_players` route reads `?elig=...` from query string and threads
  it through the existing HTMX-include partial path

### Verified end-to-end
Synthetic E2E (48 / 48 PASS) covering:
- Item 1 — eligibility card position (before Wyscout dashboard, exactly once)
- Item 2 — all 7 priority cases A–G + 3 edge cases (residency past-due,
  explicit-date-overrides-residency, foreign_other) via profile rendering
- Item 2 cleanup — no "Status:" line, "Route:" line shown when
  applicable / hidden when status is null
- Item 3 — sub-section `<details>` blocks render with avg + counts
- Item 4 — eligibility filter dropdown present, filter SQL gives
  correct subset for each of 4 options across 7 ephemeral test players

### Files modified / created
- `app/players/eligibility.py` (M) — `compute_eligibility_status` rewritten
- `app/evaluations/helpers.py` (M) — `group_scores_by_category` added,
  `NATIONALITY_ROUTE_LABEL_EN` added, `get_player_evaluations` JOIN
  extended for `category_name_ar`
- `app/__init__.py` (M) — 2 new Jinja globals registered
- `app/players/__init__.py` (M) — `_search_players` accepts `elig`;
  `_ELIG_FILTER_CLAUSES` constant; route plumbed
- `app/templates/players/profile.html` (M) — eligibility card moved up
- `app/templates/players/list.html` (M) — eligibility filter dropdown
- `app/templates/players/_grid.html` (M) — per-card eligibility line
- `app/templates/evaluations/_eligibility_card.html` (M) — Route line
  replaces Status line; residency-from line simplified
- `app/templates/evaluations/_history_card.html` (M) — section-grouped
  expand with `<details>` per category
- `migrations/_e2e_5c2_1.py` (NEW) — 48-check synthetic E2E

### Known notes
- The `INTERVAL '5 years'` in the SQL filter clauses is hard-coded;
  if `RESIDENCY_YEARS_REQUIRED` ever changes from 5, update both files.
  Comment in `app/players/__init__.py` near `_ELIG_FILTER_CLAUSES`
  flags this.
- `_search_players` SELECT now pulls 3 extra columns per row;
  negligible cost, kept inline rather than adding a second query
  per request.

## v0.5.0c2 — Phase 5c-2: Final form story (2026-05-09)

The phase that closes the form story. Submitted evaluations finally appear
on the player profile, lock/unlock workflow protects records, eligibility
status is visible, mobile UX is polished, Arabic labels are baked in.
Project status now ~85% — true MVP.

### Schema changes
- `players`: 2 new admin-set residency-tracking columns
  - `bahrain_residency_start_date DATE`
  - `bahrain_residency_notes TEXT`
- `evaluations`: 3 new columns
  - `locked_reason TEXT` — captured on unlock for audit trail
  - `last_edited_by INTEGER REFERENCES users(id) ON DELETE SET NULL` —
    populated on admin-edit; preserves original `evaluator_id`
  - `last_edited_at TIMESTAMPTZ`
- `evaluations_locked_by_fkey` recreated with `ON DELETE SET NULL`
  (was default NO ACTION — would have blocked user deletion)
- Two new FKs (`locked_by`, `last_edited_by`) verified to honor
  `ON DELETE SET NULL` via lifecycle test (delete user → evaluation
  survives, FK columns nulled, status preserved)

### Spec corrections (vs the prompt as written)
- `locked_at` and `locked_by` columns **already existed** in Phase 0
  schema — migration skips re-adding them.
- `status CHECK` already includes `'locked'` — migration skips the
  no-op extension.
- Migration only adds the 5 truly-new columns + tightens the existing
  `locked_by` FK to ON DELETE SET NULL.

### App
- `app/players/eligibility.py` — new module:
  - `RESIDENCY_YEARS_REQUIRED = 5` constant (FIFA Article 5 baseline)
  - `compute_suggested_eligibility()` — start-date + 5y, with leap-year
    edge case (Feb 29 + 5y → Feb 28 in non-leap year)
  - `compute_eligibility_status()` — returns `{icon, label, note}` dict
    for the 4 states (eligible / pending / not eligible / unknown)
  - `count_orphan_scores()` + `delete_orphan_scores()` — for
    position-change confirm flow
- `app/evaluations/helpers.py` — extended:
  - `get_player_evaluations()` — history-card data with joined evaluator
    + last_edited_by + match info + per-eval scores list
  - `nt_readiness_summary()` — last-N submitted/locked tally
  - `lock_evaluation()`, `unlock_evaluation()`, `admin_edit_evaluation()`
  - Arabic translation dicts (NT_LEVEL_LABEL_AR, RECOMMENDATION_LABEL_AR,
    ELIGIBILITY_STATUS_LABEL_AR) + EN mirrors — baked verbatim from
    Phase 5c-2 spec table; registered as Jinja globals
- `app/evaluations/__init__.py` — three new routes:
  - `POST /evaluations/<id>/lock` (`@admin_or_td_required`)
  - `POST /evaluations/<id>/unlock` (`@admin_or_td_required`, requires
    `reason` field with min 10 chars)
  - `POST /evaluations/<id>/admin-edit` (`@admin_or_td_required`,
    blocked when status='locked')
  - All audit-logged with structured details
- `app/players/__init__.py` — extended:
  - `player_profile()` SELECT pulls new eligibility/residency columns
  - `edit_player()` POST handles new residency fields; admin/TD-only
  - Position-change orphan flow: detects criterion mismatch, re-renders
    the form with confirm modal, accepts `orphan_decision=delete|keep`,
    audit-logs the choice

### Templates
- `evaluations/_eligibility_card.html` — NEW: 4-state icon + label,
  optional admin-status code, latest-3 NT-readiness vote tally,
  Bahrain-residency note when applicable
- `evaluations/_history_card.html` — NEW: scout name, NT level + recommendation
  badges, summary snippet (200 chars), expand-toggle to full criteria
  scores grid (N/A-aware), role-gated lock/unlock actions in the
  expanded panel
- `evaluations/_soft_warning_modal.html` — NEW: <5 ratings non-blocking
  warning with "go back" / "submit anyway"
- `evaluations/form.html` — sticky save bar pinned to viewport bottom
  on `<768px`, soft-warning interception on submit, Arabic on the
  Save Draft / Submit buttons; slider thumbs ≥32px desktop / ≥44px
  mobile (iOS HIG) via `.bfa-range` CSS
- `evaluations/_slider.html` — exposes `data-dirty` + `data-na`
  attributes so the soft-warning JS can count rated sliders
- `evaluations/_nt_readiness.html` — Arabic labels baked verbatim into
  every radio option + section heading
- `evaluations/view.html` — admin/TD lock/unlock buttons + unlock-reason
  modal in status header; "edited by admin" badge; admin-edit affordance
  on submitted (not locked) evaluations
- `players/profile.html` — eligibility card + history cards replace
  the "Coming in Phase 5c-2" placeholder
- `players/edit.html` — Bahrain residency input + suggested-date UX
  ("Suggested: YYYY-MM-DD ⓘ" with Article 5 caveat tooltip + "Use
  suggestion" button); orphan-scores confirm modal

### Verified end-to-end
**55 / 55 synthetic E2E checks PASS** covering all 17 acceptance criteria.

| # | Acceptance check | Result |
|---|---|---|
| 1 | Pre-flight gates pass | ✓ (with documented stale spec on rows-12/13) |
| 2 | Migration AUDIT PASS, throwaway-namespace verify PASS | ✓ |
| 3 | Profile shows eligibility card + history cards (no remnant) | ✓ |
| 4 | Lock POST flips status, audit-logged | ✓ |
| 5 | Unlock with valid reason flips back, audit-logged | ✓ |
| 6 | Unlock with <10 char reason rejected | ✓ |
| 7 | Admin edit preserves evaluator_id, sets last_edited_by | ✓ |
| 8 | Admin edit blocked on locked evaluations | ✓ |
| 9 | Eligibility card renders 4 states correctly | ✓ |
| 10 | Latest-3 NT summary line renders | ✓ |
| 11 | Residency input + suggested-date UX works | ✓ |
| 12 | Position change with orphans → modal → delete OR keep | ✓ |
| 13 | Soft warning <5 ratings → modal markup present | ✓ |
| 14 | Mobile: sticky save bar markup + ≥44px slider thumbs CSS | ✓ |
| 15 | All Arabic translations baked verbatim from spec table | ✓ |
| 16 | Locked evaluations hide lock/unlock/edit from scout role | ✓ |
| 17 | schema.sql declarative-only (no ALTERs added) | ✓ |

Plus a lifecycle FK invariant test (rollback-wrapped): deleting a user
who locked an evaluation correctly nulls `locked_by` AND `last_edited_by`
without touching the evaluation row or its status.

### Verification gaps requiring browser
- Mobile rendering of sticky save bar at <768px (CSS media query)
- Slider thumb visual size (CSS-rendered, not in DOM)
- Modal click-through-and-back UX

### Known notes
- E2E test transiently reset `scout@bfa.bh` password to a temp value
  (`phase5c2-temp-reset-2026-05-09`); admin should rotate via UI when
  reviewing.
- The Phase 6 placeholder ("Coming in Phase 6.") for the Player Passport
  remains on the profile — that section ships in the next phase.

## v0.5.0c1.1 — Phase 5c-1.1: Tri-state slider (2026-05-09)

### Schema changes
- `evaluation_scores`: tri-state semantics
  - `score` is now NULLABLE (was NOT NULL)
  - `is_not_applicable BOOLEAN NOT NULL DEFAULT FALSE` added
  - `evaluation_scores_score_or_na` CHECK enforces (rated XOR N/A):
    `(score IS NOT NULL AND is_not_applicable = FALSE) OR
     (score IS NULL     AND is_not_applicable = TRUE)`
- All 14 pre-existing rows backfilled cleanly via the DEFAULT clause
  (every row was rated pre-migration, so default of FALSE is correct)

### App
- `app/templates/evaluations/_slider.html` — tri-state slider:
  - Three Alpine state vars: `value`, `dirty`, `na`
  - `reset()` method clears all three (✕ button calls it)
  - `toggleNA()` enables N/A and clears any prior rating; click again
    returns to fully untouched
  - `:disabled="na"` on `<input type="range">` blocks drag while N/A
  - Two `:name` toggles — score input only contributes to POST when
    `dirty && !na`; hidden N/A input only when `na`
  - Visual: opacity 60% when N/A, brand color when rated, muted dash
    when untouched, ✕ visible only when `dirty && !na`
- `app/evaluations/forms.py` — `parse_score_inputs` now returns
  `{criterion_id: {'score', 'is_not_applicable'}}`. Two-pass scan: first
  scan for `score_<id>` (rated), then `na_<id>` (N/A — overrides any
  rated entry for the same criterion if both posted).
- `app/evaluations/helpers.py` — DELETE-then-INSERT semantics in
  `save_evaluation_scores`. Untouched-after-rated naturally removes the
  row; no awkward "delete row if cleared" branching. `get_evaluation_scores`
  now returns the dict-of-dicts shape for tri-state pre-fill.
- `app/templates/evaluations/_section.html` — passes both `prefilled_value`
  and `prefilled_na` to the slider include; section header text changed
  from "X / Y rated" to "X / Y decided" (counts both rated and N/A).
- `app/templates/evaluations/view.html` — renders N/A as a badge:
  "N/A · غير متخصص" with muted styling; numeric scores render as before.
- `app/templates/evaluations/form.html` — section count comment updated
  for new dict-of-dicts shape.

### Verified end-to-end
Synthetic E2E (28/28 PASS) covered:
1. Form HTML carries all 6 new tri-state attributes
2. POST tri-state matrix: 4 rows from rated/rated/N/A/malformed
3. DELETE-then-INSERT — untouched-after-rated removes the row
4. DB CHECK rejects malformed direct inserts (both score+NA and NULL+!NA)
5. Re-open pre-fills 2 dirty + 1 na correctly
6. Submit transitions; view renders N/A badge with EN+AR text
7. All 3 pre-migration evaluations still render 200

Lifecycle invariants verified:
- Backfill: 14 rows, all rated, 0 N/A, 0 invalid
- CHECK enforcement: 4-case matrix (rated, N/A both accept; both
  malformed states reject)

### Verification gaps requiring browser
The synthetic test cannot drive a real browser. The following slider UX
details need an Ali eyes-on pass:
- ✕ button visibility transitions on `dirty` flag (Alpine x-show)
- N/A button highlight toggle
- Slider visual greyout (opacity-60) when na=true
- Drag actually disabled when na=true (HTML5 :disabled on range)
- `reset()` returns slider to centered 5
- `toggleNA()` clearing prior rating correctly

### Known limitation (out of scope)
If a scout marks a slider N/A, then a player's primary position is
changed to one where that criterion no longer applies, the N/A row
stays in `evaluation_scores` but doesn't appear on the form (the form
only renders criteria mapped to the current position group). This is
DB cruft, not a correctness bug. Bundle into 5c-2 cleanup or 5d.

## v0.5.0c1 — Phase 5c-1: Evaluation form (2026-05-09)

### Schema changes
- `players`: 3 admin-set NT-eligibility columns (all nullable)
  - `nationality_status` (CHECK enum: bahraini / foreign_ancestry /
    foreign_residency / not_eligible / unknown)
  - `eligible_from_date` (DATE)
  - `eligibility_notes_admin` (TEXT)
- `evaluations`: new `match_id` column (the spec said "promote existing"
  but the column didn't actually exist on live — see PHASE_5C1_RESULT.md
  for the protocol-driven correction). FK to `matches(id)` `ON DELETE SET
  NULL` so deleting a match preserves the evaluation. New
  `idx_evaluations_match_id` supporting index.

### App
- `app/evaluations/__init__.py` — full blueprint replacing Phase 0 stub:
  - `GET/POST /players/<id>/evaluate` — form / save-draft / submit
  - `GET/POST /evaluations/<id>` — view + update own draft
  - `POST /evaluations/<id>/submit` — explicit submit endpoint
  - `POST /matches/new-inline` — modal-fed match creation, returns JSON
  - Blueprint registered at root (no `url_prefix`) since routes span
    `/players/<id>/evaluate`, `/evaluations/<id>`, `/matches/new-inline`
- `app/evaluations/helpers.py` — pure-DB layer:
  - `get_form_criteria()`, `get_recent_matches()`,
    `get_or_create_draft()`, `get_evaluation()`, `get_evaluation_scores()`,
    `save_evaluation_scores()` (UPSERT, untouched stays unstored),
    `update_evaluation_meta()`, `submit_draft()` (validates required fields),
    `resolve_position_group_for_player()`
- `app/evaluations/forms.py` — input parsing:
  - `parse_score_inputs()` — extracts `score_<criterion_id>` keys, drops
    out-of-range / non-numeric silently
  - `parse_meta_fields()` — whitelisted radio values, safe int casting

### Templates
- `evaluations/form.html` — sticky save/submit bar, match picker, 4
  slider sections (first expanded), NT readiness section, summary,
  submit-confirm modal
- `evaluations/_slider.html` — Alpine `dirty` flag toggles `name`
  attribute so untouched sliders submit no data; pre-fills from saved
  scores on draft reload
- `evaluations/_section.html` — native `<details>` accordion, "X / Y rated"
- `evaluations/_match_picker.html` — dropdown + inline-create modal
  posting to `/matches/new-inline`, prepends new option to select
- `evaluations/_nt_readiness.html` — 5 fields (level + recommendation
  required, eligibility/notes/comparable optional), pre-fills from draft
- `evaluations/_submit_modal.html` — confirm gate before submitting
- `evaluations/view.html` — read-only render with status badge,
  per-section "X / Y rated", NT readiness summary, free-text summary
- `players/edit.html` — admin/TD-only fieldset for `nationality_status`,
  `eligible_from_date`, `eligibility_notes_admin`
- `players/profile.html` — "New Evaluation" button (scout role and above)

### Verified end-to-end
1. Pre-flight: 4/5 gates clean; gate 5 had expected pending state
   documented and proceeded
2. Migration applied: AUDIT PASS — 3 cols on players, match_id + FK +
   index on evaluations
3. Throwaway-namespace replay: 6 invariants confirmed (cols, FK with
   ON DELETE SET NULL, indexes, CHECK enum values, Phase 5b preserved)
4. **Synthetic E2E: 27 / 27 acceptance checks PASS**:
   - GET form returns 200, 42 sliders for AM, 5 sections present
   - Save draft writes evaluation + 5 scores, 37 untouched leave no rows
   - Reopen pre-fills the 5 sliders + NT radios
   - Submit transitions status → submitted, sets submitted_at
   - Inline match modal POST creates manual match
   - Eligibility fieldset visible to admin, hidden from scout
5. **Lifecycle FK invariant**: deleting linked match nulls
   `evaluations.match_id`, evaluation row + status preserved (rollback-
   wrapped to leave live state intact)

### Known notes
- Spec said `evaluations.match_id` already existed; live table didn't
  have it. Migration ADDs the column instead of altering it. Same end
  state. Documented in `PHASE_5C1_RESULT.md`.
- E2E test transiently reset `scout@bfa.bh` password to a temp value
  (`phase5c1-temp-reset-2026-05-09`); admin should rotate via UI when
  reviewing. Documented in `PHASE_5C1_RESULT.md`.

## v0.5.0b — Phase 5b: matches table + Wyscout auto-link (2026-05-09)

### Schema changes
- New table `matches` (15 columns):
  - identity: `match_date`, `home_team`, `away_team` with `UNIQUE`
  - scores, competition, age_group (CHECK senior/u23/u20/u17),
    match_type (CHECK league/cup/friendly/tournament/national_team),
    bfa_team_side (home/away), notes
  - provenance: `source` (CHECK wyscout/manual, defaults to `manual`),
    `created_by` (FK users ON DELETE SET NULL), timestamps
- 4 indexes on `matches`:
  - `idx_matches_lookup` (date + LOWER(BTRIM(home/away))) — case-insensitive
    auto-link
  - `idx_matches_age_group`, `idx_matches_source`, `idx_matches_date`
- `wyscout_match_stats` gains `match_id INTEGER REFERENCES matches(id)
  ON DELETE SET NULL` + `idx_wyscout_match_id`. Nullable; `SET NULL`
  preserves stat history if a match is ever deleted.

### Data
- Backfill linked all 34 existing `wyscout_match_stats` rows
  (Arthur Rezende 18 + Saifaldeen Bouhra 16) to **33 unique matches**.
  The 33 (not 34) is correct: Arthur and Bouhra played opposite teams in
  one shared fixture (Muharraq vs Khalidiya, 2026-01-02), and case-
  insensitive dedup correctly mapped both stat rows to one match row.
- Audit gate inside the migration RAISEd on any drift; AUDIT PASS
  printed before COMMIT.

### Added
- `migrations/phase_5b_matches.sql` — imperative migration with
  pre-flight check (stats == 34, matches table absent), transaction-
  wrapped DDL + backfill, audit gate (matches == 33, linked == 34,
  unlinked == 0), eyeball SELECT.
- `migrations/_generate_phase_5b.py` — generator with thresholds in
  one place; mirrors Phase 5a artifact split.
- `migrations/_dryrun_5b.py` — runs the migration with rollback wrapper.
- `migrations/_apply_5b.py` — runs it for real, COMMITs only on audit pass.
- `migrations/_verify_throwaway_5b.py` — applies updated `schema.sql`
  to an isolated namespace and checks: matches columns, indexes,
  match_id presence, FK ON DELETE SET NULL semantics. Confirms
  declarative schema and live-DB state converge.
- `app/wyscout/ingest.py:_resolve_match_id()` — case-insensitive lookup
  + INSERT ... ON CONFLICT DO UPDATE, called inside the existing
  ingest transaction so matches and stats commit atomically.
- `app/wyscout/__init__.py` — `GET /wyscout/matches` (read-only,
  `@admin_or_td_required`); returns one row per match with
  linked_stats count via `LEFT JOIN COUNT(wyscout_match_stats)`.
- `app/templates/wyscout/matches.html` — table view with source badge
  (BFA gold for `wyscout`, blue for `manual`) and linked-stats count
  (green when > 0).

### Changed
- `schema.sql`:
  - New section "6. MATCHES (Phase 5b)" inserted before WYSCOUT INTEGRATION
    so `wyscout_match_stats.match_id` REFERENCES resolves at fresh-install
    time
  - `wyscout_match_stats` CREATE TABLE updated in place to include the
    `match_id` column declaration (no ALTER statements added)
  - Section numbering bumped: WYSCOUT INTEGRATION → 7, AI ARTIFACTS → 8
- `app/wyscout/ingest.py` — UPSERT vals dict gains `match_id`, populated
  by `_resolve_match_id()` per parsed row before the stat-row UPSERT.
  DO UPDATE clause auto-includes `match_id = EXCLUDED.match_id` because
  it's not part of the conflict key.

### Verified end-to-end
1. Pre-flight: 34 stats, no matches table → passed
2. Migration applied: AUDIT PASS — 33 / 34 / 0
3. Throwaway-namespace replay: schema.sql converges (15 cols on matches,
   FK with ON DELETE SET NULL, all 4 indexes present)
4. Re-upload Arthur's xlsx via real `ingest_wyscout()`:
   `inserted=0, updated=18`, **0 new matches, 0 NULL match_ids,
   0 drifted match_ids** — re-uploads idempotent on matches as well as
   on stats
5. Shared-fixture invariant — `2026-01-02 Muharraq vs Khalidiya`:
   exactly 1 matches row, 2 linked stat rows (Arthur + Bouhra)
6. ON DELETE SET NULL invariant (in rollback wrapper): deleting the
   shared fixture nulls both stat rows' match_id; the stat rows
   themselves survive intact

### Known limitation
The UNIQUE constraint is on raw `(match_date, home_team, away_team)`,
not on the lowered/trimmed values. The auto-link path uses case-
insensitive lookup, so it won't *create* duplicates, but if a manual
match is created with whitespace divergence ("Muharraq " vs "Muharraq")
both rows could persist. Acceptable for v1.

## v0.5.0a — Phase 5a: criteria reseed + NT readiness columns (2026-05-09)

### Schema changes
- `evaluations`: 4 new columns for the National-Team Readiness section
  - `nt_readiness_level VARCHAR(16)` — CHECK in (senior, u23, u20, u17, not_ready)
  - `eligibility_status VARCHAR(32)` — CHECK in (bahraini, foreign_residency,
    foreign_ancestry, foreign_other, not_eligible, unknown)
  - `eligibility_notes TEXT`
  - `comparable_player VARCHAR(255)`
- `evaluations_recommendation_check` rewritten:
  - dropped value: `not_ready` (now lives in `nt_readiness_level`)
  - added value: `not_at_level`

### Data
- `criteria` reseeded from the v2-LOCKED Phase 5 taxonomy: **55 items**
  (Technical 20, Tactical 20, Physical 9, Mentality 6 — trimmed from 12).
  Codes use category prefixes (`tech_*`/`tact_*`/`phys_*`/`ment_*`).
- `position_group_criteria` reseeded: **303 mappings**.
  Per-position form sizes:
  GK 24, CB 42, FB 42, DM 40, CM 37, AM 42, W 38, ST 38.

### Added
- `migrations/phase_5a_reseed.sql` — imperative migration with pre-flight,
  transaction-wrapped reseed + ALTER, and a DO-block audit gate that
  RAISEs if per-position counts don't match the v2 spec (forces ROLLBACK).
- `migrations/_generate_phase_5a.py` — taxonomy → SQL generator; asserts
  per-position counts vs the spec BEFORE emitting any SQL.
- `migrations/_dryrun.py` — runs the migration in a rollback wrapper.
- `migrations/_apply.py` — runs it for real, COMMITs only on audit pass.
- `migrations/_verify_throwaway_db.py` — applies schema.sql to an isolated
  schema and audits, proving the declarative source-of-truth and the
  imperative migration converge.

### Changed
- `schema.sql`:
  - `evaluations` CREATE TABLE definition updated in place to include the
    4 new NT-readiness columns and the new recommendation CHECK values
    (declarative-only, no ALTER statements added)
  - Phase 0 starter criteria seed (39 items) replaced wholesale with the
    Phase 5a taxonomy (55 items)
  - position_group_criteria mapping block replaced to match
  - `v_position_group_form_counts` doc comment updated to reflect the
    new per-position sizes (GK 24 .. CB/FB/AM 42)

### Notes
- Pre-flight verified: `evaluation_scores` was empty and no evaluation
  used the legacy `recommendation = 'not_ready'`, so the reseed didn't
  destroy any user data.
- `Arabic strings` are placeholders — final translations deferred to
  the admin UI in Phase 8.

## v0.4.1 — Phase 4.1: Season aggregations + player comparison (2026-05-09)

### Added
- `app/wyscout/helpers.py` — `season_label_for_date()`: Aug 1 → May 31 football
  season helper, returns `'YYYY/YY'` (accepts `date`, `datetime`, ISO string, or None)
- `app/wyscout/aggregations.py` — three new functions:
  - `get_player_seasons()` — per-season SUMs grouped by `EXTRACT(MONTH/YEAR ...)`
    with NULL-safe pass / duel / aerial / defensive percentages and `goals_plus_assists`
  - `get_player_radar_seasons(player_id, n_seasons=2)` — last N seasons normalized
    via existing `RADAR_THRESHOLDS` / `normalize_radar_axis`; returns
    `[{season_label, season_start_year, matches, total_minutes, scores}]`
  - `compare_players(player_ids)` + `validate_comparison(player_ids)` —
    side-by-side data assembly for 2-3 players with `best_per_metric` highlighting;
    GK + outfield mix is the only cross-position restriction
- `app/players/__init__.py` — three new routes (all `@any_authenticated`):
  - `GET /players/compare` — picker form
  - `GET /players/compare/search` — lightweight HTMX search partial
  - `GET /players/compare/view` — accepts `?ids=1&ids=2` *or* `?ids=1,2,3`,
    flashes ValueError messages and redirects to picker on validation failures
- `app/templates/players/compare.html` — Alpine-driven 3-slot picker with
  HTMX search and live "selected count" feedback; submit disabled until ≥2 picked
- `app/templates/players/_compare_search.html` — HTMX result rows
- `app/templates/players/compare_view.html` — bio header row, career stats grid
  with per-metric max highlighted in BFA green, and an overlapping radar
- `app/static/js/compare.js` — Chart.js radar overlay (3-color palette, BFA red /
  gold / blue) reading from `<canvas data-compare='...'>`
- `app/templates/base.html` — `Compare` link in both desktop nav and the
  mobile dropdown (visible to all authenticated users)
- 3 new Jinja globals: `get_player_seasons`, `get_player_radar_seasons`,
  `season_label_for_date`

### Changed
- `app/templates/players/profile.html` — Career-by-Season table appended to the
  Wyscout dashboard (11-col table: season / Mt / Min / G / A / G+A / xG /
  Ps% / Duel% / Y / R); radar canvas now reads `data-radar-seasons` JSON,
  removed the old `window.BFA.radar` global injection
- `app/static/js/player_dashboard.js` — `initRadar()` rewritten to consume
  `data-radar-seasons`: current season solid (BFA red), prior season dashed
  (BFA gold); legend appears only when ≥2 datasets

### Notes
- No schema changes — `wyscout_match_stats` already had everything needed
- Comparison percentages never divide by zero — `_compare_summary()` uses
  Python guards on the denominator and stores `None` when no data

## v0.3.0 — Phase 4: Wyscout import + player dashboard (2026-05-08)

### Added
- `app/wyscout/parser.py` — `parse_wyscout_xlsx()` with `WYSCOUT_COLUMN_MAP` (50+ header aliases),
  match label regex, date/score/is_home extraction, per-row raw_row JSONB preservation
- `app/wyscout/helpers.py` — `RADAR_AXES`, `RADAR_THRESHOLDS`, `normalize_radar_axis()` for 6-axis radar
- `app/wyscout/ingest.py` — `ingest_wyscout()`: full transaction, UPSERT
  `ON CONFLICT (player_id, match_label, match_date) DO UPDATE`, xmax=0 insert-vs-update detection,
  audit_log entry, failed-import recovery
- `app/wyscout/aggregations.py` — `get_player_summary()`, `get_player_match_history()`,
  `get_player_radar_scores()`, `get_player_trends()` — all direct pool queries
- `app/wyscout/__init__.py` — full blueprint (replaces Phase 0 stub):
  `GET/POST /wyscout/upload/<id>`, `GET /wyscout/result/<id>`,
  `GET /wyscout/imports/<id>`, `POST /wyscout/delete/<id>`, `GET /wyscout/trends/<id>` (JSON API)
- `app/templates/wyscout/upload.html`, `result.html`, `imports.html`
- `app/templates/players/profile.html` — Wyscout placeholder replaced with live dashboard:
  8 summary KPI cards, 6-axis radar, 3 trend line charts (G+A, pass accuracy, duel win%),
  10-row recent match table
- `app/static/js/player_dashboard.js` — Chart.js 4 radar + line chart init with BFA colour tokens
- Chart.js 4.4.2 CDN added to `base.html`
- `age()` Jinja global registered (players.helpers)
- 3 new Jinja globals: `get_wyscout_summary`, `get_player_match_history`, `get_player_radar_scores`

### Changed
- `requirements.txt` — added `pandas>=2.0`, `openpyxl>=3.1`
- `app/players/helpers.py` — added `age()` utility

## v0.2.0 — Phase 3: Players module (2026-05-08)

### Added
- `app/players/__init__.py` — full blueprint replacing Phase 0 stub:
  - `GET /players/` — list with HTMX live search (300ms debounce) + position filter
  - `GET/POST /players/new` — create player + Pillow photo upload
  - `GET /players/<id>` — full profile with Phase 4/5/6 placeholder sections
  - `GET/POST /players/<id>/edit` — edit player + optional photo replace
  - `POST /players/<id>/deactivate` — soft-delete (is_active = FALSE only)
- `app/players/helpers.py` — `get_player_photo()`, `get_player_pos()` as Jinja globals
- `app/players/photos.py` — `save_player_photo()` center-crops to 400x400 JPEG via Pillow
- `app/static/photos/placeholder.svg` — BFA-branded player silhouette fallback
- Templates: `players/list.html`, `players/_grid.html` (HTMX partial), `players/new.html`,
  `players/edit.html`, `players/profile.html`
- `app/static/css/style.css` — `.player-grid`, `.player-card`, `.photo-thumb`,
  `.pos-badge` with per-position-group colour tokens

### Changed
- `requirements.txt` — added `Pillow==10.3.0`
- `app/__init__.py` — registered `get_player_photo` and `get_player_pos` as Jinja globals
- `.gitignore` — added `app/static/photos/*.jpg`
- `PROJECT.md` — Phase 3 marked complete, Phase 4 queued

---

## v0.1.1 — Phase 1 fix (2026-05-08)

### Fixed
- `app/templates/index.html` line 24: `url_for('auth.index')` -> `url_for('auth.login')`
  (auth blueprint has no `index` route; was causing BuildError on landing page)

---

## v0.1.0 — Phase 1: Auth & RBAC (2026-05-08)

### Added
- `app/auth/models.py` — `User(UserMixin)` with `get_by_id`, `get_by_email`, `has_role`; uses pool directly for user-loader compat outside request context
- `app/auth/decorators.py` — `role_required(*roles)` + convenience bundles: `admin_required`, `admin_or_td_required`, `scout_or_above`, `any_authenticated`
- `app/auth/audit.py` — `log_audit()` writing to `audit_log` table; never raises
- `app/auth/__init__.py` — full login/logout/profile/change-password routes; generic error messages; PBKDF2:sha256:600000
- `app/admin/__init__.py` + `app/admin/users.py` — admin user CRUD: list, new, edit, reset-password, deactivate; `is_last_active_admin()` guard on all destructive actions
- `app/__init__.py` — Flask-Login + Flask-WTF CSRFProtect wired; user_loader; admin blueprint registered; first-boot admin seed at startup
- `app/db.py` — `seed_initial_admin()` one-shot seeder from env vars
- Templates: `auth/login.html`, `auth/profile.html`, `admin/users/list.html`, `admin/users/new.html`, `admin/users/edit.html`
- `app/templates/base.html` — top nav now shows user full name, role badge, admin Users link (admin only), Sign out form
- `app/static/css/style.css` — role badge classes + dark-mode form input base styles

### Changed
- All 7 remaining blueprint stubs now have `@login_required` on their stub index route
- `requirements.txt` — added `Flask-WTF==1.2.1`, `email-validator==2.1.0`
- `.env.example` — added `INITIAL_ADMIN_EMAIL`, `INITIAL_ADMIN_PASSWORD`
- `PROJECT.md` — Phase 1 marked complete, Phase 2 queued

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
