from flask import Blueprint

bp = Blueprint('reports', __name__)


@bp.route('/')
def index():
    return 'TODO: reports blueprint — Phase 6'
