from flask import Blueprint, render_template
from app.auth.decorators import admin_required
from app.evaluations.helpers import list_deleted_evaluations

bp = Blueprint('admin', __name__, template_folder='../templates/admin')

from . import users  # noqa: E402,F401 — registers routes on bp
from . import bulk_import  # noqa: E402,F401 — Phase 9: registers /admin/players/bulk-import/* routes
from . import registry_import  # noqa: E402,F401 — registers /admin/import/players/* routes
from . import photo_import  # noqa: E402,F401 — registers /admin/import/photos/* routes
from . import assign_positions  # noqa: E402,F401 — registers /admin/assign-positions routes
from . import assign_clubs  # noqa: E402,F401 — registers /admin/assign-clubs routes
from . import club_aliases  # noqa: E402,F401 — registers /admin/club-aliases routes


@bp.route('/deleted-evaluations')
@admin_required
def deleted_evaluations():
    """
    Admin recovery view (Phase 5c-3). Lists all soft-deleted evaluations
    across the system with a restore action. Pure recovery — no edit or
    submit. The list_deleted_evaluations() helper is the one documented
    exception to the "filter WHERE deleted_at IS NULL" invariant.
    """
    deleted = list_deleted_evaluations()
    return render_template('admin/deleted_evaluations.html', deleted=deleted)
