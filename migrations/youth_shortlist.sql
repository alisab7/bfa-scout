-- =============================================================
-- BFA-Scout — Youth shortlist (tracked prospects)
-- =============================================================
-- A flat watchlist of youth prospects being tracked toward senior/NT
-- call-up. One row per shortlisted player (UNIQUE player_id makes "add"
-- idempotent — the route does ON CONFLICT … DO UPDATE to refresh the note).
--
-- All idempotent + valid PG (CREATE TABLE/INDEX IF NOT EXISTS, inline
-- UNIQUE — NOT the invalid `ADD CONSTRAINT IF NOT EXISTS`).
-- =============================================================

\set ON_ERROR_STOP on
\timing on

BEGIN;

CREATE TABLE IF NOT EXISTS youth_shortlist (
    id          SERIAL PRIMARY KEY,
    player_id   INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    note        TEXT,
    added_by    INTEGER REFERENCES users(id),
    added_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (player_id)            -- a player is on the shortlist at most once
);

CREATE INDEX IF NOT EXISTS idx_youth_shortlist_player ON youth_shortlist (player_id);

COMMIT;

-- Eyeball (post-commit)
SELECT COUNT(*) AS shortlist_rows FROM youth_shortlist;
