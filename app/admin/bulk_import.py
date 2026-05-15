"""
Bulk player import blueprint sub-routes (Phase 9).

URL layout (mounted under the admin blueprint's `/admin` prefix):
  GET  /admin/players/bulk-import                — Step 1 upload form
  POST /admin/players/bulk-import/upload         — parse + park session
  GET  /admin/players/bulk-import/preview        — Step 2 preview table
  POST /admin/players/bulk-import/commit         — Step 3 transactional commit
  GET  /admin/players/bulk-import/result         — post-commit summary
  GET  /admin/players/bulk-import/discard        — clear parked session
  GET  /admin/players/bulk-import/template.csv   — downloadable CSV template
  GET  /admin/players/bulk-import/template.xlsx  — downloadable Excel template

All routes are gated on `admin_required` — scout/TD/viewer/nt_staff
get 403; anon redirects to login.

Session contract:
  flask.session['bulk_import_session_id']  — opaque token (~22 chars)
  app/admin/bulk_import_session.py         — module-level dict of
                                              parsed-rows-per-token
"""
from __future__ import annotations

import io
import json

from flask import (
    request, render_template, redirect, url_for, abort, flash,
    session as flask_session, send_file, current_app,
)
from flask_login import current_user

from app.admin import bp
from app.auth.decorators import admin_required
from app.auth.audit import log_audit
from app.db import get_db

from app.admin import bulk_import_helpers as helpers
from app.admin import bulk_import_session as parked

import pandas as pd


# Flask session key under which we stash the parked-import token.
_SESSION_TOKEN_KEY = 'bulk_import_session_id'


# ───────── Step 1: upload form ───────────────────────────────────────────

@bp.route('/players/bulk-import')
@admin_required
def bulk_import_index():
    """Step 1 — upload form. If the user already has a parked import,
    surface it so they can resume or discard."""
    parked.gc()                                 # lazy expiry sweep
    pending = parked.get(flask_session.get(_SESSION_TOKEN_KEY),
                         current_user.id)
    return render_template(
        'admin/bulk_import_upload.html',
        pending=pending,
    )


@bp.route('/players/bulk-import/upload', methods=['POST'])
@admin_required
def bulk_import_upload():
    """Step 1.5 — parse the uploaded file, classify every row, park the
    result under a fresh session token, redirect to preview."""
    uploaded = request.files.get('file')
    if not uploaded or not uploaded.filename:
        flash("Choose a CSV or .xlsx file before uploading.", "error")
        return redirect(url_for('admin.bulk_import_index'))

    try:
        rows = helpers.parse_file(uploaded)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for('admin.bulk_import_index'))

    parsed, summary = helpers.classify_rows(rows)

    token = parked.new_session_id()
    parked.store(token,
                 user_id=current_user.id,
                 file_name=uploaded.filename,
                 parsed_rows=parsed,
                 summary=summary)
    flask_session[_SESSION_TOKEN_KEY] = token

    return redirect(url_for('admin.bulk_import_preview'))


# ───────── Step 2: preview ───────────────────────────────────────────────

@bp.route('/players/bulk-import/preview')
@admin_required
def bulk_import_preview():
    token = flask_session.get(_SESSION_TOKEN_KEY)
    data = parked.get(token, current_user.id)
    if not data:
        flash("No pending import (it may have expired). Upload again.",
              "error")
        return redirect(url_for('admin.bulk_import_index'))
    return render_template(
        'admin/bulk_import_preview.html',
        rows=data['parsed_rows'],
        summary=data['summary'],
        file_name=data['file_name'],
        session_id=token,
    )


# ───────── Step 3: commit ────────────────────────────────────────────────

