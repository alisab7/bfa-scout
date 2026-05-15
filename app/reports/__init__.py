from flask import Blueprint
from flask_login import login_required

bp = Blueprint('reports', __name__)


@bp.route('/')
@login_required
def index():
    return 'TODO: reports blueprint — Phase 6'
