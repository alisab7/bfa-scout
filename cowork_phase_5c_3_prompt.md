# Cowork/Claude Code Session: BFA-Scout Phase 5c-3 — UI/UX Polish

## Context

Phase 5c-2.1 is committed (`f1e7c48`). The form story is complete.
Eligibility logic is sound. Profile views are working.

**Phase 5c-3 closes the UI/UX polish gaps before Phase 6 (PDF Player Passport):**
- Free-text fields with high typo risk → structured dropdowns (nationality, club)
- Evaluation deletion workflow (soft-delete with admin recovery)
- Bio richness (match counts + evaluation counts visible at a glance)
- Player card visual density (nationality + flag)
- Date and number input theming consistency

**Working folder:** `D:\BFA-Scout`. Do NOT touch `D:\BFA-Analytics` or `D:\BFA-Analytics-AWS`.

**Local environment:**
- PostgreSQL 15 native, database `bfa_scout`, user `bfa`, password `bfa2025`
- Python venv at `.venv`
- Flask via `flask --app wsgi run --debug`

## Six items, locked scope

| # | Item | Effort estimate |
|---|---|---|
| 1 | Nationality dropdown — full FIFA list (~211 nations), ISO 3166-1 alpha-3 codes, EN labels | 30 min |
| 2 | Clubs dropdown — 24 Bahraini clubs (12 Premier + 12 First Division) + "Other" free-text | 45 min |
| 3 | Date / height / weight input theming fix (CSS) | 10 min |
| 4 | Evaluation soft-delete + admin recovery page | 60 min |
| 5 | Bio additions: Wyscout match count + evaluation count on player header | 20 min |
| 6 | Player card grid: nationality + flag emoji | 15 min |

