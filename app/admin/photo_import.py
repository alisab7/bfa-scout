"""
CPR-matched bulk photo import — routes (Page 2).

URL layout (under the admin blueprint's `/admin` prefix):
  GET  /admin/import/photos          — Step 1 multi-file upload form
  POST /admin/import/photos/upload   — derive CPR per filename, match, park
  GET  /admin/import/photos/preview  — Step 2 preview (MATCH / NO MATCH)
  POST /admin/import/photos/commit   — Step 3 upload matched photos to Spaces
  GET  /admin/import/photos/result   — post-commit summary
  GET  /admin/import/photos/discard  — clear parked session

Admin-only. Photos are matched to players by CPR derived from the filename
(`041209370.jpg` → `041209370`; `41209370.jpg` → `041209370` via the SAME
normalize_cpr). Upload reuses the app's existing photo pipeline
(app/players/photos.save_player_photo → Pillow 400×400 re-encode →
storage.put_player_photo, keyed by player_id), so imported photos display
identically to manually-uploaded ones.
"""
from __future__ import annotations

import os
import io

from flask import (
    request, render_template, redirect, url_for, flash,
    session as flask_session, current_app,
)
from flask_login import current_user

from app.admin import bp
from app.auth.decorators import admin_required
from app.auth.audit import log_audit
from app.db import get_db
from app.players.cpr import normalize_cpr
from app.players.photos import save_player_photo

from app.admin import bulk_import_session as parked


_PK = 'photo_import_session_id'
_ALLOWED_EXT = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}


def _match_players_by_cpr(cprs: list[str]) -> dict:
    if not cprs:
        return {}
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, national_id, full_name FROM players "
            "WHERE national_id = ANY(%s) AND is_active = TRUE",
            (cprs,)
        )
        return {r['national_id']: {'id': r['id'], 'name': r['full_name']}
                for r in cur.fetchall()}


@bp.route('/import/photos')
@admin_required
def photo_import_index():
    parked.gc()
    pending = parked.get(flask_session.get(_PK), current_user.id)
    return render_template('admin/photo_import_upload.html', pending=pending)


@bp.route('/import/photos/upload', methods=['POST'])
@admin_required
def photo_import_upload():
    files = [f for f in request.files.getlist('files') if f and f.filename]
    if not files:
        flash("Choose one or more image files (named by CPR) to upload.", "error")
        return redirect(url_for('admin.photo_import_index'))

    # First pass: derive CPR from each filename + read bytes.
    prelim = []
    for f in files:
        stem, ext = os.path.splitext(f.filename)
        ext = ext.lower()
        entry = {'filename': f.filename, 'cpr': None,
                 'player_id': None, 'player_name': None,
                 'status': None, 'reason': '', 'bytes': None}
        if ext not in _ALLOWED_EXT:
            entry['status'] = 'ERROR'
            entry['reason'] = f"not an image ({ext or 'no extension'})"
            prelim.append(entry)
            continue
        cpr = normalize_cpr(os.path.basename(stem))
        if cpr is None:
            entry['status'] = 'ERROR'
            entry['reason'] = "filename is not a valid CPR"
            prelim.append(entry)
            continue
        entry['cpr'] = cpr
        entry['bytes'] = f.read()
        if not entry['bytes']:
            entry['status'] = 'ERROR'
            entry['reason'] = "empty file"
            entry['bytes'] = None
        prelim.append(entry)

    # Match the valid CPRs to players in one query.
    cprs = [e['cpr'] for e in prelim if e['cpr'] and e['status'] is None]
    matched = _match_players_by_cpr(sorted(set(cprs)))
    for e in prelim:
        if e['status'] is not None:
            continue
        m = matched.get(e['cpr'])
        if m:
            e['status'] = 'MATCH'
            e['player_id'] = m['id']
            e['player_name'] = m['name']
        else:
            e['status'] = 'NO_MATCH'
            e['reason'] = f"no active player with CPR {e['cpr']}"
            e['bytes'] = None        # nothing to upload — free the memory

    summary = {
        'total':    len(prelim),
        'matched':  sum(1 for e in prelim if e['status'] == 'MATCH'),
        'no_match': sum(1 for e in prelim if e['status'] == 'NO_MATCH'),
        'errors':   sum(1 for e in prelim if e['status'] == 'ERROR'),
    }
    token = parked.new_session_id()
    parked.store(token, user_id=current_user.id, file_name=f"{len(files)} file(s)",
                 parsed_rows=prelim, summary=summary)
    flask_session[_PK] = token
    return redirect(url_for('admin.photo_import_preview'))


@bp.route('/import/photos/preview')
@admin_required
def photo_import_preview():
    token = flask_session.get(_PK)
    data = parked.get(token, current_user.id)
    if not data:
        flash("No pending photo import (it may have expired). Upload again.", "error")
        return redirect(url_for('admin.photo_import_index'))
    # Don't leak raw bytes to the template — pass a bytes-free view.
    view_rows = [{k: v for k, v in e.items() if k != 'bytes'}
                 for e in data['parsed_rows']]
    return render_template('admin/photo_import_preview.html',
                           rows=view_rows, summary=data['summary'])


@bp.route('/import/photos/commit', methods=['POST'])
@admin_required
def photo_import_commit():
    token = flask_session.get(_PK)
    data = parked.get(token, current_user.id)
    if not data:
        flash("No pending photo import to commit. Upload again.", "error")
        return redirect(url_for('admin.photo_import_index'))

    uploaded, failed = [], []
    for e in data['parsed_rows']:
        if e['status'] != 'MATCH' or not e.get('bytes'):
            continue
        try:
            # Reuse the exact manual-upload pipeline (Pillow re-encode →
            # storage backend, keyed by player_id). No new storage path.
            save_player_photo(e['player_id'], io.BytesIO(e['bytes']))
            uploaded.append(e['filename'])
            log_audit(user_id=current_user.id, action='player.photo_imported',
                      entity_type='player', entity_id=e['player_id'],
                      details={'cpr': e['cpr'], 'filename': e['filename']})
        except Exception as exc:
            current_app.logger.exception("photo import failed for %s", e['filename'])
            failed.append({'filename': e['filename'], 'reason': str(exc)})

    flask_session.pop(_PK, None)
    parked.discard(token)
    flask_session['photo_import_last_result'] = {
        'uploaded': uploaded,
        'failed':   failed,
        'no_match': [e['filename'] for e in data['parsed_rows']
                     if e['status'] == 'NO_MATCH'],
        'errors':   [{'filename': e['filename'], 'reason': e['reason']}
                     for e in data['parsed_rows'] if e['status'] == 'ERROR'],
    }
    return redirect(url_for('admin.photo_import_result'))


@bp.route('/import/photos/result')
@admin_required
def photo_import_result():
    summary = flask_session.pop('photo_import_last_result', None)
    if not summary:
        return redirect(url_for('admin.photo_import_index'))
    return render_template('admin/photo_import_result.html', summary=summary)


@bp.route('/import/photos/discard')
@admin_required
def photo_import_discard():
    token = flask_session.pop(_PK, None)
    parked.discard(token)
    flash("Pending photo import discarded.", "success")
    return redirect(url_for('admin.photo_import_index'))
