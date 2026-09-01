"""
Phase 7 — National Team workspace.

`/nt` is the dedicated workspace for National Team staff. Access is
gated to admin + nt_staff (the spec's exact set; TD is deliberately
not included — see CHANGELOG v0.7.0 for the open question). The
page shows the BPL-eligible squad list with each player's
NT-evaluation count.
"""
from flask import Blueprint, render_template, redirect, url_for, abort
from flask_login import login_required, current_user

from app.auth.decorators import residents_view_required, admin_or_nt_staff_required
from app.nt.helpers import (
    get_eligible_squad_players, get_resident_players, get_squad_members,
)


bp = Blueprint('nt', __name__, url_prefix='/nt')


@bp.route('/')
@login_required
def index():
    """National Team workspace landing page (citizens / senior squad track).

    Senior squad stays admin/TD/nt_staff only. But scouts (committee) CAN
    see /nt/residents, whose tab strip links here ("Citizens") — so rather
    than bounce a scout with a bare 403, loop them to the players list.
    Other non-permitted roles (viewer, youth_nt) still get 403.
    """
    if not current_user.has_role('admin', 'technical_director', 'nt_staff'):
        if current_user.has_role('scout'):
            return redirect(url_for('players.list_players'))
        abort(403)
    squad = get_eligible_squad_players()
    return render_template('nt/index.html', squad=squad)


@bp.route('/residents')
@login_required
@residents_view_required
def residents():
    """
    Coaching-team view of the naturalization pathway: active
    `foreign_residency` players split into "Eligible Now" (residency
    clock complete) and "Still Counting" (future-eligible — shows the
    date, or "date not set" when no residency start is recorded).

    Access: admin + TD + nt_staff + SCOUT (committee members) — split
    from /nt so scouts can read eligibility WITHOUT seeing the senior
    /nt squad page (`index` stays admin_or_nt_staff_required). Viewer
    still excluded. Page content unchanged.
    """
    eligible_now, still_counting = get_resident_players()
    return render_template('nt/residents.html',
                           eligible_now=eligible_now,
                           still_counting=still_counting)


@bp.route('/squad')
@login_required
@admin_or_nt_staff_required
def first_team_squad():
    """
    First-Team Squad — the admin-curated roster, READ-ONLY.

    Shows ONLY players in `squad_members`, so a coach opening this tab
    sees "the squad" rather than the whole players list (which now mixes
    established players with 88 imported prospects).

    Access: admin + TD + nt_staff (`admin_or_nt_staff_required`) — the
    same audience as the /nt Citizens tab, since this is a coaching
    surface in the NT workspace. Scout/viewer/youth_nt get a real 403.
    CURATION is admin-only and lives at /admin/squad.

    Membership is editorial: there is NO eligibility gate. Each row
    renders its eligibility badge via `compute_eligibility_status` for
    context, so a still-counting prospect is visibly flagged as such
    without being hidden.
    """
    members = get_squad_members()
    return render_template('nt/squad.html', members=members)
