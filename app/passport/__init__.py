"""
Phase 6 — Player Passport PDF.

Public entry point is the `bp` Blueprint, registered on `app/__init__.py`.
The route `GET /players/<id>/passport.pdf` returns the rendered PDF.

Two modes:
  - default (admin/TD/scout): full data — scout names, evaluator panels,
    eligibility admin notes
  - ?public=1 (any authenticated): redacted — scout names → 'Scout N',
    admin-only eligibility notes stripped

Soft-delete invariant honoured: soft-deleted evaluations excluded from
the page-2 panels; soft-deleted (deactivated) players return 404.
Locked evaluations INCLUDED (locked is workflow protection).
"""
import os
import re
import base64
from datetime import date
from io import BytesIO

from flask import (
    Blueprint, request, render_template, send_file, abort, current_app
)
from flask_login import login_required, current_user

from app.auth.audit import log_audit
from app.passport.data import get_passport_data
from app.passport.renderer import render_passport_pdf
from app.passport.radar_svg import render_wyscout_radar_svg


bp = Blueprint('passport', __name__)


def _slugify(name: str) -> str:
    """ASCII slug for filenames. 'Arthur Rezende' → 'arthur-rezende'.
    Strips non-ASCII (Arabic name half is dropped from filename — keep
    the latin half identifiable to international users / file managers)."""
    if not name:
        return 'player'
    # Strip diacritics and non-ASCII the lazy way (Latin-1 → ASCII keeps
    # most western European names readable; anything else collapses).
    ascii_part = name.encode('ascii', errors='ignore').decode('ascii')
    slug = re.sub(r'[^A-Za-z0-9]+', '-', ascii_part).strip('-').lower()
    return slug or 'player'


def _resolve_photo_data_uri(player_id: int) -> str | None:
    """Return a data:URI for the player photo, or None if there is none.

    Phase 8: bytes now come from app/storage.py (Spaces in prod, local
    FS in dev) instead of a hard-coded local path. base64-embedding is
    UNCHANGED and still deliberate — WeasyPrint's network image fetcher
    is unreliable under load, so the PDF must stay fully self-contained
    (Phase 6 decision). storage.read_player_photo_bytes() returns None
    on any miss/error and never raises, so the passport degrades to the
    placeholder block exactly as before."""
    from app import storage
    raw = storage.read_player_photo_bytes(player_id)
    if not raw:
        return None
    b64 = base64.b64encode(raw).decode('ascii')
    return f"data:image/jpeg;base64,{b64}"


@bp.route('/players/<int:player_id>/passport.pdf')
@login_required
def player_passport(player_id):
    """
    Render the Player Passport PDF.

    Permissions:
      - mode='full' (default): admin / TD / scout
      - mode='public' (?public=1): any authenticated (viewer included)

    Returns 404 if the player isn't active (soft-deleted via
    is_active=FALSE).
    """
    mode = 'public' if request.args.get('public') == '1' else 'full'

    if mode == 'full' and not current_user.has_role(
            'admin', 'technical_director', 'scout'):
        abort(403)

    # Phase 7: thread requesting user's role so NT evals are hidden
    # from scout-generated passports.
    data = get_passport_data(player_id, mode=mode,
                             requesting_user_role=current_user.role)
    if not data:
        abort(404)

    # Render the 6-axis radar SVG only if there's Wyscout data. The
    # data layer already populates `radar_scores` (axis_label → 0-100).
    if data.get('wyscout') and data['wyscout'].get('radar_scores'):
        data['wyscout_radar_svg'] = render_wyscout_radar_svg(
            data['wyscout']['radar_scores']
        )
    else:
        data['wyscout_radar_svg'] = None

    # Embed the player photo as a data URI for offline self-contained PDF.
    data['player']['photo_data_uri'] = _resolve_photo_data_uri(player_id)

    # Generator name on the footer. Public mode redacts to a generic
    # institutional label so an externally-shared PDF doesn't doxx the
    # specific BFA staffer who generated it (the spec's spirit — "for
    # sharing with player agents or external clubs" — extends naturally
    # from scout-identity redaction to generator-identity).
    if mode == 'public':
        data['meta']['generator_name'] = 'BFA Scouting Department'
    else:
        data['meta']['generator_name'] = current_user.full_name

    pdf_bytes = render_passport_pdf(data)

    # Audit log — one row per generation.
    log_audit(
        user_id     = current_user.id,
        action      = 'player.passport_generated',
        entity_type = 'player',
        entity_id   = player_id,
        details     = {'player_id': player_id, 'mode': mode},
    )

    filename = (
        f"BFA-Scout_Player-{player_id}_"
        f"{_slugify(data['player']['full_name'])}_"
        f"{date.today().isoformat()}.pdf"
    )
    return send_file(
        BytesIO(pdf_bytes),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=filename,
    )
