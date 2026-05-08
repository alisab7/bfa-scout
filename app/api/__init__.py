from flask import Blueprint

bp = Blueprint('api', __name__)


@bp.route('/')
def index():
    return 'TODO: api blueprint — Phase 1+'