@bp.route('/players/bulk-import/commit', methods=['POST'])
@admin_required
def bulk_import_commit():
    """
    Commit the parked import inside ONE transaction. Either every row
    that's eligible (valid or duplicate-with-action='update') succeeds
    AND the audit log gets its rows, or the whole thing rolls back.
    """
    token = flask_session.get(_SESSION_TOKEN_KEY)
    data = parked.get(token, current_user.id)
    if not data:
        flash("No pending import to commit. Upload again.", "error")
        return redirect(url_for('admin.bulk_import_index'))

    # Read per-duplicate-row action choices from the submitted form.
    # Each duplicate row has a select named `row_<n>_action` with
    # values 'skip' (default) or 'update'.
    row_actions = {
        int(k.removeprefix('row_').removesuffix('_action')):
            (v or 'skip').strip()
        for k, v in request.form.items()
        if k.startswith('row_') and k.endswith('_action')
    }

    parsed_rows = data['parsed_rows']
    file_name   = data['file_name']

    conn = get_db()
    created_ids:   list[int] = []
    updated_ids:   list[int] = []
    skipped_count = 0
    invalid_count = sum(1 for r in parsed_rows if r['status'] == 'invalid')
    error: str | None = None

    try:
        # One outer transaction. Any failure → ROLLBACK everything,
        # nothing written, audit-log stays clean.
        with conn:
            for r in parsed_rows:
                row_num = r['row_number']
                if r['status'] == 'invalid':
                    continue
                if r['status'] == 'duplicate':
                    action = row_actions.get(row_num, 'skip')
                    if action == 'skip':
                        skipped_count += 1
                        continue
                    if action != 'update':
                        # Defensive — only 'skip' / 'update' are valid.
                        raise ValueError(
                            f"row {row_num}: unknown duplicate action {action!r}"
                        )
                    # Apply UPDATE — only non-NULL fields overwrite.
                    params = helpers.build_db_params(conn, r['fields'])
                    updates = {k: v for k, v in params.items() if v is not None}
                    if not updates:
                        # Nothing to update; treat as skip.
                        skipped_count += 1
                        continue
                    set_clauses = ", ".join(f"{k} = %({k})s" for k in updates)
                    updates['id'] = r['duplicate_of']
                    with conn.cursor() as cur:
                        cur.execute(
                            f"UPDATE players SET {set_clauses}, "
                            f"updated_at = NOW() WHERE id = %(id)s",
                            updates
                        )
                    updated_ids.append(r['duplicate_of'])
                    _audit_player(conn, current_user.id,
                                  player_id=r['duplicate_of'],
                                  row_number=row_num, action='update',
                                  file_name=file_name)
                    continue

                # r['status'] == 'valid' → INSERT new player.
                params = helpers.build_db_params(conn, r['fields'])
                params['created_by'] = current_user.id
                cols = [k for k, v in params.items()
                        if v is not None or k in ('created_by',)]
                # full_name has NOT NULL, so it must be in the column
                # list. Validation already guaranteed it's non-empty.
                if 'full_name' not in cols:
                    cols.append('full_name')
                placeholders = ", ".join(f"%({c})s" for c in cols)
                col_list     = ", ".join(cols)
                with conn.cursor() as cur:
                    cur.execute(
                        f"INSERT INTO players ({col_list}) "
                        f"VALUES ({placeholders}) RETURNING id",
                        params
                    )
                    # Fetch INSIDE the with block — psycopg2 closes the
                    # cursor on exit and fetchone() after that raises
                    # "cursor already closed".
                    new_id = cur.fetchone()['id']
                created_ids.append(new_id)
                _audit_player(conn, current_user.id,
                              player_id=new_id, row_number=row_num,
                              action='create', file_name=file_name)

            # Summary audit row — one per import. Lives inside the
            # same transaction so it rolls back with everything else.
            log_audit(
                user_id     = current_user.id,
                action      = 'admin.bulk_import_completed',
                entity_type = 'admin',
                entity_id   = None,
                details     = {
                    'total':       len(parsed_rows),
                    'created':     len(created_ids),
                    'updated':     len(updated_ids),
                    'skipped':     skipped_count,
                    'invalid':     invalid_count,
                    'file_name':   file_name,
                    'created_ids': created_ids,
                    'updated_ids': updated_ids,
                },
            )
    except Exception as exc:
        # `with conn:` auto-rolls-back on exception, but we still want
        # to surface the error.
        try:
            conn.rollback()
        except Exception:
            pass
        current_app.logger.exception("bulk import commit failed")
        error = str(exc)

    if error:
        flash(f"Import failed (rolled back): {error}", "error")
        return redirect(url_for('admin.bulk_import_preview'))

    # Success — clear the parked session and stash the summary so
    # /result can render it. The result-page summary doesn't need
    # the full row list, just the counts + IDs.
    flask_session.pop(_SESSION_TOKEN_KEY, None)
    parked.discard(token)
    flask_session['bulk_import_last_result'] = {
        'total':       len(parsed_rows),
        'created':     len(created_ids),
        'updated':     len(updated_ids),
        'skipped':     skipped_count,
        'invalid':     invalid_count,
        'file_name':   file_name,
        'created_ids': created_ids,
        'updated_ids': updated_ids,
    }
    return redirect(url_for('admin.bulk_import_result'))


