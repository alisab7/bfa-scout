from flask import Blueprint

bp = Blueprint('evaluations', __name__)


@bp.route('/')
def index():
    return 'TODO: evaluations blueprint — Phase 5'
