"""
Wyscout blueprint — file upload, import management, trends API.

Routes:
  GET  /wyscout/upload/<player_id>      — upload form
  POST /wyscout/upload/<player_id>      — process upload
  GET  /wyscout/result/<import_id>      — import result
  GET  /wyscout/imports/<player_id>     — import history list
  POST /wyscout/delete/<import_id>      — soft-delete (admin only)
  GET  /wyscout/trends/<player_id>      — JSON trend data for Chart.js
  GET  /wyscout/matches                 — read-only matches list (admin/TD)
"""
import os
import uuid
import logging

from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, jsonify, abort, current_app)
from flask_login import login_required, current_user

from app.auth.decorators import admin_or_td_required
from app.db import get_db
from app.wyscout.ingest import ingest_wyscout
from app.wyscout.aggregations import (
    get_player_summary, get_player_match_history,
    get_player_radar_scores, get_player_trends
)

bp = Blueprint('wyscout', __name__)
log = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {'xlsx', 'xls'}
MAX_UPLOAD_BYTES    = 20 * 1024 * 1024   # 20 MB


def _allowed(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _require_player(player_id: int):
    """Fetch player row or 404."""
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, full_name FROM players WHERE id = %s AND is_active = TRUE",
            (player_id,)
        )
        row = cur.fetchone()
    if not row:
        abort(404)
    return row


# ---------------------------------------------------------------------------
# Upload form + processing
# ---------------------------------------------------------------------------
@bp.route('/upload/<int:player_id>', methods=['GET', 'POST'])
@login_required
def upload(player_id):
    if current_user.role not in ('admin', 'technical_director', 'scout'):
        abort(403)

    player = _require_player(player_id)

    if request.method == 'GET':
        return render_template('wyscout/upload.html', player=player)

    # POST — process upload
    f = request.files.get('wyscout_file')
    if not f or not f.filename:
        flash("No file selected.", "error")
        return render_template('wyscout/upload.html', player=player)

    if not _allowed(f.filename):
        flash("Only .xlsx or .xls files are accepted.", "error")
        return render_template('wyscout/upload.html', player=player)

    # Check content length without reading entire file
    f.seek(0, 2)
    size = f.tell()
    f.seek(0)
    if size > MAX_UPLOAD_BYTES:
        flash("File exceeds 20 MB limit.", "error")
        return render_template('wyscout/upload.html', player=player)

    # Save to temp path
    upload_folder = current_app.config.get('UPLOAD_FOLDER', './uploads')
    os.makedirs(upload_folder, exist_ok=True)
    safe_name = f"{player_id}_{uuid.uuid4().hex[:8]}_{f.filename}"
    tmp_path  = os.path.join(upload_folder, safe_name)
    f.save(tmp_path)

    try:
        result = ingest_wyscout(
            player_id      = player_id,
            file_path      = tmp_path,
            file_name      = f.filename,
            uploaded_by_id = current_user.id,
        )
    finally:
        # Clean up temp file
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    if result["status"] == "failed":
        flash(f"Import failed: {result['error']}", "error")
        return render_template('wyscout/upload.html', player=player)

    return redirect(url_for('wyscout.result', import_id=result["import_id"]))


# ---------------------------------------------------------------------------
# Import result page
# ---------------------------------------------------------------------------
@bp.route('/result/<int:import_id>')
@login_required
def result(import_id):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT wi.*, p.full_name AS player_name
            FROM   wyscout_imports wi
            LEFT JOIN players p ON p.id = wi.player_id
            WHERE  wi.id = %s
            """,
            (import_id,)
        )
        imp = cur.fetchone()
    if not imp:
        abort(404)
    return render_template('wyscout/result.html', imp=imp)


# ---------------------------------------------------------------------------
# Import history for a player
# ---------------------------------------------------------------------------
@bp.route('/imports/<int:player_id>')
@login_required
def imports(player_id):
    player = _require_player(player_id)
    conn   = get_db()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT wi.id, wi.file_name, wi.row_count, wi.status,
                   wi.error_message, wi.imported_at,
                   u.full_name AS uploaded_by_name
            FROM   wyscout_imports wi
            LEFT JOIN users u ON u.id = wi.uploaded_by
            WHERE  wi.player_id = %s
            ORDER BY wi.imported_at DESC
            """,
            (player_id,)
        )
        import_list = cur.fetchall() or []
    return render_template('wyscout/imports.html', player=player, import_list=import_list)


# ---------------------------------------------------------------------------
# Delete import (admin only — marks failed, does NOT delete match rows)
# ---------------------------------------------------------------------------
@bp.route('/delete/<int:import_id>', methods=['POST'])
@login_required
def delete_import(import_id):
    if current_user.role != 'admin':
        abort(403)
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT player_id FROM wyscout_imports WHERE id = %s",
            (import_id,)
        )
        row = cur.fetchone()
        if not row:
            abort(404)
        player_id = row["player_id"]

        cur.execute(
            """
            UPDATE wyscout_imports
            SET status = 'failed', error_message = 'Deleted by admin'
            WHERE id = %s
            """,
            (import_id,)
        )
    flash("Import marked as deleted.", "info")
    return redirect(url_for('wyscout.imports', player_id=player_id))


# ---------------------------------------------------------------------------
# Trends API — JSON for Chart.js line charts
# ---------------------------------------------------------------------------
@bp.route('/trends/<int:player_id>')
@login_required
def trends(player_id):
    _require_player(player_id)
    try:
        data = get_player_trends(player_id)
        return jsonify(data)
    except Exception as exc:
        log.exception("trends API error: %s", exc)
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Matches list — read-only verification view (Phase 5b, admin/TD only)
# ---------------------------------------------------------------------------
@bp.route('/matches')
@admin_or_td_required
def list_matches():
    """All matches with linked-stats counts. No edit/delete in 5b."""
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT m.id, m.match_date, m.home_team, m.away_team,
                   m.home_score, m.away_score,
                   m.competition, m.age_group, m.match_type, m.source,
                   COUNT(wms.id) AS linked_stats,
                   u.full_name   AS created_by_name
            FROM   matches m
            LEFT JOIN wyscout_match_stats wms ON wms.match_id = m.id
            LEFT JOIN users u                  ON u.id = m.created_by
            GROUP BY m.id, u.full_name
            ORDER BY m.match_date DESC, m.id DESC
            """
        )
        matches = cur.fetchall() or []
    return render_template('wyscout/matches.html', matches=matches)
