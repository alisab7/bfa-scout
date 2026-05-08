# Cowork Session: BFA-Scout Phase 0 Patch — Fix view definition + verify seeds

## Context

Phase 0 scaffold is committed but `schema.sql` has a PostgreSQL strict-GROUP-BY error in the verification view at the end of the file. When Ali ran `psql -U bfa -d bfa_scout -f D:\BFA-Scout\schema.sql`, this error appeared:

```
INSERT 0 0
psql:D:/BFA-Scout/schema.sql:498: ERROR:  column "pg.sort_order" must appear in the GROUP BY clause or be used in an aggregate function
LINE 7: ORDER BY pg.sort_order;
```

The `INSERT 0 0` immediately before the error is also suspicious — could indicate the `position_group_criteria` seed inserted 0 rows. Need to verify all seeds landed.

**Working folder:** `D:\BFA-Scout` (do NOT touch `D:\BFA-Analytics` or `D:\BFA-Analytics-AWS`)

**Database:** `bfa_scout` on local Postgres (user `bfa`). Native install, not Docker.

## Goal

1. Fix the view definition in `schema.sql`
2. Apply the fix to the live database
3. Verify all seed data is correctly populated (re-run schema.sql if anything is missing — it is idempotent)
4. Report final state to Ali

## Step 1 — Fix `schema.sql`

Open `D:\BFA-Scout\schema.sql`. Find the `v_position_group_form_counts` view definition near the end (around line 493). It currently looks like:

```sql
CREATE OR REPLACE VIEW v_position_group_form_counts AS
SELECT pg.code AS position_group,
       COUNT(pgc.criterion_id) AS criteria_count
FROM position_groups pg
LEFT JOIN position_group_criteria pgc ON pgc.position_group_id = pg.id
GROUP BY pg.code
ORDER BY pg.sort_order;
```

Change the `GROUP BY` line from:
```sql
GROUP BY pg.code
```
to:
```sql
GROUP BY pg.code, pg.sort_order
```

Nothing else changes. Save the file.

## Step 2 — Apply fix to live DB

```powershell
cd D:\BFA-Scout
psql -U bfa -d bfa_scout -c "DROP VIEW IF EXISTS v_position_group_form_counts;"
psql -U bfa -d bfa_scout -f schema.sql
```

The full schema.sql re-run is safe — every CREATE uses `IF NOT EXISTS` and every INSERT uses `ON CONFLICT DO NOTHING`. Tables and rows that already exist will be no-ops. Missing rows (if any) will fill in. The view will be created cleanly this time.

## Step 3 — Verify seed counts

```powershell
psql -U bfa -d bfa_scout -c "SELECT 'position_groups' AS t, COUNT(*) FROM position_groups UNION ALL SELECT 'positions', COUNT(*) FROM positions UNION ALL SELECT 'criteria_categories', COUNT(*) FROM criteria_categories UNION ALL SELECT 'criteria', COUNT(*) FROM criteria UNION ALL SELECT 'position_group_criteria', COUNT(*) FROM position_group_criteria;"
```

Expected output:

| t | count |
|---|---|
| position_groups | 8 |
| positions | 26 |
| criteria_categories | 4 |
| criteria | 37 |
| position_group_criteria | ~150 |

If any count is 0 or below expected, **stop and investigate** before proceeding. Don't wave it off.

## Step 4 — Verify the view works

```powershell
psql -U bfa -d bfa_scout -c "SELECT * FROM v_position_group_form_counts;"
```

Expected: 8 rows, each position group showing 18+ criteria. GK will likely have a slightly different mix than outfield groups (GK-specific criteria like shot stopping, distribution).

## Step 5 — Update CHANGELOG.md

Append to the existing `v0.0.1` entry (do not bump version — this is a patch within Phase 0):

```
## v0.0.1 — Project scaffold (existing entry, append below)

### Patch
- Fixed `v_position_group_form_counts` view: PostgreSQL strict GROUP BY required `sort_order` in the clause
- Verified all seed data populated: 8 position_groups, 26 positions, 4 criteria_categories, 37 criteria, ~150 position_group_criteria mappings
```

## Step 6 — Report results

Print to chat:
1. Confirmation the file edit was applied (show the diff)
2. Output of the seed-count query (Step 3)
3. Output of the view query (Step 4)
4. ✅ or ❌ for each acceptance check below

## Acceptance checks

- ✅ `schema.sql` line ~497 reads `GROUP BY pg.code, pg.sort_order`
- ✅ `psql -f schema.sql` runs end-to-end with no errors (just `NOTICE: relation already exists` warnings, which are expected)
- ✅ Seed counts match: 8 / 26 / 4 / 37 / ~150
- ✅ `v_position_group_form_counts` view returns 8 rows, each with criteria_count ≥ 18
- ✅ CHANGELOG.md updated

## Hard rules

- ❌ Do NOT bump the version number — this is a patch within v0.0.1, not a new release
- ❌ Do NOT modify any other part of `schema.sql` — only the GROUP BY line in the view
- ❌ Do NOT touch the Dockerfile or docker-compose.yml — they stay for production deploy later
- ✅ Use `psql` directly (native Postgres install, not Docker)
- ✅ If seed counts come back wrong, investigate and report — do not silently re-seed with hand-crafted INSERTs

## Out of scope

- Phase 1 (Auth & RBAC) — that's the next session
- Any code changes outside `schema.sql` and `CHANGELOG.md`

## Session discipline

- Target: 3 messages or fewer (this is a small patch)
- End with the acceptance checklist printed
- After the session: Ali commits from PowerShell:
  ```powershell
  cd D:\BFA-Scout
  git add schema.sql CHANGELOG.md
  git commit -m "Phase 0 patch: fix v_position_group_form_counts GROUP BY"
  ```
