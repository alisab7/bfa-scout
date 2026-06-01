"""
Phase 7 — National Team workspace.

`/nt` is the dedicated workspace for National Team staff. Access is
gated to admin + nt_staff (the spec's exact set; TD is deliberately
not included — see CHANGELOG v0.7.0 for the open question). The
page shows the BPL-eligible squad list with each player's
NT-evaluation count.
"""
from flask import Blueprint, render_template
from flask_login import login_required, current_user

from app.auth.decorators import admin_or_nt_staff_required
from app.nt.helpers import get_eligible_squad_players, get_resident_players


bp = Blueprint('nt', __name__, url_prefix='/nt')


@bp.route('/')
@login_required
@admin_or_nt_staff_required
def index():
    """National Team workspace landing page (citizens track)."""
    squad = get_eligible_squad_players()
    return render_template('nt/index.html', squad=squad)


@bp.route('/residents')
@login_required
@admin_or_nt_staff_required
def residents():
    """
    Coaching-team view of the naturalization pathway: active
    `foreign_residency` players split into "Eligible Now" (residency
    clock complete) and "Still Counting" (future-eligible — shows the
    date, or "date not set" when no residency start is recorded).

    Same access gate as /nt (admin + TD + nt_staff). Reuses the shared
    eligibility date math; no schema/role changes.
    """
    eligible_now, still_counting = get_resident_players()
    return render_template('nt/residents.html',
                           eligible_now=eligible_now,
                           still_counting=still_counting)
