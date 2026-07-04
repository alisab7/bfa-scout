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


def enrich_match_history_with_opponent(
    matches: list, player_club_id: int | None
) -> list[dict]:
    """
    Add 'opponent' (str|None) and 'own_match' (bool) to each match row dict.

    opponent  — raw team string of the opposing side when the player's club is
                identified in the match; None otherwise.
    own_match — True when the player's club (by club_id) appears as home or away.

    Uses a single batch DB query regardless of list length.
    When player_club_id is None (player has no club), every row gets
    opponent=None / own_match=False — graceful degradation, no filter shown.
    """
    result = [dict(m) for m in matches]
    if not result:
        return result

    if player_club_id is None:
        for row in result:
            row["opponent"] = None
            row["own_match"] = False
        return result

    team_strings = {
        ts.strip()
        for m in result
        for ts in (m.get("home_team") or "", m.get("away_team") or "")
        if ts.strip()
    }

    if not team_strings:
        for row in result:
            row["opponent"] = None
            row["own_match"] = False
        return result

    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT alias_text, club_id FROM club_aliases"
            " WHERE LOWER(alias_text) = ANY(%s)",
            ([ts.lower() for ts in team_strings],),
        )
        alias_map = {r["alias_text"].lower(): r["club_id"] for r in cur.fetchall()}

    for row in result:
        home = (row.get("home_team") or "").strip()
        away = (row.get("away_team") or "").strip()
        home_id = alias_map.get(home.lower()) if home else None
        away_id = alias_map.get(away.lower()) if away else None
        own_is_home = home_id == player_club_id
        own_is_away = away_id == player_club_id
        row["own_match"] = own_is_home or own_is_away
        if own_is_home:
            row["opponent"] = row.get("away_team")
        elif own_is_away:
            row["opponent"] = row.get("home_team")
        else:
            row["opponent"] = None

    return result
