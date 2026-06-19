"""
Youth NT section — data helpers.

The youth section surfaces players whose squad `age_group` is one of the
youth groups (U17 / U20 / U23). Senior players (age_group = 'senior' or
NULL) never appear here; the general player list is their home.

These queries are deliberately youth-scoped at the SQL level — they are
the ONLY player surface the restricted youth_nt role can reach, so the
filter is a security boundary, not a convenience.
"""
from app.db import get_db
from app.auth.decorators import YOUTH_GROUPS

# URL slug ⇄ stored age_group value. Slugs are lowercase (clean URLs);
# the stored/displayed value is uppercase (matches the CHECK constraint).
SLUG_TO_GROUP = {'u17': 'U17', 'u20': 'U20', 'u23': 'U23'}
GROUP_TO_SLUG = {v: k for k, v in SLUG_TO_GROUP.items()}


def get_youth_counts() -> dict:
    """Return {'U17': n, 'U20': n, 'U23': n} — active players per youth group."""
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT age_group, COUNT(*) AS n
            FROM   players
            WHERE  is_active = TRUE
              AND  age_group IN %s
            GROUP  BY age_group
            """,
            (YOUTH_GROUPS,)
        )
        rows = cur.fetchall()
    counts = {g: 0 for g in YOUTH_GROUPS}
    for r in rows:
        counts[r['age_group']] = r['n']
    return counts


def get_youth_squad(group: str) -> list:
    """
    Active players in one youth `group` (e.g. 'U17'), joined to position +
    club for the squad table. Ordered by name.

    Hard-fails closed: if `group` is not a youth group, returns [] (never
    leaks senior players into a youth view).
    """
    if group not in YOUTH_GROUPS:
        return []
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT pl.id, pl.full_name, pl.full_name_ar, pl.national_id,
                   pl.dob, pl.age_group, pl.current_club,
                   pl.nationality_code, pl.primary_position_id,
                   p.code AS position_code, p.name AS position_name,
                   pg.code AS group_code,
                   c.name AS club_name
            FROM   players pl
            LEFT JOIN positions p        ON p.id  = pl.primary_position_id
            LEFT JOIN position_groups pg ON pg.id = p.position_group_id
            LEFT JOIN clubs c            ON c.id  = pl.club_id
            WHERE  pl.is_active = TRUE
              AND  pl.age_group = %s
            ORDER  BY pl.full_name
            """,
            (group,)
        )
        return cur.fetchall()
