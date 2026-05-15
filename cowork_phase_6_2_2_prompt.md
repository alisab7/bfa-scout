# Cowork/Claude Code Session: BFA-Scout Phase 6.2.2 — Bundled Polish (3 Items)

## Context

BFA board meeting (May 12) surfaced three items that bundle naturally as a single polish patch — all relate to data integrity and display correctness. Phase 7 (NT role + scout restriction) and Phase 9 (bulk player import) follow separately.

**Working folder:** `D:\BFA-Scout`. Phase 6.2.1 must be committed first.

## Three items in this patch

| # | Item | Effort | Risk |
|---|---|---|---|
| 1 | Age at eligibility — display "Age at eligibility: 23" line below residency-since in profile card + passport PDF | 30 min | Low — additive |
| 2 | Bahraini status fix — when `nationality_status='bahraini'`, eligibility must show ✅ Eligible (citizen) + Bahrain flag, NOT pending/unknown | 15 min | Low — single conditional |
| 3 | Wyscout accumulation audit — verify re-upload behavior is upsert (not overlap, not duplicate); fix if broken | 30-45 min | Medium — may require backfill |

Total ~1.5hr.

## Pre-flight gates

```powershell
git log --oneline | Select-Object -First 1   # expect: Phase 6.2.1 at top
git status                                    # expect: clean

# Diagnostic for Item 2 — how many players currently have bahraini status?
psql -U bfa -d bfa_scout -c "SELECT id, full_name, nationality_status, nationality_code FROM players WHERE nationality_status = 'bahraini';"

# Diagnostic for Item 3 — duplicate detection on Wyscout
psql -U bfa -d bfa_scout -c "SELECT player_id, COUNT(*) AS total_rows, COUNT(DISTINCT match_date) AS distinct_dates FROM wyscout_match_stats GROUP BY player_id HAVING COUNT(*) > COUNT(DISTINCT match_date);"
# expect: empty result. If any rows return, that's the bug.
```

## Item 1 — Age at eligibility

### Locked decisions

| Decision | Choice |
|---|---|
| Display style | Option C — separate line below residency-since: **"Age at eligibility: 23"** |
| Show when | Player has DOB + future eligible date + foreign-residency status |
| Hide when | Already eligible / no DOB / non-foreign-residency / unknown / not_eligible / bahraini / foreign_ancestry |
| Calculation | Age in full years at the eligible_from_date (or derived residency+5y date) |
| Locations | Profile eligibility card + passport PDF eligibility section |
| Arabic translation | Not in this patch |

### Helper — `app/players/eligibility.py`

```python
from datetime import date

def age_at_eligibility(player: dict) -> int | None:
    """Returns the player's age (in full years) at their eligibility date.
    Returns None if:
    - Not foreign_residency
    - No DOB
    - No future eligible date (already eligible or no date)
    """
    if player.get('nationality_status') != 'foreign_residency':
        return None
    dob = player.get('dob')
    if not dob:
        return None

    elig_date = _resolve_eligibility_date(player)
    if not elig_date:
        return None

    today = date.today()
    if elig_date <= today:
        return None  # Already eligible — don't display

    years = elig_date.year - dob.year
    if (elig_date.month, elig_date.day) < (dob.month, dob.day):
        years -= 1
    return years


def _resolve_eligibility_date(player: dict) -> date | None:
    """Returns explicit eligible_from_date if set; otherwise derives
    from bahrain_residency_start_date + 5y (FIFA Article 5 default)."""
    if player.get('eligible_from_date'):
        return player['eligible_from_date']
    start = player.get('bahrain_residency_start_date')
    if start:
        return date(start.year + 5, start.month, start.day)
    return None
```

If `_resolve_eligibility_date` already exists in the eligibility module, reuse it — don't duplicate.

### Template — profile eligibility card

`app/templates/evaluations/_eligibility_card.html`:

Add directly after the residency-since line:

```html
{% if eligibility.age_at_eligibility %}
  <p class="elig-note">Age at eligibility: {{ eligibility.age_at_eligibility }}</p>
{% endif %}
```

### Template — passport PDF

`app/templates/passport/passport.html`:

Add directly after the residency-since line in the eligibility section:

```html
{% if eligibility.age_at_eligibility %}
  <p class="elig-age">Age at eligibility: {{ eligibility.age_at_eligibility }}</p>
{% endif %}
```

CSS in `_passport.css`:

```css
.elig-age {
    font-size: 10pt;
    color: #444;
    margin: 2pt 0 0 0;
}
```

### Data flow