Plus housekeeping: players list now filterable by nationality + club (since they're structured data).

Total: ~3 hr attended.

## Locked decisions (do not deviate)

| Decision | Choice |
|---|---|
| Nationality storage | ISO 3166-1 alpha-3 in `players.nationality_code` (CHAR(3), nullable) |
| Nationality labels | EN-only. Stored as static Python dict in `app/players/nationalities.py` |
| Nationality dropdown | All 211 FIFA-recognized nations. Sourced from FIFA member list. Stateless and "Other" both omitted (use NULL = unknown) |
| Club storage | FK to new `clubs` table. NULL = "Other / free text" (free-text in `current_club` column survives for non-Bahraini clubs) |
| Club rows | 24 seeded — 12 Premier League + 12 First Division Bahraini clubs (list below) |
| Division tracking | `clubs.division` enum: `'premier'` or `'first'` |
| Soft-delete columns | `evaluations.deleted_at` TIMESTAMPTZ NULL, `deleted_by` FK users, `deleted_reason` TEXT NOT NULL when deleted_at set |
| Soft-delete permissions | Scout: own drafts only. Admin/TD: any non-locked evaluation. Locked = nobody can delete (must unlock first). |
| Soft-delete reason text | Min 10 chars, audit-logged |
| Soft-delete filter invariant | EVERY query for evaluations in user-facing code MUST include `WHERE deleted_at IS NULL` (only exception: admin recovery page) |
| Recovery page | `/admin/deleted-evaluations` — admin only, lists soft-deleted, allows restore |
| Bio match count | Count from `wyscout_match_stats` for the player |
| Bio evaluation count | Count from `evaluations WHERE deleted_at IS NULL` for the player |
| Card nationality display | `🇧🇭 BHR` style (flag emoji from ISO code via emoji-flag mapping) |
| Players list filters | Existing search + position + eligibility, plus new: nationality dropdown + club dropdown |

## Pre-flight gates

```powershell
# Gate 1: 5c-2.1 committed
git log --oneline | Select-String "5c-2.1"
# expect: at least one commit

# Gate 2: clean working tree
git status
# expect: nothing to commit

# Gate 3: 14 evaluation_scores rows persist
psql -U bfa -d bfa_scout -c "SELECT COUNT(*) FROM evaluation_scores;"
# expect: 14 (or more if you've created drafts since)

# Gate 4: 3 submitted evaluations persist
psql -U bfa -d bfa_scout -c "SELECT COUNT(*) FROM evaluations WHERE status = 'submitted';"
# expect: 3 (or more)

# Gate 5: clubs table doesn't exist yet
psql -U bfa -d bfa_scout -c "SELECT to_regclass('public.clubs');"
# expect: NULL

# Gate 6: nationality_code column doesn't exist yet
psql -U bfa -d bfa_scout -c "\d players" | Select-String "nationality_code"
# expect: empty
```

## Bahraini clubs to seed (24 total)

### Premier League (Nasser bin Hamad) — 12 clubs

```python
PREMIER_LEAGUE_CLUBS = [
    'Al-Muharraq',
    'Al-Khalidiya',
    'Al-Hidd',
    'Malkiya Club',
    'Al-Riffa',
    "A'Ali FC",
    'Sitra Club',
    'Al-Budaiya',
    'Al-Shabab Manama',
    'Al-Najma',
    'Al-Ahli Manama',
    'Al-Bahrain SC',
]
```

### First Division League — 12 clubs

```python
FIRST_DIVISION_CLUBS = [
    'Al-Ittifaq',
    'East Riffa',
    'Manama Club',
    'Al-Ettihad',
    'Al-Hala',
    'Um Alhassam',
    'Bouri',
    'Busaiteen',
    'Isa Town',
    'Etehad Alreef',
    'Al-Tadhamun',
    'Galali',
]
```

## FIFA nationality list

Use the standard ISO 3166-1 alpha-3 codes. Generator script must produce a verified list of all 211 FIFA member nations. Recommend pulling from a reliable Python package or a verified static list — DO NOT hand-type 211 entries (typo risk). Options:

1. **`pycountry` package** (preferred) — `pip install pycountry`, then iterate `pycountry.countries` and filter to FIFA members. ~250 ISO 3166-1 entries (close enough; FIFA's 211 differs from ISO by edge cases like Vatican/Palestine; use ISO list as superset).

2. **Static dict in `app/players/nationalities.py`** — generated once via pycountry at build time, then committed as a frozen dict. Safer (no runtime dep on pycountry), reproducible.

Use option 2: at build time, run `pycountry` to produce the static dict; commit the dict; remove pycountry as runtime dependency.

Display order in dropdown: alphabetical by EN label, with **Bahrain first** (since it's a Bahraini-focused platform — BFA staff will type "B" first usually).

```python
# app/players/nationalities.py
NATIONALITY_CHOICES = [
    ('BHR', 'Bahrain'),  # always first
    # then alphabetical:
    ('AFG', 'Afghanistan'),
    ('ALB', 'Albania'),
    # ... ~210 more entries
    ('ZWE', 'Zimbabwe'),
]

NATIONALITY_LABEL = dict(NATIONALITY_CHOICES)
```

## Files to create / modify

```
migrations/
├── _generate_phase_5c3.py            [NEW] Generator (clubs INSERTs, schema additions)
├── phase_5c3_clubs_and_softdelete.sql [NEW] Migration artifact
├── _dryrun_5c3.py                    [NEW] Savepoint+rollback verify-without-apply
└── _verify_throwaway_5c3.py          [NEW] schema.sql convergence test

schema.sql                             [MODIFY] In-place CREATE edits — no ALTERs:
                                                 - players: add nationality_code, club_id
                                                 - evaluations: add deleted_at, deleted_by, deleted_reason
                                                 - new clubs table CREATE

app/players/
├── __init__.py                        [MODIFY] _search_players supports nat/club filters; edit handler reads new fields
├── nationalities.py                   [NEW] Static FIFA ISO list + helper functions
└── clubs.py                           [NEW] get_clubs_grouped(), get_club_label()

app/evaluations/
├── __init__.py                        [MODIFY] Soft-delete routes (POST /evaluations/<id>/delete; admin recovery routes)
├── helpers.py                         [MODIFY] All read queries filter WHERE deleted_at IS NULL by default; add include_deleted=False kwarg
└── forms.py                           [MODIFY] Validation for deletion reason text

app/admin/                             [NEW DIRECTORY]
└── __init__.py                        [NEW] Blueprint with /admin/deleted-evaluations (admin-only)

app/templates/
├── players/
│   ├── _grid.html                     [MODIFY] Add nationality + flag per card
│   ├── edit.html                      [MODIFY] Replace nationality input with select; replace current_club input with select+other; date/number theming
│   ├── profile.html                   [MODIFY] Bio: add match count + evaluation count
│   └── list.html                      [MODIFY] Add nat + club filter dropdowns
├── evaluations/
│   ├── _history_card.html             [MODIFY] Add delete button (role-gated, confirms with reason)
│   ├── _delete_modal.html             [NEW] Confirm modal with reason input
│   ├── view.html                      [MODIFY] Show deleted state to admin (link to recovery)
│   └── _eligibility_card.html         [MODIFY only if needed]
└── admin/                              [NEW DIRECTORY]
    └── deleted_evaluations.html        [NEW] Recovery page

app/static/css/
└── style.css                          [MODIFY] Date/number input theming

CHANGELOG.md                           [APPEND] v0.5.0c3 entry
PROJECT.md                             [UPDATE] Mark 5c-3 complete
```

## Schema changes

```sql
-- 1. New clubs table
CREATE TABLE IF NOT EXISTS clubs (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(128) NOT NULL,
    division    VARCHAR(16) NOT NULL
                CHECK (division IN ('premier', 'first')),
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (name, division)
);
CREATE INDEX IF NOT EXISTS idx_clubs_division ON clubs(division);
CREATE INDEX IF NOT EXISTS idx_clubs_active   ON clubs(is_active);

-- 2. Players nationality + club
ALTER TABLE players
    ADD COLUMN nationality_code CHAR(3),
    ADD COLUMN club_id INTEGER REFERENCES clubs(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_players_nationality ON players(nationality_code);
CREATE INDEX IF NOT EXISTS idx_players_club_id     ON players(club_id);

-- 3. Evaluations soft-delete
ALTER TABLE evaluations
    ADD COLUMN deleted_at      TIMESTAMPTZ,
    ADD COLUMN deleted_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN deleted_reason  TEXT,
    ADD CONSTRAINT evaluations_soft_delete_consistency
        CHECK (
            (deleted_at IS NULL  AND deleted_by IS NULL  AND deleted_reason IS NULL) OR
            (deleted_at IS NOT NULL AND deleted_by IS NOT NULL AND deleted_reason IS NOT NULL AND char_length(deleted_reason) >= 10)
        );

CREATE INDEX IF NOT EXISTS idx_evaluations_deleted_at ON evaluations(deleted_at);

-- 4. Seed 24 clubs
INSERT INTO clubs (name, division) VALUES
    ('Al-Muharraq', 'premier'),
    ('Al-Khalidiya', 'premier'),
    ('Al-Hidd', 'premier'),
    ('Malkiya Club', 'premier'),
    ('Al-Riffa', 'premier'),
    ('A''Ali FC', 'premier'),
    ('Sitra Club', 'premier'),
    ('Al-Budaiya', 'premier'),
    ('Al-Shabab Manama', 'premier'),
    ('Al-Najma', 'premier'),
    ('Al-Ahli Manama', 'premier'),
    ('Al-Bahrain SC', 'premier'),
    ('Al-Ittifaq', 'first'),
    ('East Riffa', 'first'),
    ('Manama Club', 'first'),
    ('Al-Ettihad', 'first'),
    ('Al-Hala', 'first'),
    ('Um Alhassam', 'first'),
    ('Bouri', 'first'),
    ('Busaiteen', 'first'),
    ('Isa Town', 'first'),
    ('Etehad Alreef', 'first'),
    ('Al-Tadhamun', 'first'),
    ('Galali', 'first');

-- 5. Backfill existing players' club_id from current_club text where it matches a known club
UPDATE players SET club_id = c.id
FROM clubs c
WHERE LOWER(BTRIM(players.current_club)) = LOWER(BTRIM(c.name))
   OR LOWER(BTRIM(players.current_club)) = LOWER(BTRIM(c.name)) || ' club'
   OR REPLACE(LOWER(BTRIM(players.current_club)), 'al-', 'al ') = REPLACE(LOWER(BTRIM(c.name)), 'al-', 'al ');
```

The backfill is best-effort. Arthur's "Muharraq Club" should match "Al-Muharraq" via the variations. Bouhra's "Khalidiya" should match "Al-Khalidiya". For any non-match, `club_id` stays NULL (which renders as "Other / free-text" — `current_club` text is preserved either way).

**Audit gate inside transaction:**
```sql
DO $$
DECLARE
    clubs_count INTEGER;
    backfilled_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO clubs_count FROM clubs;
    IF clubs_count != 24 THEN
        RAISE EXCEPTION 'AUDIT FAIL — expected 24 clubs, got %', clubs_count;
    END IF;

    SELECT COUNT(*) INTO backfilled_count FROM players WHERE club_id IS NOT NULL;
    -- Expect at least 2 backfilled (Arthur + Bouhra) but tolerate 0 if naming diverges
    RAISE NOTICE 'AUDIT PASS — % clubs seeded, % players auto-linked to clubs', clubs_count, backfilled_count;
END $$;
```

## Soft-delete invariant — CRITICAL

EVERY existing query in `app/evaluations/helpers.py` and `app/players/__init__.py` that reads `evaluations` MUST be updated to filter `WHERE deleted_at IS NULL`.

Specifically:

| Function | Where | Action |
|---|---|---|
| `get_player_evaluations` | helpers.py | Add `AND e.deleted_at IS NULL` to the WHERE clause |
| `nt_readiness_summary` | helpers.py | Add `AND deleted_at IS NULL` to the inner query |
| Any other helper that SELECTs from evaluations | helpers.py | Add the filter |
| Bio evaluation_count query | new — see Item 5 | Filter from the start |

**Add a docstring comment to each function:** `# DOES NOT include soft-deleted evaluations` so future developers don't accidentally bypass the filter.

The exception is the recovery page route — it explicitly looks at `WHERE deleted_at IS NOT NULL`. Document this explicitly in the route's docstring.

## Item 1 — Nationality dropdown

Edit `app/templates/players/edit.html` to replace the existing nationality input:

```html
<!-- Was: <input type="text" name="nationality" ...> -->
<label class="block text-sm font-medium mb-1">Nationality</label>
<select name="nationality_code" class="w-full px-3 py-2 rounded text-sm"
        style="background:var(--bg);border:1px solid var(--border);color:var(--text);">
  <option value="">— Select nationality —</option>
  {% for code, label in NATIONALITY_CHOICES %}
    <option value="{{ code }}" {% if player.nationality_code == code %}selected{% endif %}>
      {{ label }}
    </option>
  {% endfor %}
</select>
```

Register `NATIONALITY_CHOICES` as a Jinja global in `app/__init__.py`.

In the `/players/<id>/edit` POST handler, read `nationality_code`, validate it's in the dict (defense against arbitrary values), UPDATE the players row.

## Item 2 — Clubs dropdown + "Other" escape

Edit `app/templates/players/edit.html`:

```html
<label class="block text-sm font-medium mb-1">Current Club</label>
<select name="club_id" id="club_id_select"
        x-data="{ showOther: {{ 'true' if not player.club_id and player.current_club else 'false' }} }"
        @change="showOther = $event.target.value === 'other'"
        class="w-full px-3 py-2 rounded text-sm mb-2"
        style="background:var(--bg);border:1px solid var(--border);color:var(--text);">
  <option value="">— Select club —</option>
  <optgroup label="Premier League">
    {% for club in clubs_premier %}
      <option value="{{ club.id }}" {% if player.club_id == club.id %}selected{% endif %}>
        {{ club.name }}
      </option>
    {% endfor %}
  </optgroup>
  <optgroup label="First Division">
    {% for club in clubs_first %}
      <option value="{{ club.id }}" {% if player.club_id == club.id %}selected{% endif %}>
        {{ club.name }}
      </option>
    {% endfor %}
  </optgroup>
  <option value="other" {% if not player.club_id and player.current_club %}selected{% endif %}>
    Other (free text)
  </option>
</select>

<input type="text" name="current_club_other"
       x-show="showOther" x-cloak
       value="{{ player.current_club if not player.club_id else '' }}"
       placeholder="Enter club name"
       class="w-full px-3 py-2 rounded text-sm"
       style="background:var(--bg);border:1px solid var(--border);color:var(--text);">
```

POST handler logic:
- If `club_id` is a numeric string → SET `players.club_id = <int>` and `current_club = (SELECT name FROM clubs WHERE id = <int>)` (denormalized cache, so existing code that reads `current_club` keeps working without join)
- If `club_id == 'other'` → SET `players.club_id = NULL` and `current_club = <current_club_other text>`
- If `club_id == ''` → SET `players.club_id = NULL` and `current_club = NULL`

The `current_club` text column is kept as a denormalized cache — so existing template/code that uses `player.current_club` keeps working. The new `club_id` is the structured FK source of truth for filtering and validation.

## Item 3 — Date/height/weight input theming

In `app/static/css/style.css`, find any existing input styling. Add overrides:

```css
input[type="date"],
input[type="number"],
input[type="time"] {
  background-color: var(--bg) !important;
  color: var(--text) !important;
  border: 1px solid var(--border);
  padding: 0.5rem 0.75rem;
  border-radius: 0.375rem;
  -webkit-appearance: none;
  appearance: none;
}

/* Native picker icons in date inputs (calendar icon) on dark theme */
input[type="date"]::-webkit-calendar-picker-indicator {
  filter: invert(1) opacity(0.6);
  cursor: pointer;
}
```

Browser-test in Chrome and Firefox after applying.

## Item 4 — Soft-delete + recovery

### Routes (in `app/evaluations/__init__.py`)

```python
@bp.route('/evaluations/<int:eval_id>/delete', methods=['POST'])
@login_required
def delete_evaluation(eval_id):
    """Soft-delete. Permission rules:
      - Scout: can delete own draft evaluations only
      - Admin/TD: can delete any evaluation EXCEPT locked ones
      - Locked evaluations cannot be deleted (must unlock first)
    Reason text required, min 10 chars.
    """
    reason = request.form.get('reason', '').strip()
    if len(reason) < 10:
        flash('Reason must be at least 10 characters', 'error')
        return redirect(url_for('players.profile', player_id=...))

    # Look up the evaluation
    # Check permission per the rules above
    # If allowed: UPDATE evaluations SET deleted_at=NOW(), deleted_by=current_user.id, deleted_reason=reason
    # Audit-log: action='evaluation.deleted'

@bp.route('/evaluations/<int:eval_id>/restore', methods=['POST'])
@admin_or_td_required
def restore_evaluation(eval_id):
    """Restore soft-deleted evaluation. Admin/TD only."""
    # UPDATE evaluations SET deleted_at=NULL, deleted_by=NULL, deleted_reason=NULL
    # Audit-log: action='evaluation.restored'
```

### Admin recovery page — new blueprint `app/admin/__init__.py`

```python
from flask import Blueprint, render_template
from app.auth import admin_required

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

@admin_bp.route('/deleted-evaluations')
@admin_required
def deleted_evaluations():
    """List all soft-deleted evaluations across the system.
    Pure recovery view. No edit, no submit, just restore button per row.
    """
    # SELECT all evaluations WHERE deleted_at IS NOT NULL
    # JOIN to users to show evaluator + deleted_by names
    # JOIN to players to show player name + photo
    # Order by deleted_at DESC
```

Register this blueprint in `app/__init__.py`.

### Template — `_history_card.html` add delete button (role-gated)

Inside the existing card actions section:

```html
{% if not ev.locked_at and (
     (ev.status == 'draft' and ev.evaluator_id == current_user.id) or
     current_user.has_role('admin', 'technical_director')
   ) %}
  <button type="button"
          @click="deleteModal = true"
          class="text-xs underline"
          style="color:var(--text-muted);">Delete</button>
{% endif %}
```

### Template — `_delete_modal.html` (new)

```html
<div x-show="deleteModal" x-cloak class="fixed inset-0 z-50 ...">
  <div class="rounded-xl p-6 max-w-md w-full" style="background:var(--surface);">
    <h3 class="font-bold mb-3">Delete this evaluation?</h3>
    <p class="text-sm mb-4" style="color:var(--text-muted);">
      The evaluation will be hidden from all views. Admin can restore it later.
    </p>
    <form method="POST" action="{{ url_for('evaluations.delete_evaluation', eval_id=ev.id) }}">
      <label class="block text-sm font-medium mb-1">Reason for deletion *</label>
      <textarea name="reason" required minlength="10" rows="3"
                placeholder="Why are you deleting this? (min 10 chars)"
                class="w-full px-3 py-2 rounded text-sm mb-3"
                style="background:var(--bg);border:1px solid var(--border);color:var(--text);"></textarea>
      <div class="flex justify-end gap-2">
        <button type="button" @click="deleteModal = false" class="px-3 py-1 text-sm">Cancel</button>
        <button type="submit" class="px-3 py-1 rounded text-sm font-semibold text-white"
                style="background:var(--brand);">Delete</button>
      </div>
    </form>
  </div>
</div>
```

Include this in `_history_card.html`. The Alpine `deleteModal` flag scoped per-card.

## Item 5 — Bio additions on player header

Update `players/profile.html` header strip to query and display:

```python
# In the route handler
match_count = db_query_scalar("""
    SELECT COUNT(*) FROM wyscout_match_stats WHERE player_id = %s
""", (player_id,))

evaluation_count = db_query_scalar("""
    SELECT COUNT(*) FROM evaluations
    WHERE player_id = %s AND deleted_at IS NULL
""", (player_id,))
```

Pass to template, render in the header strip:

```html
<div class="flex gap-4 mt-2 text-xs" style="color:var(--text-muted);">
  <span>📊 {{ match_count }} Wyscout match{{ '' if match_count == 1 else 'es' }}</span>
  <span>📝 {{ evaluation_count }} evaluation{{ '' if evaluation_count == 1 else 's' }}</span>
</div>
```

## Item 6 — Player card grid: nationality + flag

In `_grid.html`, find where existing player info renders. Add:

```html
{% if p.nationality_code %}
  <span class="text-xs ml-2" style="color:var(--text-muted);">
    {{ flag_emoji(p.nationality_code) }} {{ p.nationality_code }}
  </span>
{% endif %}
```

Helper function `flag_emoji(iso_code)` — converts a 3-letter ISO code to flag emoji. Implementation: ISO 3166-1 alpha-3 → alpha-2 mapping (built-in via pycountry at build time, frozen as static dict), then alpha-2 → flag emoji via Unicode regional indicator characters:

```python
def flag_emoji(alpha3_code: str) -> str:
    """Convert ISO 3166-1 alpha-3 country code to flag emoji string."""
    if not alpha3_code or len(alpha3_code) != 3:
        return ''
    alpha2 = ALPHA3_TO_ALPHA2.get(alpha3_code.upper())
    if not alpha2 or len(alpha2) != 2:
        return ''
    # Each letter to regional indicator: A=0x1F1E6, etc.
    return chr(0x1F1E6 + ord(alpha2[0]) - ord('A')) + chr(0x1F1E6 + ord(alpha2[1]) - ord('A'))
```

Bake `ALPHA3_TO_ALPHA2` into the static `nationalities.py` file alongside `NATIONALITY_CHOICES`.

Register `flag_emoji` as a Jinja global.

## Players list filters update

`/players/` currently has search + position + eligibility filter (from 5c-2.1). Add two more dropdowns:

```html
<select name="nat" class="px-3 py-2 rounded text-sm">
  <option value="">All nationalities</option>
  {% for code, label in NATIONALITY_CHOICES %}
    <option value="{{ code }}" {% if request.args.get('nat') == code %}selected{% endif %}>
      {{ label }}
    </option>
  {% endfor %}
</select>

<select name="club" class="px-3 py-2 rounded text-sm">
  <option value="">All clubs</option>
  <optgroup label="Premier League">
    {% for c in clubs_premier %}
      <option value="{{ c.id }}" {% if request.args.get('club') == c.id|string %}selected{% endif %}>
        {{ c.name }}
      </option>
    {% endfor %}
  </optgroup>
  <optgroup label="First Division">
    {% for c in clubs_first %}
      <option value="{{ c.id }}" {% if request.args.get('club') == c.id|string %}selected{% endif %}>
        {{ c.name }}
      </option>
    {% endfor %}
  </optgroup>
</select>
```

In `_search_players`, add:

```python
if nat_filter:
    where_clauses.append("pl.nationality_code = %s")
    params.append(nat_filter)

if club_filter:
    if club_filter == 'other':
        where_clauses.append("pl.club_id IS NULL")
    else:
        where_clauses.append("pl.club_id = %s")
        params.append(int(club_filter))
```

## Verification protocol

After all code:

1. **Generate SQL** via `_generate_phase_5c3.py`
2. **Dry-run** via `_dryrun_5c3.py` — savepoint+rollback
3. **Apply** migration; confirm AUDIT PASS
4. **Update schema.sql** declaratively (no ALTERs)
5. **Throwaway-namespace verify** — schema.sql → fresh schema → same final state
6. **Restart Flask**; run synthetic E2E:
   - GET `/players/2/edit` → Nationality dropdown shows 211 entries with Bahrain at top, Club dropdown shows 2 optgroups (Premier League / First Division), date/number inputs visually consistent with theme
   - POST update Arthur's nationality_code = 'BRA', club_id = 1 (Al-Muharraq), save
   - GET `/players/2` → Bio shows "📊 18 Wyscout matches" and "📝 3 evaluations"
   - GET `/players/` → Arthur's card shows 🇧🇷 BRA; filter by Nationality=Brazil → only Arthur shows
   - Filter by Club=Al-Muharraq → only Arthur shows
   - As scout, draft an evaluation, click Delete with reason "test deletion of own draft" → DB shows deleted_at set
   - As scout, attempt to delete a SUBMITTED evaluation → forbidden (button not visible OR 403 if URL hit)
   - As admin, delete a submitted evaluation with reason "spot-checking soft-delete admin path" → succeeds
   - GET `/admin/deleted-evaluations` as admin → both deleted evaluations visible
   - Click Restore on one → UPDATE clears deleted_at; original card re-appears on profile
   - GET `/admin/deleted-evaluations` as scout → 403
   - Try to delete a LOCKED evaluation → forbidden (button not visible)
   - GET `/players/2` after deletion → evaluation_count drops by 1; deleted card hidden from history
7. **DB lifecycle verification:**
   ```powershell
   psql -U bfa -d bfa_scout -c "
     SELECT id, status,
            CASE WHEN deleted_at IS NULL THEN 'active' ELSE 'deleted' END AS state,
            deleted_reason
     FROM evaluations
     ORDER BY id;
   "
   ```
   All deleted rows have all 3 deleted_* columns set, all active have all 3 NULL.

## Acceptance criteria

- ✅ Pre-flight gates pass (6)
- ✅ Migration AUDIT PASS, throwaway-namespace verify PASS
- ✅ 24 clubs seeded, 12+12 split correctly by division
- ✅ Backfill linked existing players (Arthur, Bouhra) to clubs (or NULL if names diverge)
- ✅ Nationality dropdown shows 211 entries, Bahrain first, then alphabetical
- ✅ Editing player nationality persists; reading shows correct EN label
- ✅ Club dropdown shows Premier + First Division optgroups; Other free-text path works
- ✅ Date/number inputs visible against dark theme
- ✅ Bio shows match count + evaluation count, both filter deleted_at IS NULL correctly
- ✅ Card grid shows 🇧🇷 BRA-style nationality+flag
- ✅ Players list filterable by nationality (correct results)
- ✅ Players list filterable by club (correct results)
- ✅ Scout can delete own draft, with reason text required
- ✅ Scout cannot delete submitted evaluations
- ✅ Scout cannot delete other scouts' evaluations
- ✅ Admin can delete any non-locked evaluation
- ✅ Locked evaluations cannot be deleted (button hidden, route returns 403)
- ✅ Reason text < 10 chars rejected
- ✅ Recovery page admin-only (403 for scout)
- ✅ Restore from recovery page works
- ✅ All other read queries (history, summary, eligibility) hide deleted evaluations
- ✅ schema.sql updated declaratively, no ALTERs added

## Hard rules

- ❌ Do NOT modify auth, criteria taxonomy, wyscout/parser, wyscout/ingest
- ❌ Do NOT alter the slider component, lock workflow, eligibility logic from prior phases
- ❌ Do NOT use flask.test_client() for verification — restart real Flask
- ❌ Do NOT initialize git or commit — Ali commits manually
- ❌ Do NOT touch `D:\BFA-Analytics` or `D:\BFA-Analytics-AWS`
- ❌ Do NOT add ALTER statements to schema.sql — declarative-only
- ❌ Do NOT skip the deleted_at IS NULL filter on any evaluation read query (it's an invariant)
- ❌ Do NOT hand-type 211 nationality entries (use pycountry to generate)
- ❌ Do NOT change the 24 club names or divisions in the seed (verbatim from spec)
- ✅ Wrap migration in transaction with audit gate
- ✅ Pre-flight gate aborts on unexpected state
- ✅ Generator → migration → dry-run → apply → schema.sql → throwaway-namespace pattern
- ✅ Every state-changing route audit-logged
- ✅ Append v0.5.0c3 entry to CHANGELOG.md
- ✅ Update PROJECT.md to mark 5c-3 complete, queue 5d

## Out of scope (do NOT build)

- Comparison page scout dimension (Phase 5d — designed against real evaluation data)
- Player Passport PDF (Phase 6)
- Auto-translation of nationality names to Arabic
- Adding clubs through UI (admin manages via DB; future feature)
- Bulk operations
- Tracking history of player club moves (out of scope; just show current_club)

## Session discipline

- Target: 6–8 messages
- After every code change: restart Flask + browser-or-curl verify
- Verify all 22 acceptance criteria explicitly
- After session, Ali commits:
  ```powershell
  cd D:\BFA-Scout
  git add -A
  git commit -m "Phase 5c-3: Nationality dropdown, clubs dropdown, soft-delete evaluations, bio counts, card nationality, input theming"
  ```
