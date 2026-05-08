from flask import Blueprint

bp = Blueprint('wyscout', __name__)


@bp.route('/')
def index():
    return 'TODO: wyscout blueprint — Phase 4'