def _audit_player(conn, importer_id: int, *, player_id: int,
                  row_number: int, action: str, file_name: str) -> None:
    """One audit_log row per imported player. Lives inside the
    bulk-import transaction so it rolls back with the data write."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO audit_log
                (user_id, action, entity_type, entity_id, details)
            VALUES (%s, %s, %s, %s, %s::jsonb)
            """,
            (importer_id, 'player.bulk_imported', 'player', player_id,
             json.dumps({
                 'row_number':       row_number,
                 'action':           action,
                 'source_file_name': file_name,
                 'importer_id':      importer_id,
             }))
        )


# ───────── Result page ───────────────────────────────────────────────────

@bp.route('/players/bulk-import/result')
@admin_required
def bulk_import_result():
    summary = flask_session.pop('bulk_import_last_result', None)
    if not summary:
        return redirect(url_for('admin.bulk_import_index'))
    return render_template('admin/bulk_import_result.html', summary=summary)


# ───────── Discard ───────────────────────────────────────────────────────

@bp.route('/players/bulk-import/discard')
@admin_required
def bulk_import_discard():
    token = flask_session.pop(_SESSION_TOKEN_KEY, None)
    parked.discard(token)
    flash("Pending import discarded.", "success")
    return redirect(url_for('admin.bulk_import_index'))


# ───────── Downloadable templates ────────────────────────────────────────

_TEMPLATE_HEADERS = list(helpers.ACCEPTED_COLUMNS)

# Two example rows so admins can see the format — modelled after the
# existing test data (Arthur Rezende = Brazilian foreign-residency,
# Saifaldeen Bouhra = Moroccan foreign-residency). Edit-friendly,
# illustrative, not copy-pasteable into prod.
_TEMPLATE_EXAMPLE_ROWS = [
    {
        'full_name':                    'Arthur Rezende (example)',
        'dob':                          '1995-03-12',
        'national_id':                  '999000001',
        'primary_position_code':        'AMF',
        'nationality_code':             'BRA',
        'nationality_status':           'foreign_residency',
        'eligible_from_date':           '',
        'bahrain_residency_start_date': '2020-12-06',
        'current_club_name':            'Al-Muharraq',
        'dominant_foot':                'right',
        'height_cm':                    '178',
        'weight_kg':                    '72',
    },
    {
        'full_name':                    'Saifaldeen Bouhra (example)',
        'dob':                          '2001-01-01',
        'national_id':                  '999000002',
        'primary_position_code':        'DMF',
        'nationality_code':             'MAR',
        'nationality_status':           'foreign_residency',
        'eligible_from_date':           '',
        'bahrain_residency_start_date': '2022-08-15',
        'current_club_name':            'Al-Khalidiya',
        'dominant_foot':                'right',
        'height_cm':                    '166',
        'weight_kg':                    '65',
    },
]


@bp.route('/players/bulk-import/template.csv')
@admin_required
def bulk_import_template_csv():
    df = pd.DataFrame(_TEMPLATE_EXAMPLE_ROWS, columns=_TEMPLATE_HEADERS)
    csv_bytes = df.to_csv(index=False).encode('utf-8')
    return send_file(
        io.BytesIO(csv_bytes),
        mimetype='text/csv',
        as_attachment=True,
        download_name='bfa-scout-bulk-import-template.csv',
    )


@bp.route('/players/bulk-import/template.xlsx')
@admin_required
def bulk_import_template_xlsx():
    df = pd.DataFrame(_TEMPLATE_EXAMPLE_ROWS, columns=_TEMPLATE_HEADERS)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Players', index=False)
    buf.seek(0)
    return send_file(
        buf,
        mimetype=('application/vnd.openxmlformats-officedocument.'
                  'spreadsheetml.sheet'),
        as_attachment=True,
        download_name='bfa-scout-bulk-import-template.xlsx',
    )