Both `compute_eligibility_status()` (profile) and `_build_passport_eligibility()` (PDF) need to include the `age_at_eligibility` field in their returned dicts. Single helper, two consumers.

## Item 2 — Bahraini status displays as eligible immediately

### The bug

When admin sets `nationality_status='bahraini'`, the eligibility card should show:
- ✅ Eligible (Bahraini citizen)
- Bahrain flag inline

Today this may render as "Status unknown" or pending state if other date fields aren't set. Bahraini citizens don't have eligibility dates — citizenship is immediate.

### Diagnose first

Check `app/players/eligibility.py` — find the function (likely `compute_eligibility_status`). Trace the conditional flow:

```python
def compute_eligibility_status(player):
    # What's the priority order?
    if player['nationality_status'] == 'not_eligible':
        return {...not eligible...}
    if player['nationality_status'] == 'bahraini':
        return {
            'icon': '✅',
            'label': 'Eligible (Bahraini citizen)',
            'is_eligible_now': True,
            'show_flag': True,
        }
    # ... etc.
```

If the bahraini branch already exists and correctly returns immediate-eligible, the issue is template-side OR the order of conditions is wrong (e.g., a more general branch matches first).

If the bahraini branch is missing or returns the wrong values, that's the fix.

### Fix

Ensure the `bahraini` branch returns:
- `icon: '✅'`
- `label: 'Eligible now'` or `'Eligible (Bahraini citizen)'` (consistent with other "eligible now" rendering)
- `is_eligible_now: True`
- Any flag-related field needed for the Bahrain flag SVG to render

Verify the same branch covers `foreign_ancestry` — these players are also immediately eligible (no date logic needed).

### Template check

The eligibility card template should render the Bahrain flag SVG inline next to the label. The flag-SVG helper already exists (`_flag_svg_inline()` from Phase 6.1). If the bahraini branch doesn't pass `nationality_code='BHR'` through, the flag won't render.

```html
{% if eligibility.is_eligible_now %}
  <div class="elig-label">
    <span class="elig-icon">{{ eligibility.icon }}</span>
    {{ eligibility.label }}
    {% if player.nationality_code %}
      <span class="flag-inline">{{ get_flag_svg(player.nationality_code) | safe }}</span>
    {% endif %}
  </div>
{% endif %}
```

For a Bahraini citizen, this shows: ✅ Eligible (Bahraini citizen) [Bahrain flag SVG]

### Test

Create a test player (or modify an existing one) to `nationality_status='bahraini', nationality_code='BHR'`. Verify:
- Profile eligibility card shows ✅ + flag + "Eligible (Bahraini citizen)"
- No "Status unknown", no "Eligible from", no residency-since, no age-at-eligibility lines

Restore the original state after testing.

## Item 3 — Wyscout accumulation audit

### Verify upsert behavior

The Wyscout ingest in `app/wyscout/ingest.py` uses `ON CONFLICT (player_id, match_date) DO UPDATE`. This SHOULD mean:

- Re-uploading same xlsx → existing rows refreshed, 0 inserts
- Uploading xlsx with new matches → new rows added, prior rows preserved
- Mixed → old refreshed, new added

### Diagnostic queries (run BEFORE any code change)

```sql
-- 1. Total row counts vs distinct (player_id, match_date) — should match
SELECT
    COUNT(*) AS total_rows,
    COUNT(DISTINCT (player_id, match_date)) AS distinct_combos
FROM wyscout_match_stats;
-- Pass: total_rows == distinct_combos
-- Fail: total_rows > distinct_combos (duplicate rows = bug)

-- 2. Per-player duplicate check
SELECT
    player_id,
    COUNT(*) AS total,
    COUNT(DISTINCT match_date) AS distinct_dates
FROM wyscout_match_stats
GROUP BY player_id
HAVING COUNT(*) > COUNT(DISTINCT match_date);
-- Pass: empty result
-- Fail: any row indicates duplicates for that player

-- 3. Confirm uniqueness constraint exists
\d wyscout_match_stats
-- Pass: UNIQUE constraint on (player_id, match_date) visible
-- Fail: no constraint — that's how duplicates would slip in
```

Run these. Report results.

### If duplicates exist

Deduplicate by keeping the most-recent row (highest `id`):

```sql
DELETE FROM wyscout_match_stats a
USING wyscout_match_stats b
WHERE a.id < b.id
  AND a.player_id = b.player_id
  AND a.match_date = b.match_date;
```

Then add the missing constraint:

```sql
ALTER TABLE wyscout_match_stats
ADD CONSTRAINT wyscout_match_stats_player_match_unique
UNIQUE (player_id, match_date);
```

