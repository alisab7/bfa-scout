# Cowork/Claude Code Session: BFA-Scout Phase 4.2 (Minimal) — Season Column + Backfill

## Context

Phase 5d-1 committed. Twelve phases on master. `wyscout_match_stats` has no `season` column today — that's the gap this phase closes. 34 existing rows all fall in 2025-26 season (verified: dates 2025-09-12 → 2026-04-16). UI work for season-toggle is deferred to Phase 4.2.1 when a second season of data exists.

**Working folder:** `D:\BFA-Scout`.

## Scope

1. Add `season` VARCHAR(7) column to `wyscout_match_stats`
2. Add `derive_season(match_date)` helper (Bahrain Premier League: Aug–May)
3. Modify Wyscout ingest pipeline to compute `season` on insert
4. Backfill all 34 existing rows
5. Standard migration discipline: generator → SQL → dry-run → audit gate → schema.sql → throwaway-namespace verify

**No UI work.** No template changes. No route changes. Schema + ingest only.

## Pre-flight gates

```powershell
git log --oneline | Select-Object -First 1     # expect: 5d-1
git status                                       # expect: clean
psql -U bfa -d bfa_scout -c "SELECT COUNT(*) FROM wyscout_match_stats;"
# expect: 34
psql -U bfa -d bfa_scout -c "\d wyscout_match_stats" | Select-String "season"
# expect: empty (no column yet)
```

## Season helper

`app/wyscout/season.py`:

```python
from datetime import date

def derive_season(match_date: date) -> str:
    """Bahrain Premier League season runs Aug–May.
    A match in 2025-09-12 belongs to season '2025-26'.
    A match in 2026-04-16 also belongs to season '2025-26'.
    """
    if match_date.month >= 8:
        return f"{match_date.year}-{str(match_date.year + 1)[-2:]}"
    return f"{match_date.year - 1}-{str(match_date.year)[-2:]}"
```

Test cases for the helper (include in `_generate_phase_4_2.py`):
- `derive_season(date(2025, 9, 12))` → `'2025-26'`
- `derive_season(date(2026, 4, 16))` → `'2025-26'`
- `derive_season(date(2025, 7, 31))` → `'2024-25'`
- `derive_season(date(2025, 8, 1))` → `'2025-26'`
- `derive_season(date(2026, 8, 15))` → `'2026-27'`

Assert all 5 before SQL emission.

## Schema change

```sql
ALTER TABLE wyscout_match_stats
    ADD COLUMN season VARCHAR(7);

CREATE INDEX IF NOT EXISTS idx_wyscout_match_stats_season ON wyscout_match_stats(season);
```

Nullable for now — backfill fills all existing rows, but future rows might come in with NULL `match_date` (rare but possible), so the column stays nullable.

## Backfill SQL

```sql
-- Backfill: derive season from match_date
UPDATE wyscout_match_stats
SET season = CASE
    WHEN match_date IS NULL THEN NULL
    WHEN EXTRACT(MONTH FROM match_date) >= 8 THEN
        EXTRACT(YEAR FROM match_date)::TEXT || '-' || LPAD((EXTRACT(YEAR FROM match_date)::INT + 1)::TEXT, 4, '0')[3:4]
    ELSE
        (EXTRACT(YEAR FROM match_date)::INT - 1)::TEXT || '-' || LPAD(EXTRACT(YEAR FROM match_date)::TEXT, 4, '0')[3:4]
END
WHERE season IS NULL AND match_date IS NOT NULL;
```

**Audit gate inside transaction:**

```sql
DO $$
DECLARE
    null_season_count INTEGER;
    expected_season_count INTEGER;
BEGIN
    -- All rows with non-NULL match_date should have a season
    SELECT COUNT(*) INTO null_season_count FROM wyscout_match_stats
    WHERE match_date IS NOT NULL AND season IS NULL;
    IF null_season_count > 0 THEN
        RAISE EXCEPTION 'AUDIT FAIL — % rows with match_date have NULL season', null_season_count;
    END IF;

    -- All 34 existing rows should have season = '2025-26' (verified date range)
    SELECT COUNT(*) INTO expected_season_count FROM wyscout_match_stats
    WHERE season = '2025-26';
    IF expected_season_count != 34 THEN
        RAISE EXCEPTION 'AUDIT FAIL — expected 34 rows in season 2025-26, got %', expected_season_count;
    END IF;

    RAISE NOTICE 'AUDIT PASS — all 34 rows backfilled to season 2025-26';
END $$;
```

## Ingest pipeline change

In `app/wyscout/ingest.py`, find the UPSERT/INSERT loop. Before the INSERT, compute season:

```python
from app.wyscout.season import derive_season

# Inside the row processing loop:
if row.get('match_date'):
    season = derive_season(row['match_date'])
else:
    season = None
```

Add `season` to the INSERT column list and `season = EXCLUDED.season` to the DO UPDATE clause (matching the existing UPSERT pattern from Phase 5b).

## Files to create / modify

```
migrations/
├── _generate_phase_4_2.py         [NEW] Generator with derive_season test cases
├── phase_4_2_season_column.sql    [NEW] Migration artifact
├── _dryrun_4_2.py                 [NEW] Savepoint+rollback
└── _verify_throwaway_4_2.py       [NEW] Schema.sql convergence

schema.sql                          [MODIFY] Add `season VARCHAR(7)` inline to wyscout_match_stats CREATE; add index; no ALTER

app/wyscout/
├── season.py                       [NEW] derive_season helper
└── ingest.py                       [MODIFY] Compute and INSERT season

CHANGELOG.md                        [APPEND] v0.5.0-4-2 entry
PROJECT.md                          [UPDATE] Mark 4.2 minimal complete; queue 4.2.1 for when 2nd season arrives; queue Phase 6
```

## Verification

1. Generator script — assert all 5 derive_season test cases pass before SQL emission
2. Dry-run — savepoint+rollback against live DB
3. Apply migration; confirm AUDIT PASS
4. Update schema.sql declaratively
5. Throwaway-namespace verify
6. Restart Flask
7. Re-upload Arthur's Wyscout xlsx:
   - 18 existing rows updated (UPSERT)
   - All 18 retain season = '2025-26'
   - 0 new rows
   - 0 NULL season values

## Acceptance criteria

- ✅ Pre-flight gates pass
- ✅ Generator passes 5/5 derive_season unit tests before SQL emission
- ✅ Migration AUDIT PASS, throwaway-namespace PASS
- ✅ All 34 existing rows have `season = '2025-26'`
- ✅ Re-upload of Wyscout xlsx preserves season on UPSERT
- ✅ Schema.sql declarative-only

## Hard rules

- ❌ No UI work (deferred to 4.2.1)
- ❌ No route changes
- ❌ No template changes
- ❌ Do NOT use flask.test_client()
- ❌ Do NOT initialize git or commit — Ali commits manually
- ❌ Do NOT touch D:\BFA-Analytics or D:\BFA-Analytics-AWS
- ❌ Do NOT add ALTER statements to schema.sql — declarative-only
- ✅ Standard migration pattern (generator → SQL → dry-run → audit → throwaway)
- ✅ Append v0.5.0-4-2 to CHANGELOG.md
- ✅ Mark complete in PROJECT.md

## Out of scope

- Season-toggle UI on comparison page (4.2.1)
- Season-toggle on player profile dashboard (4.2.1)
- Multi-season aggregations in scout dimension (post-4.2.1)

## Commit

```powershell
cd D:\BFA-Scout
git add -A
git commit -m "Phase 4.2: Season column on wyscout_match_stats (backfill + ingest update)"
```
