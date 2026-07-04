"""
Club alias resolver.

The only correct way to translate a wyscout match-team string to a clubs.id.
Lookup is case-insensitive against the club_aliases table. Returns None when
no alias exists — never guesses or fuzzy-matches.
"""
from __future__ import annotations

from app.db import get_db


def resolve_club_from_team_string(team_string: str | None) -> int | None:
    """
    Return the clubs.id for a raw wyscout match-team string, or None.

    Lookup is case-insensitive (LOWER comparison against club_aliases.alias_text).
    Returns None for unmapped strings — the caller or admin must add the alias.

    Examples::

        resolve_club_from_team_string('Muharraq')   # → 1  (Al-Muharraq)
        resolve_club_from_team_string('muharraq')   # → 1  (case-insensitive)
        resolve_club_from_team_string('Al Hadd')    # → 3  (Al-Hidd)
        resolve_club_from_team_string('Unknown FC') # → None
        resolve_club_from_team_string(None)         # → None
    """
    if not team_string or not team_string.strip():
        return None
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT club_id FROM club_aliases WHERE LOWER(alias_text) = LOWER(%s)",
            (team_string.strip(),),
        )
        row = cur.fetchone()
    return row["club_id"] if row else None
