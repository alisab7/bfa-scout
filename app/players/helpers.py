import os
from datetime import date
from flask import url_for, current_app


def age(dob) -> int | str:
    """Return age in years from a date of birth, or '—' if unknown."""
    if not dob:
        return '—'
    try:
        today = date.today()
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    except Exception:
        return '—'


def get_player_photo(player_id):
    """Return URL for player photo, falling back to placeholder.svg.

    Phase 8: delegates to app/storage.py so the same Jinja global
    works for both backends — Spaces CDN URL in production, local
    /static/photos URL in dev. storage returns None when there's no
    photo (in dev) or unconditionally returns the CDN URL (in prod,
    relying on the template's onerror→placeholder backstop). Either
    way, None here → placeholder.svg, preserving the pre-Phase-8
    contract for every caller (profile/list/grid/compare/eval form,
    and wyscout aggregations' photo_url).
    """
    from app import storage
    url = storage.get_player_photo_url(player_id)
    if url:
        return url
    return url_for('static', filename='photos/placeholder.svg')


def get_player_pos(position_id):
    """
    Return (position_code, group_code, group_name_en) for a positions.id integer.
    Returns (None, None, None) if position_id is None or not found.
    Used as a Jinja global; queries DB via pool so it works outside request context.
    """
    if not position_id:
        return (None, None, None)

    from app.db import _get_pool
    conn = _get_pool().getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.code, pg.code AS group_code, pg.name_en AS group_name
                FROM   positions p
                JOIN   position_groups pg ON pg.id = p.position_group_id
                WHERE  p.id = %s
                """,
                (position_id,)
            )
            row = cur.fetchone()
        if row:
            return (row['code'], row['group_code'], row['group_name'])
        return (None, None, None)
    finally:
        _get_pool().putconn(conn)
