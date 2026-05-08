from flask import Blueprint

bp = Blueprint('criteria', __name__)


@bp.route('/')
def index():
    return 'TODO: criteria blueprint — Phase 2'
