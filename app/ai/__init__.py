from flask import Blueprint, abort
from flask_login import login_required, current_user

bp = Blueprint('ai', __name__)


@bp.before_request
def _deny_youth_nt():
    if current_user.is_authenticated and current_user.role == 'youth_nt':
        abort(403)


@bp.route('/')
@login_required
def index():
    return 'TODO: ai blueprint — Phase 7'
