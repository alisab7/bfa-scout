-- =============================================================
-- BFA-Scout — Evaluations: record the position played in the match
-- =============================================================
-- The `evaluations.position_played_id` column ALREADY exists (declared in
-- schema.sql, FK → positions(id), nullable) but was never written/read —
-- this wires it up. The column-ensure below is a safe no-op on existing
-- installs (valid PG `ADD COLUMN IF NOT EXISTS`, NOT the invalid
-- `ADD CONSTRAINT IF NOT EXISTS`).
--
-- Effects:
--   1. Ensure the column exists (idempotent; no-op where it already does).
--   2. Backfill existing rows with NULL position_played_id to the player's
--      registered primary position, so the view/history never show "—" for
--      historical evaluations.
--   3. Audit gate: report how many rows remain NULL (only players with no
--      registered primary position — acceptable, displays gracefully).
-- =============================================================

\set ON_ERROR_STOP on
\timing on

BEGIN;

-- 1. Ensure column (no-op where present; valid PG syntax)
ALTER TABLE evaluations
  ADD COLUMN IF NOT EXISTS position_played_id INTEGER REFERENCES positions(id);

-- 2. Backfill NULLs to the player's primary position
UPDATE evaluations e
SET    position_played_id = p.primary_position_id
FROM   players p
WHERE  e.player_id = p.id
  AND  e.position_played_id IS NULL
  AND  p.primary_position_id IS NOT NULL;

-- 3. Audit notice (informational — rows still NULL = players with no
--    registered primary position; the UI shows "—" for those)
DO $$
DECLARE
  null_n INT;
BEGIN
  SELECT COUNT(*) INTO null_n FROM evaluations WHERE position_played_id IS NULL;
  RAISE NOTICE 'position_played backfill done — % evaluation(s) still NULL (player has no primary position)', null_n;
END $$;

COMMIT;

-- Eyeball (post-commit)
SELECT position_played_id, COUNT(*) AS n
FROM   evaluations
GROUP  BY position_played_id
ORDER  BY position_played_id NULLS FIRST;
