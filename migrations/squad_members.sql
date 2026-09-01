-- =============================================================
-- BFA-Scout — First-Team Squad (admin-curated membership)
-- =============================================================
-- A flat, manually-curated list of the players who are IN the first-team
-- squad. One row per member (UNIQUE player_id makes "add" idempotent —
-- the admin route does ON CONFLICT (player_id) DO NOTHING, so adding the
-- same player twice never duplicates).
--
-- Deliberately has NO eligibility gate: a still-counting resident
-- prospect and a born citizen are equally addable. Membership is an
-- editorial decision by the admin, not a computed one — the eligibility
-- badge is shown alongside each member for context only.
--
-- ON DELETE CASCADE on the player FK mirrors youth_shortlist: deleting a
-- player never orphans a membership row. The reverse is NOT true —
-- removing a squad membership only deletes the squad_members row, never
-- the player.
--
-- All idempotent + valid PG (CREATE TABLE/INDEX IF NOT EXISTS, inline
-- UNIQUE — NOT the invalid `ADD CONSTRAINT IF NOT EXISTS`). Mirrors
-- migrations/youth_shortlist.sql exactly, plus a DO-block audit gate.
-- =============================================================

\set ON_ERROR_STOP on
\timing on

BEGIN;

CREATE TABLE IF NOT EXISTS squad_members (
    id          SERIAL PRIMARY KEY,
    player_id   INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    added_by    INTEGER REFERENCES users(id),
    added_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (player_id)            -- a player is in the squad at most once
);

CREATE INDEX IF NOT EXISTS idx_squad_members_player ON squad_members (player_id);

-- ─── Audit gate — RAISE (→ ROLLBACK) on drift ──────────────────
-- Guards the two properties the app depends on: the table exists, and
-- player_id carries a UNIQUE constraint (without it the route's
-- ON CONFLICT (player_id) DO NOTHING would error at runtime).
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE  table_schema = current_schema() AND table_name = 'squad_members'
  ) THEN
    RAISE EXCEPTION 'AUDIT FAIL — squad_members table was not created';
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM   pg_constraint c
    JOIN   pg_class      t ON t.oid = c.conrelid
    JOIN   pg_attribute  a ON a.attrelid = t.oid AND a.attnum = ANY (c.conkey)
    WHERE  t.relname = 'squad_members'
      AND  c.contype = 'u'
      AND  a.attname = 'player_id'
  ) THEN
    RAISE EXCEPTION 'AUDIT FAIL — squad_members.player_id has no UNIQUE constraint '
                    '(ON CONFLICT (player_id) would fail at runtime)';
  END IF;
END $$;

COMMIT;

-- Eyeball (post-commit)
SELECT COUNT(*) AS squad_rows FROM squad_members;
