-- =============================================================
-- BFA-Scout — club_aliases: maps match-team strings → canonical clubs
-- =============================================================
-- Wyscout match data stores teams as free-text ("Muharraq", "Al Hadd")
-- that don't match clubs.name exactly. This table is the explicit mapping
-- layer. Resolution is always alias-table-only; fuzzy/guessing is ruled out
-- because canonical normalization fails on cases like Al Hadd → Al-Hidd.
--
-- Idempotent: CREATE TABLE/INDEX IF NOT EXISTS; seed uses ON CONFLICT DO NOTHING.
-- Portable: seed maps by club NAME, not hardcoded id, so safe across dev/prod.
-- =============================================================

\set ON_ERROR_STOP on
\timing on

BEGIN;

-- ── Table ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS club_aliases (
    id          SERIAL PRIMARY KEY,
    club_id     INTEGER NOT NULL REFERENCES clubs(id) ON DELETE CASCADE,
    alias_text  TEXT    NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Case-insensitive uniqueness: one match-string → at most one club.
-- The functional index on LOWER(alias_text) enforces this.
CREATE UNIQUE INDEX IF NOT EXISTS idx_club_aliases_alias_lower
    ON club_aliases (LOWER(alias_text));

CREATE INDEX IF NOT EXISTS idx_club_aliases_club
    ON club_aliases (club_id);

-- ── Seed: the 12 real match-team strings from prod wyscout_match_stats ───

INSERT INTO club_aliases (alias_text, club_id)
SELECT v.alias, c.id
FROM (VALUES
    ('A''Ali',     'A''Ali FC'),
    ('Al Ahli',    'Al-Ahli Manama'),
    ('Al Hadd',    'Al-Hidd'),          -- spelling variant; cannot be resolved by normalization
    ('Al Najma',   'Al-Najma'),
    ('Al Riffa',   'Al-Riffa'),
    ('Al Shabab',  'Al-Shabab Manama'),
    ('Bahrain SC', 'Al-Bahrain SC'),
    ('Budaiya',    'Al-Budaiya'),
    ('Khalidiya',  'Al-Khalidiya'),
    ('Malkiya',    'Malkiya Club'),
    ('Muharraq',   'Al-Muharraq'),
    ('Sitra',      'Sitra Club')
) AS v(alias, club_name)
JOIN clubs c ON c.name = v.club_name
ON CONFLICT (LOWER(alias_text)) DO NOTHING;

COMMIT;

-- Eyeball (post-commit)
SELECT ca.alias_text, c.name AS club_name
FROM   club_aliases ca
JOIN   clubs c ON c.id = ca.club_id
ORDER  BY ca.alias_text;
SELECT COUNT(*) AS alias_rows FROM club_aliases;
