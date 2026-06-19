-- =============================================================
-- BFA-Scout — Youth NT section + restricted youth_nt role
-- =============================================================
-- Effects:
--   1. Pre-flight: aborts if `players.age_group` already exists
--      (one-shot apply guard).
--   2. ADD COLUMN players.age_group VARCHAR(16) DEFAULT 'senior'.
--      DEFAULT keeps every newly-created player on the GENERAL list
--      unless explicitly placed in a youth group, and removes the
--      NULL edge case from the youth-exclusion filter.
--   3. CHECK constraint: age_group IS NULL OR IN ('U17','U20','U23','senior').
--      NOTE (FLAG 1): uppercase, per spec. This intentionally differs
--      from matches.age_group which is lowercase ('senior','u23','u20',
--      'u17') and means a different thing (the match's age-level, not
--      the player's squad). Different table, different semantics.
--   4. Backfill: every existing player → 'senior' so they STAY on the
--      general list (none are hidden by the new youth filter).
--   5. Index for the youth sub-view / exclusion filters.
--   6. Widen users_role_check to add 'youth_nt' (additive — keeps the
--      5 existing roles). DROP+ADD DO-block — NOT the invalid
--      `ADD CONSTRAINT IF NOT EXISTS` syntax.
--   7. Audit gate: no NULL age_group remains; constraint present;
--      role constraint now admits 'youth_nt'. RAISE → ROLLBACK on drift.
-- =============================================================

\set ON_ERROR_STOP on
\timing on

-- ─── Pre-flight (no transaction yet) ───────────────────────────
DO $$
DECLARE
  col_exists BOOLEAN;
BEGIN
  SELECT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE  table_schema = current_schema()
      AND  table_name   = 'players'
      AND  column_name  = 'age_group'
  ) INTO col_exists;
  IF col_exists THEN
    RAISE EXCEPTION 'PRE-FLIGHT FAIL — players.age_group already exists; migration already applied';
  END IF;
END $$;

BEGIN;

-- ─── 1. ADD COLUMN (DEFAULT 'senior' — new players stay on general list)
ALTER TABLE players
  ADD COLUMN age_group VARCHAR(16) DEFAULT 'senior';

-- ─── 2. CHECK constraint (uppercase values, per spec) ───────────
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'players_age_group_check') THEN
    ALTER TABLE players ADD CONSTRAINT players_age_group_check
      CHECK (age_group IS NULL OR age_group IN ('U17','U20','U23','senior'));
  END IF;
END $$;

-- ─── 3. Backfill every existing player to 'senior' ──────────────
UPDATE players SET age_group = 'senior' WHERE age_group IS NULL;

-- ─── 4. Index for the youth filters ─────────────────────────────
CREATE INDEX IF NOT EXISTS idx_players_age_group ON players (age_group);

-- ─── 5. Widen users_role_check (additive — adds youth_nt) ────────
-- DO-block DROP+ADD; the invalid `ADD CONSTRAINT IF NOT EXISTS`
-- syntax is deliberately avoided (caused the half-deployed-schema
-- incident).
DO $$ BEGIN
  ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;
  ALTER TABLE users ADD CONSTRAINT users_role_check
    CHECK (role IN ('admin','technical_director','scout','viewer','nt_staff','youth_nt'));
END $$;

-- ─── 6. Audit gate (RAISE → ROLLBACK on drift) ──────────────────
DO $$
DECLARE
  null_n        INT;
  bad_n         INT;
  has_age_ck    BOOLEAN;
  role_ck_ok    BOOLEAN;
BEGIN
  SELECT COUNT(*) INTO null_n FROM players WHERE age_group IS NULL;
  IF null_n > 0 THEN
    RAISE EXCEPTION 'AUDIT FAIL — % players still have NULL age_group after backfill', null_n;
  END IF;

  SELECT COUNT(*) INTO bad_n FROM players
   WHERE age_group NOT IN ('U17','U20','U23','senior');
  IF bad_n > 0 THEN
    RAISE EXCEPTION 'AUDIT FAIL — % players have an out-of-domain age_group', bad_n;
  END IF;

  SELECT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'players_age_group_check')
    INTO has_age_ck;
  IF NOT has_age_ck THEN
    RAISE EXCEPTION 'AUDIT FAIL — players_age_group_check constraint missing';
  END IF;

  SELECT pg_get_constraintdef(oid) LIKE '%youth_nt%'
    INTO role_ck_ok
    FROM pg_constraint WHERE conname = 'users_role_check';
  IF NOT COALESCE(role_ck_ok, FALSE) THEN
    RAISE EXCEPTION 'AUDIT FAIL — users_role_check does not admit youth_nt';
  END IF;

  RAISE NOTICE 'AUDIT PASS — age_group added + backfilled, youth_nt role enabled';
END $$;

COMMIT;

-- ─── Eyeball tables (post-commit) ──────────────────────────────
SELECT age_group, COUNT(*) AS n FROM players GROUP BY age_group ORDER BY age_group NULLS FIRST;
SELECT pg_get_constraintdef(oid) AS users_role_check
FROM   pg_constraint WHERE conname = 'users_role_check';
