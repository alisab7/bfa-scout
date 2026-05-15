import sys
from app.db import _get_pool


def log_audit(user_id, action, entity_type, entity_id=None, details=None, ip_address=None):
    """
    Insert a row into audit_log.

    Action examples:
        'auth.login.success', 'auth.login.failure', 'auth.logout',
        'auth.password.change', 'user.create', 'user.edit',
        'user.deactivate', 'user.role.change'

    Never raises — audit failure must NOT block the triggering action.
    """
    import json
    try:
        conn = _get_pool().getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO audit_log
                        (user_id, action, entity_type, entity_id, details, ip_address)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        user_id,
                        action,
                        entity_type,
                        entity_id,
                        json.dumps(details) if details else None,
                        ip_address,
                    )
                )
            conn.commit()
        finally:
            _get_pool().putconn(conn)
    except Exception as exc:
        print(f'[audit] WARN: failed to write audit log ({action}): {exc}', file=sys.stderr)
