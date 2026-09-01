"""
First-team squad management screen (admin only).

The players list now mixes established first-team / call-up-ready players
with the 88 freshly-imported resident prospects (incomplete data, still
counting toward eligibility). A coach opening the app cannot see "the
squad". This screen is where the admin CURATES that squad; the read-only
view lives at `/nt/squad` (National Team workspace, third tab), the same
way the youth shortlist is curated per-player and read at
`/youth/shortlist`.

Mirrors `/admin/assign-clubs` (structure, bulk-select mechanics, audit +
commit discipline). Two deliberate differences:

  * AUTH — assign-clubs/assign-positions are `admin_or_td_required`; squad
    MANAGEMENT is `admin_required` (admin-only), because who is in the
    first-team squad is Ali's editorial call. Viewing is wider (admin + TD
    + nt_staff, on /nt/squad).
  * NO GATE — every active player is addable. There is no eligibility
    check and no age-group check: a still-counting `foreign_residency`
    prospect and a born citizen are equally addable. The eligibility badge
    is rendered for context only.

Routes (under the admin blueprint's `/admin` prefix):
  GET  /admin/squad         — search/filter every active player + current squad
  POST /admin/squad/add     — bulk-add the ticked players to the squad
  POST /admin/squad/remove  — remove ONE player's MEMBERSHIP (never the player)

Removing from the squad deletes the `squad_members` row only — the
`players` row is never touched.
"""
from __future__ import annotations

from flask import render_template, redirect, url_for, request, flash
from flask_login import current_user

from app.admin import bp
from app.auth.decorators import admin_required
from app.auth.audit import log_audit
from app.db import get_db
from app.nt.helpers import (
    get_squad_members, get_squad_member_ids,
    add_players_to_squad, remove_from_squad,
)

# Membership filter values accepted from the `show` dropdown.
_SHOW_VALUES = ('all', 'in', 'out')


def _candidate_players(conn, q: str, pos_id: int | None,
                       club: str | None, show: str):
    """Active players matching the search/filter, for the pick list.

    The candidate pool is EVERY active player — no eligibility gate and no
    age-group gate, so a youth-group prospect or a still-counting resident
    can be put in the first-team squad. With ~88 prospects plus the
    existing roster the list is long, hence the server-side filters:

      q     — name (EN/AR) or National / BFA ID, ILIKE
      pos   — positions.id
      club  — clubs.id, or the literal 'other' for club-less players
      show  — 'all' (default) | 'in' (already in squad) | 'out' (not yet)

    Standing rule: player_id, national_id and position are named
    explicitly, plus the four ELIGIBILITY_REQUIRED_COLUMNS
    (nationality_status, eligible_from_date, bahrain_residency_start_date,
    origin_country) so the badge macro can never be starved.
    """
    extra_clauses: list[str] = []
    extra_params: list = []

    if club:
        if club == 'other':
            extra_clauses.append("pl.club_id IS NULL")
        elif club.isdigit():
            extra_clauses.append("pl.club_id = %s")
            extra_params.append(int(club))

    if show == 'in':
        extra_clauses.append("sm.player_id IS NOT NULL")
    elif show == 'out':
        extra_clauses.append("sm.player_id IS NULL")

    sql = f"""
        SELECT pl.id, pl.full_name, pl.full_name_ar, pl.national_id,
               pl.dob, pl.age_group, pl.current_club, pl.club_id,
               pl.primary_position_id,
               pl.nationality_code, pl.nationality_status,
               pl.eligible_from_date, pl.bahrain_residency_start_date,
               pl.origin_country, pl.origin_country_code,
               p.code  AS position_code, p.name AS position_name,
               pg.code AS position_group_code,
               c.name  AS club_name,
               (sm.player_id IS NOT NULL) AS in_squad
        FROM   players pl
        LEFT JOIN positions p        ON p.id  = pl.primary_position_id
        LEFT JOIN position_groups pg ON pg.id = p.position_group_id
        LEFT JOIN clubs c            ON c.id  = pl.club_id
        LEFT JOIN squad_members sm   ON sm.player_id = pl.id
        WHERE  pl.is_active = TRUE
          AND  (%s = '' OR pl.full_name    ILIKE %s
                        OR pl.full_name_ar ILIKE %s
                        OR pl.national_id  ILIKE %s)
          AND  (%s IS NULL OR pl.primary_position_id = %s)
          {(" AND " + " AND ".join(extra_clauses)) if extra_clauses else ""}
        ORDER  BY pl.full_name
    """
    with conn.cursor() as cur:
        cur.execute(sql, (q, f'%{q}%', f'%{q}%', f'%{q}%',
                          pos_id, pos_id, *extra_params))
        return cur.fetchall()


