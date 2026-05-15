from flask import Blueprint
from flask_login import login_required

bp = Blueprint('api', __name__)


@bp.route('/')
@login_required
def index():
    return 'TODO: api blueprint — Phase 1+'
