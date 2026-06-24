-- =============================================================
-- BFA-Scout — Passport holders (naturalized Bahraini + origin country)
-- =============================================================
-- A passport holder is DEFINED by nationality_status='bahraini' AND an
-- origin_country set — no separate boolean flag. `origin_country` is real
-- queryable data (for future origin-based analysis: "how many players of
-- <origin>…"); `origin_country_code` is the ISO alpha-3 for the flag,
-- mirroring the nationality_code convention.
--
-- Idempotent + valid PG: `ADD COLUMN IF NOT EXISTS` (NOT the invalid
-- `ADD CONSTRAINT IF NOT EXISTS`). No data backfill — existing players are
-- born citizens / residents / foreign with no origin (NULL), unchanged.
-- =============================================================

\set ON_ERROR_STOP on
\timing on

BEGIN;

ALTER TABLE players ADD COLUMN IF NOT EXISTS origin_country      VARCHAR(64);
ALTER TABLE players ADD COLUMN IF NOT EXISTS origin_country_code CHAR(3);

-- Queryable index for origin-based analysis (partial — only set on holders).
CREATE INDEX IF NOT EXISTS idx_players_origin_country
  ON players (origin_country) WHERE origin_country IS NOT NULL;

COMMIT;

-- Eyeball (post-commit)
SELECT COUNT(*) AS passport_holders
FROM   players
WHERE  nationality_status = 'bahraini' AND origin_country IS NOT NULL;
