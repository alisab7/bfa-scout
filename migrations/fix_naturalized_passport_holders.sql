-- =============================================================
-- BFA-Scout — Data fix: naturalized players mis-coded as foreign_residency
-- =============================================================
-- Context: a naturalized player who holds a Bahraini passport must be modelled
-- as a PASSPORT HOLDER, i.e.
--     nationality_status = 'bahraini'
--     nationality_code   = 'BHR'
--     origin_country      = <their original country name>   (e.g. 'Brazil')
--     origin_country_code = <ISO alpha-3 of origin>          (e.g. 'BRA')
--     bahrain_residency_start_date = <unchanged — keeps the 5-year clock>
--
-- Juninho was already fixed. Ali reports 3 more in the SAME case. They are
-- currently coded nationality_status='foreign_residency' with a FOREIGN
-- nationality_code (the giveaway: a foreign code while really holding a
-- Bahraini passport). origin_country is still NULL on them.
--
-- HOW TO USE
--   1. Run STEP 1 (read-only) to list the candidates and eyeball the 3.
--   2. Fill STEP 2's VALUES list with the confirmed (id, origin_country,
--      origin_country_code) — origin = the player's ORIGINAL country (use the
--      country the current foreign nationality_code points to, e.g. BRA→Brazil,
--      MAR→Morocco). Then run STEP 2 inside the transaction.
--   3. STEP 3 re-checks; COMMIT only if the 3 rows look right, else ROLLBACK.
--
-- This is DATA only — the app code (eligibility filter, profile, PDF, residents
-- view) already handles passport holders correctly once the row is bahraini +
-- origin_country. No deploy needed for this script.
-- =============================================================

\set ON_ERROR_STOP on

-- ── STEP 1 — read-only: candidates (foreign_residency w/ a foreign code) ──
-- These are the players to review. Confirm the 3 naturalized ones with Ali.
SELECT id, full_name, nationality, nationality_code, nationality_status,
       origin_country, origin_country_code, bahrain_residency_start_date
FROM   players
WHERE  is_active = TRUE
  AND  nationality_status = 'foreign_residency'
  AND  origin_country IS NULL
ORDER  BY full_name;

-- ── STEP 2 — the fix (edit the VALUES list, then run) ────────────────────
-- Each row: (player_id, origin_country_name, origin_country_code_alpha3).
-- Example placeholders below — REPLACE with the 3 confirmed players.
BEGIN;

WITH fix(id, origin_country, origin_country_code) AS (
    VALUES
        -- (101, 'Brazil',  'BRA'),
        -- (102, 'Morocco', 'MAR'),
        -- (103, 'Nigeria', 'NGA')
        (NULL::int, NULL::varchar, NULL::char(3))   -- remove this guard row
)
UPDATE players p
SET    nationality_status  = 'bahraini',
       nationality_code    = 'BHR',
       origin_country      = f.origin_country,
       origin_country_code = f.origin_country_code,
       updated_at          = NOW()
FROM   fix f
WHERE  p.id = f.id
  -- Safety: only flip rows that are still the mis-coded shape, so re-running
  -- is idempotent and we never clobber a correctly-set player.
  AND  p.nationality_status = 'foreign_residency';

-- ── STEP 3 — verify, then COMMIT or ROLLBACK ─────────────────────────────
-- Expect: the 3 players now bahraini + BHR + origin set, residency date kept.
SELECT id, full_name, nationality_status, nationality_code,
       origin_country, origin_country_code, bahrain_residency_start_date
FROM   players
WHERE  nationality_status = 'bahraini' AND origin_country IS NOT NULL
ORDER  BY full_name;

-- If correct:
--   COMMIT;
-- else:
--   ROLLBACK;
