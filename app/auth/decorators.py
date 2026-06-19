from functools import wraps
from flask import abort
from flask_login import current_user

# Youth squad age-groups (UPPERCASE — distinct from matches.age_group).
YOUTH_GROUPS = ('U17', 'U20', 'U23')


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

# ── Youth NT decorators (the first RESTRICTED role) ──────────────────────────
#
# youth_nt is the first role that is BLOCKED FROM SEEING DATA, not just from
# acting. Enforcement is query-level (filtered queries) + real 403s, never
# hidden-UI-only. Two route-level decorators + two object-level helpers:
#
#   youth_section_access   — who may enter the /youth section (everyone working
#                            EXCEPT viewer, plus youth_nt itself).
#   youth_manage_required  — who may CHANGE a player's age_group (promotion):
#                            senior staff only; youth_nt is excluded.
#   deny_youth_nt          — hard 403 for youth_nt on senior-only player
#                            surfaces that are otherwise open to any
#                            authenticated user (general list, compare,
#                            passport, wyscout, reports, ...).
#   require_youth_access   — object-level guard: 403 a youth_nt user who
#                            targets a NON-youth player (profile/evaluate/
#                            edit/delete). Senior roles pass through.

youth_section_access  = role_required('admin', 'technical_director', 'scout',
                                      'nt_staff', 'youth_nt')
youth_manage_required = role_required('admin', 'technical_director', 'nt_staff')


def deny_youth_nt(f):
    """Block the restricted youth_nt role from a route with a real 403.

    Use on senior-scoping player surfaces that are otherwise reachable by any
    authenticated user, so youth_nt cannot leak senior data by direct URL.
    """
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        if current_user.role == 'youth_nt':
            abort(403)
        return f(*args, **kwargs)
    return wrapped


def is_youth_group(age_group) -> bool:
    """True if `age_group` is one of the youth squad groups."""
    return age_group in YOUTH_GROUPS


def require_youth_access(player) -> None:
    """Object-level scoping guard for the restricted youth_nt role.

    If the current user is youth_nt and `player` is NOT in a youth age-group,
    abort(403). Senior roles are unaffected. `player` must expose an
    'age_group' key/attr; a missing/None value is treated as non-youth
    (fail-closed → 403 for youth_nt).
    """
    if current_user.is_authenticated and current_user.role == 'youth_nt':
        ag = None
        if player is not None:
            try:
                ag = player['age_group']
            except (KeyError, TypeError, IndexError):
                ag = getattr(player, 'age_group', None)
        if ag not in YOUTH_GROUPS:
            abort(403)