@bp.route('/squad')
@admin_required
def squad():
    conn = get_db()

    q       = (request.args.get('q', '') or '').strip()
    pos_str = (request.args.get('pos', '') or '').strip()
    pos_id  = int(pos_str) if pos_str.isdigit() else None
    club    = (request.args.get('club', '') or '').strip() or None
    show    = (request.args.get('show', '') or '').strip() or 'all'
    if show not in _SHOW_VALUES:
        show = 'all'

    candidates = _candidate_players(conn, q, pos_id, club, show)

    # Reuse the players blueprint's grouped picker + club grouping — the
    # same options the edit/eval forms and the players list offer.
    from app.players import _load_position_picker
    from app.players.clubs import get_clubs_grouped
    clubs_grouped = get_clubs_grouped()

    return render_template(
        'admin/squad.html',
        candidates=candidates,
        members=get_squad_members(),
        member_count=len(get_squad_member_ids()),
        position_groups=_load_position_picker(),
        clubs_premier=clubs_grouped.get('premier', []),
        clubs_first=clubs_grouped.get('first', []),
        q=q, pos_id=pos_id, club=club, show=show,
    )


def _back_to_squad():
    """Redirect back to /admin/squad, preserving the active filters so the
    admin isn't thrown back to the full unfiltered list after each save."""
    args = {k: v for k, v in (
        ('q',    (request.form.get('q') or '').strip()),
        ('pos',  (request.form.get('pos') or '').strip()),
        ('club', (request.form.get('club') or '').strip()),
        ('show', (request.form.get('show') or '').strip()),
    ) if v}
    return redirect(url_for('admin.squad', **args))


@bp.route('/squad/add', methods=['POST'])
@admin_required
def squad_add():
    """Bulk-add the ticked players to the first-team squad.

    Idempotent: ON CONFLICT (player_id) DO NOTHING inside
    `add_players_to_squad`, so re-submitting a form that includes players
    already in the squad adds nothing and duplicates nothing.
    """
    # Selected players: checkboxes named player_ids (multi-value) —
    # exactly the assign-clubs bulk-select mechanic.
    player_ids: list[int] = []
    for raw in request.form.getlist('player_ids'):
        if (raw or '').strip().isdigit():
            player_ids.append(int(raw))

    if not player_ids:
        flash("No players were selected.", "error")
        return _back_to_squad()

    inserted = add_players_to_squad(player_ids, current_user.id)
    for pid in inserted:
        log_audit(current_user.id, 'player.squad_added', 'player', pid,
                  {'via': 'admin_squad'})

    added = len(inserted)
    skipped = len(set(player_ids)) - added
    if added:
        msg = (f"Added {added} player{'' if added == 1 else 's'} "
               f"to the first-team squad.")
        if skipped:
            msg += f" ({skipped} already in the squad — no duplicates created.)"
        flash(msg, "success")
    else:
        flash("Nothing added — the selected players are already in the squad.",
              "error")
    return _back_to_squad()


@bp.route('/squad/remove', methods=['POST'])
@admin_required
def squad_remove():
    """Remove ONE player's squad MEMBERSHIP. The player record is untouched."""
    raw = (request.form.get('player_id') or '').strip()
    if not raw.isdigit():
        flash("No player was specified.", "error")
        return _back_to_squad()
    player_id = int(raw)

    if remove_from_squad(player_id):
        log_audit(current_user.id, 'player.squad_removed', 'player', player_id,
                  {'via': 'admin_squad'})
        flash("Removed from the first-team squad. The player record was kept.",
              "success")
    else:
        flash("That player was not in the squad.", "error")
    return _back_to_squad()
