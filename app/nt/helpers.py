"""
Helpers for the /nt workspace (Phase 7).

`get_eligible_squad_players()` returns the BPL-eligible candidate
list — players who are already eligible to represent Bahrain (or will
be once a recorded eligibility date passes). The query mirrors the
priority order used by `compute_eligibility_status` in
`app/players/eligibility.py`, narrowed to the "eligible now" cases.

`get_resident_players()` (residents view) returns the
naturalization-pathway players (`nationality_status='foreign_residency'`)
split into eligible-now vs still-counting, reusing the same date math.
"""
from datetime import date

from app.db import get_db
from app.players.eligibility import compute_suggested_eligibility


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

    Restricted to the SENIOR (1st team) squad: `age_group = 'senior'`.
    Youth players (U17/U20/U23) live on /youth, not here. The filter is
    NULL-safe — a senior player with a stray NULL age_group is still
    shown (mirrors the general players-list youth-exclusion semantics),
    so no 1st-team player is ever wrongly hidden. This is additive: the
    eligibility logic above is unchanged.

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
              -- Senior (1st team) only; youth live on /youth. NULL-safe so a
              -- stray-NULL senior is never hidden.
              AND  (pl.age_group = 'senior' OR pl.age_group IS NULL)
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


def _effective_eligibility_date(player: dict):
    """
    The date a foreign_residency player becomes (or became) NT-eligible.

    Mirrors `compute_eligibility_status`'s priority order WITHOUT
    reinventing the date math:
      1. explicit admin `eligible_from_date` wins if set;
      2. else derive from `bahrain_residency_start_date` via the shared
         `compute_suggested_eligibility` (residency_start + 5y, leap-safe);
      3. else None — admin hasn't recorded a residency start, so the
         clock can't be computed ("date not set").
    """
    explicit = player.get("eligible_from_date")
    if explicit:
        return explicit
    return compute_suggested_eligibility(player.get("bahrain_residency_start_date"))


def get_resident_players() -> tuple[list[dict], list[dict]]:
    """
    Returns (eligible_now, still_counting) for the residents view.

    Both lists hold active `foreign_residency` players. Each player dict
    is augmented with `eligible_from_effective` (a `date` or None) so the
    template can show *when* a still-counting player qualifies — or flag
    "date not set" when no residency start has been recorded.

    Split rule (uses the shared date helper — no reinvented math):
      * eligible_now    — effective date is set AND <= today
      * still_counting  — effective date is in the future, OR is None
                          (residency start not recorded yet)

    Honours `is_active = TRUE`. The `players` table has NO `deleted_at`
    column (soft-delete is at the evaluations layer per Phase 5c-3), so
    activeness is the only liveness filter here.

    Standing rule: the SELECT includes player_id, national_id, position.
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
              AND  pl.nationality_status = 'foreign_residency'
            ORDER  BY pl.full_name
            """
        )
        rows = [dict(r) for r in cur.fetchall() or []]

    today = date.today()
    eligible_now: list[dict] = []
    still_counting: list[dict] = []
    for p in rows:
        eff = _effective_eligibility_date(p)
        p["eligible_from_effective"] = eff
        if eff is not None and eff <= today:
            eligible_now.append(p)
        else:
            still_counting.append(p)
    return eligible_now, still_counting


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
