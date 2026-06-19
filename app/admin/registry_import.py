"""
Player Registry Excel import — routes (Page 1).

URL layout (under the admin blueprint's `/admin` prefix):
  GET  /admin/import/players          — Step 1 upload form
  POST /admin/import/players/upload   — parse + classify + park session
  GET  /admin/import/players/preview  — Step 2 preview (NEW/UPDATE/SKIP/ERROR)
  POST /admin/import/players/commit   — Step 3 transactional write
  GET  /admin/import/players/result   — post-commit summary
  GET  /admin/import/players/discard  — clear parked session

All admin-only. Reuses app/admin/bulk_import_session.py for the parked
preview state (distinct Flask-session key from the Phase 9 importer).
"""
from __future__ import annotations

import json

from flask import (
    request, render_template, redirect, url_for, flash,
    session as flask_session, current_app,
)
from flask_login import current_user

from app.admin import bp
from app.auth.decorators import admin_required
from app.auth.audit import log_audit
from app.db import get_db

from app.admin import registry_import_helpers as rhelpers
from app.admin import bulk_import_session as parked


_RK = 'registry_import_session_id'


@bp.route('/import/players')
@admin_required
def registry_import_index():
    parked.gc()
    pending = parked.get(flask_session.get(_RK), current_user.id)
    return render_template('admin/registry_import_upload.html', pending=pending)


@bp.route('/import/players/upload', methods=['POST'])
@admin_required
def registry_import_upload():
    uploaded = request.files.get('file')
    if not uploaded or not uploaded.filename:
        flash("Choose the .xlsx Player Registry file before uploading.", "error")
        return redirect(url_for('admin.registry_import_index'))

    try:
        rows = rhelpers.parse_registry(uploaded)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for('admin.registry_import_index'))

    display_rows, write_plan, summary = rhelpers.classify_registry_rows(rows)
    # Stash the write plan alongside the summary (parked store is in-memory,
    # so date objects survive — no serialization).
    summary = {**summary, 'write_plan': write_plan}

    token = parked.new_session_id()
    parked.store(token, user_id=current_user.id, file_name=uploaded.filename,
                 parsed_rows=display_rows, summary=summary)
    flask_session[_RK] = token
    return redirect(url_for('admin.registry_import_preview'))


@bp.route('/import/players/preview')
@admin_required
def registry_import_preview():
    token = flask_session.get(_RK)
    data = parked.get(token, current_user.id)
    if not data:
        flash("No pending import (it may have expired). Upload again.", "error")
        return redirect(url_for('admin.registry_import_index'))
    return render_template('admin/registry_import_preview.html',
                           rows=data['parsed_rows'],
                           summary=data['summary'],
                           file_name=data['file_name'])


@bp.route('/import/players/commit', methods=['POST'])
@admin_required
def registry_import_commit():
    token = flask_session.get(_RK)
    data = parked.get(token, current_user.id)
    if not data:
        flash("No pending import to commit. Upload again.", "error")
        return redirect(url_for('admin.registry_import_index'))

    write_plan = data['summary'].get('write_plan', [])
    file_name  = data['file_name']

    conn = get_db()
    created_ids: list[int] = []
    updated_ids: list[int] = []
    error: str | None = None

    try:
        with conn:                       # one transaction; rolls back on raise
            for p in write_plan:
                if p['db_id'] is None:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO players
                                (full_name, full_name_ar, national_id, dob,
                                 age_group, is_active, created_by)
                            VALUES (%s, %s, %s, %s, %s, TRUE, %s)
                            RETURNING id
                            """,
                            (p['full_name'], p['full_name_ar'], p['cpr'],
                             p['dob'], p['age_group'], current_user.id)
                        )
                        new_id = cur.fetchone()['id']
                    created_ids.append(new_id)
                    _audit(conn, current_user.id, player_id=new_id,
                           action='create', cpr=p['cpr'], file_name=file_name)
                else:
                    with conn.cursor() as cur:
                        # COALESCE so blank name_ar/dob don't wipe existing
                        # data; age_group always set (highest-wins resolved).
                        cur.execute(
                            """
                            UPDATE players
                            SET    full_name    = %s,
                                   full_name_ar = COALESCE(%s, full_name_ar),
                                   dob          = COALESCE(%s, dob),
                                   age_group    = %s,
                                   updated_at   = NOW()
                            WHERE  id = %s
                            """,
                            (p['full_name'], p['full_name_ar'], p['dob'],
                             p['age_group'], p['db_id'])
                        )
                    updated_ids.append(p['db_id'])
                    _audit(conn, current_user.id, player_id=p['db_id'],
                           action='update', cpr=p['cpr'], file_name=file_name)

            log_audit(
                user_id=current_user.id,
                action='admin.registry_import_completed',
                entity_type='admin', entity_id=None,
                details={
                    'created': len(created_ids), 'updated': len(updated_ids),
                    'file_name': file_name,
                    'created_ids': created_ids, 'updated_ids': updated_ids,
                },
            )
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        current_app.logger.exception("registry import commit failed")
        error = str(exc)

    if error:
        flash(f"Import failed (rolled back): {error}", "error")
        return redirect(url_for('admin.registry_import_preview'))

    flask_session.pop(_RK, None)
    parked.discard(token)
    flask_session['registry_import_last_result'] = {
        'created': len(created_ids), 'updated': len(updated_ids),
        'skipped': data['summary'].get('skipped', 0),
        'merged':  data['summary'].get('merged', 0),
        'errors':  data['summary'].get('errors', 0),
        'file_name': file_name,
        'error_rows': [
            {'excel_row': r['excel_row'], 'name_en': r['name_en'],
             'reason': r['reason']}
            for r in data['parsed_rows'] if r['status'] == 'ERROR'
        ],
    }
    return redirect(url_for('admin.registry_import_result'))


def _audit(conn, importer_id, *, player_id, action, cpr, file_name):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO audit_log (user_id, action, entity_type, entity_id, details)
            VALUES (%s, %s, %s, %s, %s::jsonb)
            """,
            (importer_id, 'player.registry_imported', 'player', player_id,
             json.dumps({'action': action, 'cpr': cpr,
                         'source_file_name': file_name,
                         'importer_id': importer_id}))
        )


@bp.route('/import/players/result')
@admin_required
def registry_import_result():
    summary = flask_session.pop('registry_import_last_result', None)
    if not summary:
        return redirect(url_for('admin.registry_import_index'))
    return render_template('admin/registry_import_result.html', summary=summary)


@bp.route('/import/players/discard')
@admin_required
def registry_import_discard():
    token = flask_session.pop(_RK, None)
    parked.discard(token)
    flash("Pending import discarded.", "success")
    return redirect(url_for('admin.registry_import_index'))
