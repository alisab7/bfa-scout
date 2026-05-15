"""
Helpers for the /nt workspace (Phase 7).

`get_eligible_squad_players()` returns the BPL-eligible candidate
list — players who are already eligible to represent Bahrain (or will
be once a recorded eligibility date passes). The query mirrors the
priority order used by `compute_eligibility_status` in
`app/players/eligibility.py`, narrowed to the "eligible now" cases.
"""
from app.db import get_db


def get_eligible_squad_players() -> list[dict]:
    """
    Returns active players who are NT-eligible NOW, ordered by name.

    Eligibility = any of:
      - nationality_status IN ('bahraini', 'foreign_ancestry')  (birthright)
      - eligible_from_date IS NOT NULL AND eligible_from_date <= CURRENT_DATE
        (explicit admin date in the past)
      - nationality_status = 'foreign_residency' with the 5-year residency
        suggested date already in the past (CHECK: same FIFA Article 5
        baseline as compute_suggested_eligibility, hard-coded to 5y)

    Joins position + group + club for the squad table.

    Honours `is_active = TRUE` (deactivated players excluded). Per
    Phase 5c-3 the `players` table doesn't have `deleted_at`; soft-
    delete is at the evaluations layer, not the player layer.
    """
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT pl.id, pl.full_name, pl.full_name_ar, pl.national_id,
                   pl.dob, pl.current_club, pl.nationality_code,
                   pl.nationality_status, pl.eligible_from_date,
                   pl.bahrain_residency_start_date,
                   p.code  AS position_code, p.name AS position_name,
                   pg.code AS position_group_code,
                   pg.name_en AS position_group_name,
                   c.name AS club_name, c.division AS club_division
            FROM   players pl
            LEFT JOIN positions p        ON p.id  = pl.primary_position_id
            LEFT JOIN position_groups pg ON pg.id = p.position_group_id
            LEFT JOIN clubs c            ON c.id  = pl.club_id
            WHERE  pl.is_active = TRUE
              AND  (
                    pl.nationality_status IN ('bahraini', 'foreign_ancestry')
                 OR (pl.eligible_from_date IS NOT NULL
                     AND pl.eligible_from_date <= CURRENT_DATE)
                 OR (pl.nationality_status = 'foreign_residency'
                     AND pl.bahrain_residency_start_date IS NOT NULL
                     AND pl.bahrain_residency_start_date + INTERVAL '5 years'
                         <= CURRENT_DATE)
              )
            ORDER  BY pl.full_name
            """
        )
        return [dict(r) for r in cur.fetchall() or []]


def get_nt_evaluation_count(player_id: int) -> int:
    """How many NT-staff-authored evaluations exist for this player
    (submitted+locked, non-deleted). Drives the count column on the
    /nt squad table."""
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS n
            FROM   evaluations
            WHERE  player_id = %s
              AND  created_by_role = 'nt_staff'
              AND  status IN ('submitted', 'locked')
              AND  deleted_at IS NULL
            """,
            (player_id,)
        )
        return int(cur.fetchone()["n"])
