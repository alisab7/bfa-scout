from flask import Blueprint

bp = Blueprint('players', __name__)


@bp.route('/')
def index():
    return 'TODO: players blueprint — Phase 3'
