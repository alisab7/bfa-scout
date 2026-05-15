"""
Bahraini clubs registry helpers (Phase 5c-3).

The clubs table is seeded once via migration. Use these helpers from
templates/routes; never SELECT from clubs directly so we keep the
"premier" + "first" optgroup pattern consistent everywhere.
"""
from app.db import _get_pool


def get_clubs_grouped() -> dict[str, list[dict]]:
    """
    Returns {'premier': [...], 'first': [...]} of active clubs ordered
    alphabetically within each division. Both keys always present (may
    be empty lists if all are deactivated).
    """
    conn = _get_pool().getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, division
                FROM   clubs
                WHERE  is_active = TRUE
                ORDER  BY division, name
                """
            )
            rows = cur.fetchall() or []
        out = {"premier": [], "first": []}
        for r in rows:
            d = dict(r)
            out.setdefault(d["division"], []).append(d)
        return out
    finally:
        _get_pool().putconn(conn)


def get_club_label(club_id: int | None) -> str | None:
    """`name` of the club for display, or None."""
    if not club_id:
        return None
    conn = _get_pool().getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM clubs WHERE id = %s", (club_id,))
            r = cur.fetchone()
        return r["name"] if r else None
    finally:
        _get_pool().putconn(conn)
