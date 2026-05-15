from flask import Blueprint
from flask_login import login_required

bp = Blueprint('ai', __name__)


@bp.route('/')
@login_required
def index():
    return 'TODO: ai blueprint — Phase 7'
