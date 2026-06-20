"""
Bulk position-assign screen (admin + TD).

Bulk-imported players (registry Excel) have no primary position — the
registry file has no position column — so the evaluate route correctly
redirects them to edit (criteria are position-group-specific). Setting
positions one-by-one is slow; this screen lists every active position-less
player and assigns them in one save.

Routes (under the admin blueprint's `/admin` prefix):
  GET  /admin/assign-positions   — list position-less active players + picker
  POST /admin/assign-positions   — set primary_position_id for chosen rows

Setting `primary_position_id` is sufficient: `players` has no
position_group_id column — the group is derived via JOIN
(positions.position_group_id), exactly as the evaluate guard and the
player edit form rely on. So after a save the evaluate guard passes.
"""
from __future__ import annotations

from flask import render_template, redirect, url_for, request, flash
from flask_login import current_user

from app.admin import bp
from app.auth.decorators import admin_or_td_required
from app.auth.audit import log_audit
from app.db import get_db


def _positionless_players(conn):
    """Active players with no primary position, ordered by name."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, full_name, full_name_ar, age_group
            FROM   players
            WHERE  is_active = TRUE
              AND  primary_position_id IS NULL
            ORDER  BY full_name
            """
        )
        return cur.fetchall()


@bp.route('/assign-positions')
@admin_or_td_required
def assign_positions():
    conn = get_db()
    players = _positionless_players(conn)
    # Reuse the players blueprint's grouped picker — identical options to
    # the edit/eval forms.
    from app.players import _load_position_picker
    position_groups = _load_position_picker()
    return render_template('admin/assign_positions.html',
                           players=players, position_groups=position_groups)


@bp.route('/assign-positions', methods=['POST'])
@admin_or_td_required
def assign_positions_save():
    conn = get_db()

    # Valid position ids (validate submitted values against reality).
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM positions")
        valid_pos_ids = {r['id'] for r in cur.fetchall() or []}

    # Collect chosen positions: form fields named position_<player_id>.
    # Blank selections are skipped (those players stay unassigned).
    assignments: dict[int, int] = {}
    for key, raw in request.form.items():
        if not key.startswith('position_'):
            continue
        pid_str = key[len('position_'):]
        val = (raw or '').strip()
        if not pid_str.isdigit() or not val:
            continue
        try:
            pos_id = int(val)
        except ValueError:
            continue
        if pos_id in valid_pos_ids:
            assignments[int(pid_str)] = pos_id

    updated = 0
    if assignments:
        with conn.cursor() as cur:
            for player_id, pos_id in assignments.items():
                # Guard: only set still-unassigned active players, so a stale
                # form can't overwrite a position set in the meantime.
                cur.execute(
                    """
                    UPDATE players
                    SET    primary_position_id = %s, updated_at = NOW()
                    WHERE  id = %s
                      AND  is_active = TRUE
                      AND  primary_position_id IS NULL
                    """,
                    (pos_id, player_id)
                )
                if cur.rowcount:
                    updated += 1
                    log_audit(current_user.id, 'player.position_assigned',
                              'player', player_id,
                              {'primary_position_id': pos_id, 'via': 'bulk_assign'})
        conn.commit()   # psycopg2 discipline — persist the batch

    if updated:
        flash(f"Assigned a position to {updated} player"
              f"{'' if updated == 1 else 's'}.", "success")
    else:
        flash("No positions were assigned (no rows selected).", "error")
    return redirect(url_for('admin.assign_positions'))
