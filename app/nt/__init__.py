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
from app.nt.helpers import get_eligible_squad_players


bp = Blueprint('nt', __name__, url_prefix='/nt')


@bp.route('/')
@login_required
@admin_or_nt_staff_required
def index():
    """National Team workspace landing page."""
    squad = get_eligible_squad_players()
    return render_template('nt/index.html', squad=squad)
