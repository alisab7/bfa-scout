"""
Bulk club-assign screen (admin + TD).

Bulk-imported players (Wyscout / registry) arrive with no club — `club_id`
is NULL. A player's club is the missing link for upcoming match-reconciliation
features (true "vs opponent" on the profile, league-matches filter), since
"which match side is the player's?" can't be answered without it. Setting
clubs one-by-one on each edit form is slow; this screen lists every active
club-less player and assigns a batch to one club in a single save.

Mirrors `/admin/assign-positions` (auth, structure, commit discipline). The
interaction differs deliberately: clubs use BULK-SELECT (checkboxes +
select-all + one club dropdown), because the workflow is "select all of one
club's players, assign, repeat" rather than a per-row choice.

Routes (under the admin blueprint's `/admin` prefix):
  GET  /admin/assign-clubs   — list club-less active players + club dropdown
  POST /admin/assign-clubs   — set club_id (+ current_club) for chosen rows

Sets BOTH `club_id` (the FK) and `current_club` (the denormalised text cache
of clubs.name) so every reader of either column stays consistent.
"""
from __future__ import annotations

from flask import render_template, redirect, url_for, request, flash
from flask_login import current_user

from app.admin import bp
from app.auth.decorators import admin_or_td_required
from app.auth.audit import log_audit
from app.db import get_db


def _clubless_players(conn):
    """Active players with no club set, ordered by name."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, full_name, full_name_ar, national_id,
                   age_group, primary_position_id
            FROM   players
            WHERE  is_active = TRUE
              AND  club_id IS NULL
            ORDER  BY full_name
            """
        )
        return cur.fetchall()


def _clubs(conn):
    """All clubs for the dropdown, grouped premier-then-first, name-sorted."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, name, division
            FROM   clubs
            WHERE  is_active = TRUE
            ORDER  BY CASE division WHEN 'premier' THEN 0 ELSE 1 END, name
            """
        )
        return cur.fetchall()


@bp.route('/assign-clubs')
@admin_or_td_required
def assign_clubs():
    conn = get_db()
    return render_template('admin/assign_clubs.html',
                           players=_clubless_players(conn),
                           clubs=_clubs(conn))


@bp.route('/assign-clubs', methods=['POST'])
@admin_or_td_required
def assign_clubs_save():
    conn = get_db()

    # Validate the chosen club, and capture its name for the denormalised
    # current_club cache (so both columns stay consistent).
    club_raw = (request.form.get('club_id') or '').strip()
    club_id = int(club_raw) if club_raw.isdigit() else None
    club_name = None
    if club_id is not None:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM clubs WHERE id = %s AND is_active = TRUE",
                        (club_id,))
            row = cur.fetchone()
        club_name = row['name'] if row else None
    if club_name is None:
        flash("Pick a club before assigning.", "error")
        return redirect(url_for('admin.assign_clubs'))

    # Selected players: checkboxes named player_ids (multi-value).
    player_ids: list[int] = []
    for raw in request.form.getlist('player_ids'):
        if (raw or '').strip().isdigit():
            player_ids.append(int(raw))

    if not player_ids:
        flash("No players were selected.", "error")
        return redirect(url_for('admin.assign_clubs'))

    updated = 0
    with conn.cursor() as cur:
        # Set BOTH club_id and current_club. Guard on still-clubless + active
        # so a stale form can't overwrite a club set in the meantime.
        cur.execute(
            """
            UPDATE players
            SET    club_id = %s, current_club = %s, updated_at = NOW()
            WHERE  id = ANY(%s)
              AND  is_active = TRUE
              AND  club_id IS NULL
            RETURNING id
            """,
            (club_id, club_name, player_ids)
        )
        assigned = [r['id'] for r in cur.fetchall() or []]
        updated = len(assigned)
        for pid in assigned:
            log_audit(current_user.id, 'player.club_assigned', 'player', pid,
                      {'club_id': club_id, 'club_name': club_name,
                       'via': 'bulk_assign'})
    conn.commit()   # psycopg2 discipline — persist the batch

    if updated:
        flash(f"Assigned {club_name} to {updated} player"
              f"{'' if updated == 1 else 's'}.", "success")
    else:
        flash("No players were assigned (they may already have a club).", "error")
    return redirect(url_for('admin.assign_clubs'))
