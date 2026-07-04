"""
Club-alias management screen (admin + TD).

Maps raw wyscout match-team strings ("Al Hadd", "Muharraq") to canonical
clubs. Without these aliases, match-team strings can't be reliably tied to a
club row, blocking the vs-opponent display and league-matches filter.

Routes (under the admin blueprint's /admin prefix):
  GET  /admin/club-aliases              — list aliases + unmapped strings + add form
  POST /admin/club-aliases/add          — add a new alias
  POST /admin/club-aliases/<id>/reassign — change which club an alias points to
  POST /admin/club-aliases/<id>/delete  — remove an alias

Mirrors /admin/assign-clubs (auth, structure, commit discipline).
"""
from __future__ import annotations

from flask import render_template, redirect, url_for, request, flash
from flask_login import current_user

from app.admin import bp
from app.auth.decorators import admin_or_td_required
from app.auth.audit import log_audit
from app.db import get_db


def _all_aliases(conn) -> list:
    """All aliases ordered by alias_text, joined to clubs.name."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ca.id, ca.alias_text, ca.club_id, c.name AS club_name
            FROM   club_aliases ca
            JOIN   clubs c ON c.id = ca.club_id
            ORDER  BY LOWER(ca.alias_text)
            """
        )
        return cur.fetchall()


def _clubs(conn) -> list:
    """All active clubs, grouped premier→first, name-sorted."""
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


def _unmapped_strings(conn) -> list[str]:
    """
    Distinct match-team strings in wyscout_match_stats that have no alias yet.
    After initial seeding this should be empty; new imports may surface more.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT team_name
            FROM (
                SELECT home_team AS team_name FROM wyscout_match_stats
                 WHERE home_team IS NOT NULL
                UNION
                SELECT away_team FROM wyscout_match_stats
                 WHERE away_team IS NOT NULL
            ) AS all_teams
            WHERE  LOWER(team_name) NOT IN (
                SELECT LOWER(alias_text) FROM club_aliases
            )
            ORDER  BY team_name
            """
        )
        rows = cur.fetchall()
    return [r["team_name"] for r in rows]


# ── List + add-form view ───────────────────────────────────────────────────

@bp.route('/club-aliases')
@admin_or_td_required
def club_aliases():
    conn = get_db()
    return render_template(
        'admin/club_aliases.html',
        aliases=_all_aliases(conn),
        clubs=_clubs(conn),
        unmapped=_unmapped_strings(conn),
    )


# ── Add a new alias ────────────────────────────────────────────────────────

@bp.route('/club-aliases/add', methods=['POST'])
@admin_or_td_required
def club_aliases_add():
    alias_text = (request.form.get('alias_text') or '').strip()
    club_id_raw = (request.form.get('club_id') or '').strip()

    if not alias_text:
        flash('Alias text cannot be empty.', 'error')
        return redirect(url_for('admin.club_aliases'))
    if not club_id_raw or not club_id_raw.isdigit():
        flash('Please select a club.', 'error')
        return redirect(url_for('admin.club_aliases'))

    club_id = int(club_id_raw)
    conn = get_db()

    with conn.cursor() as cur:
        # Confirm club exists
        cur.execute("SELECT id, name FROM clubs WHERE id = %s", (club_id,))
        club = cur.fetchone()
        if not club:
            flash('Selected club not found.', 'error')
            return redirect(url_for('admin.club_aliases'))

        try:
            cur.execute(
                """
                INSERT INTO club_aliases (alias_text, club_id)
                VALUES (%s, %s)
                """,
                (alias_text, club_id),
            )
        except Exception as exc:
            conn.rollback()
            if 'unique' in str(exc).lower() or 'duplicate' in str(exc).lower():
                flash(
                    f'Alias "{alias_text}" already exists (case-insensitive). '
                    'Use Reassign to change its club.', 'error'
                )
            else:
                flash(f'Could not add alias: {exc}', 'error')
            return redirect(url_for('admin.club_aliases'))

    conn.commit()
    log_audit(current_user.id, 'admin.club_alias.add', 'club_alias', None,
              ip_address=request.remote_addr)
    flash(f'Alias "{alias_text}" → {club["name"]} added.', 'success')
    return redirect(url_for('admin.club_aliases'))


# ── Reassign an alias to a different club ──────────────────────────────────

@bp.route('/club-aliases/<int:alias_id>/reassign', methods=['POST'])
@admin_or_td_required
def club_aliases_reassign(alias_id: int):
    club_id_raw = (request.form.get('club_id') or '').strip()
    if not club_id_raw or not club_id_raw.isdigit():
        flash('Please select a club.', 'error')
        return redirect(url_for('admin.club_aliases'))

    club_id = int(club_id_raw)
    conn = get_db()

    with conn.cursor() as cur:
        cur.execute(
            "SELECT alias_text FROM club_aliases WHERE id = %s", (alias_id,)
        )
        row = cur.fetchone()
        if not row:
            flash('Alias not found.', 'error')
            return redirect(url_for('admin.club_aliases'))

        cur.execute("SELECT name FROM clubs WHERE id = %s", (club_id,))
        club = cur.fetchone()
        if not club:
            flash('Selected club not found.', 'error')
            return redirect(url_for('admin.club_aliases'))

        cur.execute(
            "UPDATE club_aliases SET club_id = %s WHERE id = %s",
            (club_id, alias_id),
        )

    conn.commit()
    log_audit(current_user.id, 'admin.club_alias.reassign', 'club_alias', alias_id,
              ip_address=request.remote_addr)
    flash(f'"{row["alias_text"]}" reassigned to {club["name"]}.', 'success')
    return redirect(url_for('admin.club_aliases'))


# ── Delete an alias ────────────────────────────────────────────────────────

@bp.route('/club-aliases/<int:alias_id>/delete', methods=['POST'])
@admin_or_td_required
def club_aliases_delete(alias_id: int):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT alias_text FROM club_aliases WHERE id = %s", (alias_id,)
        )
        row = cur.fetchone()
        if not row:
            flash('Alias not found.', 'error')
            return redirect(url_for('admin.club_aliases'))
        cur.execute("DELETE FROM club_aliases WHERE id = %s", (alias_id,))

    conn.commit()
    log_audit(current_user.id, 'admin.club_alias.delete', 'club_alias', alias_id,
              ip_address=request.remote_addr)
    flash(f'Alias "{row["alias_text"]}" deleted.', 'success')
    return redirect(url_for('admin.club_aliases'))