Update `schema.sql` declaratively. Run a fresh-schema verify.

### If no duplicates but ingest is suspicious

Test the ingest end-to-end:

```python
# Before re-upload
row_count_before = count_rows(player_id=2)

# Re-upload Arthur's xlsx via the ingest pipeline
ingest_wyscout(arthur_xlsx_path)

# After re-upload
row_count_after = count_rows(player_id=2)

assert row_count_before == row_count_after, \
    "Re-upload of same xlsx should produce 0 new rows"
```

If this passes, the ingest is correct. Document the test in CHANGELOG as "accumulation verified."

### Pre-existing bugs

The user says "make sure" — this may be either:
1. **Preventive verification** — they observed no bug, just want confirmation
2. **Bug report** — they observed accumulation problems with real data

The diagnostic queries will tell you which. Report findings clearly.

## Verification

### Synthetic E2E — `migrations/_e2e_phase_6_2_2.py`

```python
# Item 1: age_at_eligibility
def test_age_at_eligibility():
    # Bouhra: foreign_residency + DOB + future eligible_date → returns int
    # Arthur (if bahraini): returns None
    # Player with no DOB: returns None
    # Player with past eligible_date: returns None
    pass

# Item 2: Bahraini status
def test_bahraini_immediate_eligible():
    # Save snapshot of test player
    # Set nationality_status='bahraini', nationality_code='BHR'
    # Generate PDF / fetch profile
    # Assert: ✅ + "Eligible" + Bahrain flag in HTML / PDF
    # Assert: no "Status unknown", no "Eligible from", no residency-since
    # Restore snapshot

# Item 3: Wyscout accumulation
def test_wyscout_idempotent():
    # Snapshot row count
    # Re-ingest a known Wyscout xlsx
    # Assert row count unchanged
    # Snapshot specific row's updated_at — should refresh, not duplicate
```

### Browser checks (after E2E)

1. Bouhra's profile → eligibility card shows: status / residency since / age at eligibility (three lines)
2. Set a test player to bahraini → eligibility shows ✅ + flag + "Eligible"
3. Wyscout re-upload of Arthur's xlsx → "0 new matches, 18 updated" or similar feedback in admin upload page

### Regression

All prior suites must still pass:
- 6.0: 26/26
- 6.1: 57/57
- 6.2: 26/26
- 6.2.1: 23/23

## Acceptance criteria

- ✅ Pre-flight gates pass
- ✅ Item 1: age_at_eligibility helper + display in profile + display in PDF, all 5 conditional cases correct
- ✅ Item 2: bahraini status renders ✅ + flag + "Eligible" immediately, no pending/unknown state for citizens
- ✅ Item 3: Wyscout duplicate check run; if no duplicates, ingest idempotency verified via re-upload test; if duplicates, deduplicated + constraint added + migration recorded
- ✅ All prior E2E suites still pass
- ✅ New synthetic E2E PASS
- ✅ Visual checks in browser pass

## Hard rules

- ❌ Do NOT modify schema EXCEPT for Item 3 unique constraint if duplicates found (audit-gated migration)
- ❌ Do NOT modify existing eligibility logic beyond the bahraini branch and the age field
- ❌ Do NOT change Wyscout ingest unless duplicates are found
- ❌ Do NOT use flask.test_client() — restart real Flask + real HTTP
- ❌ Do NOT initialize git or commit — Ali commits manually
- ❌ Do NOT touch `D:\BFA-Analytics` or `D:\BFA-Analytics-AWS`
- ❌ Do NOT add the Bahrain flag rendering for cases other than nationality_status='bahraini' or 'foreign_ancestry' (only for "already eligible Bahraini-route" players)
- ✅ Run all 3 diagnostic SQL queries for Item 3 BEFORE any code changes
- ✅ Snapshot+restore any test data (don't leave sentinel data in DB)
- ✅ Append v0.6.2.2 entry to CHANGELOG.md covering all 3 items
- ✅ Mark 6.2.2 complete in PROJECT.md; queue Phase 7 (NT role + scout restriction)

## Out of scope

- Arabic translations
- Bulk player import (Phase 9)
- National Team role (Phase 7)
- Scout permission restriction (Phase 7)
- Multi-season Wyscout UI (Phase 4.2.1)
- Production deploy (Phase 8)

## Commit

```powershell
cd D:\BFA-Scout
git add -A
git commit -m "Phase 6.2.2: Age at eligibility + Bahraini immediate-eligible fix + Wyscout accumulation audit"
```
