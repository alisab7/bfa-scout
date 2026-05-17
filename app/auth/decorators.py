from functools import wraps
from flask import abort
from flask_login import current_user


def role_required(*allowed_roles):
    """Decorator that restricts a route to users with one of the given roles."""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            if current_user.role not in allowed_roles:
                abort(403)
            return f(*args, **kwargs)
        return wrapped
    return decorator


# ── Convenience role bundles ──────────────────────────────────────────────────

admin_required       = role_required('admin')
admin_or_td_required = role_required('admin', 'technical_director')
# v1.0.2: nt_staff added to scout_or_above. NT staff need the same
# create/evaluate/upload access as scouts (concrete bug: New Evaluation
# button was hidden because the backend 403'd nt_staff). Admin/TD
# class actions (lock, unlock, admin-edit, eligibility fieldset) remain
# gated by admin_or_td_required separately.
scout_or_above       = role_required('admin', 'technical_director', 'scout', 'nt_staff')
any_authenticated    = role_required('admin', 'technical_director',
                                     'scout', 'viewer', 'nt_staff')

# ── Phase 7 NT-workspace decorators ─────────────────────────────────────────

nt_staff_required = role_required('nt_staff')
# Phase 7.1: widened to include 'technical_director'. The /nt workspace
# is now visible to admin + TD + nt_staff. TD is treated as
# admin-equivalent for NT peer review (consistent with how
# `admin_or_td_required` is used elsewhere in the codebase).
admin_or_nt_staff_required = role_required('admin', 'technical_director',
                                           'nt_staff')
