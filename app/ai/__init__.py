from flask import Blueprint

bp = Blueprint('ai', __name__)


@bp.route('/')
def index():
    return 'TODO: ai blueprint — Phase 7'
