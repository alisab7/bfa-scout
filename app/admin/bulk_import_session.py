"""
In-memory parked-import storage (Phase 9).

500 parsed rows don't fit in a Flask session cookie (4KB limit), so we
hold them in a module-level dict keyed by a short token. The token
itself goes in the Flask session — small enough to fit, opaque to
the user.

Persistence: NONE. A Flask restart wipes pending imports. That's
acceptable for v1 — bulk import is a synchronous 1-2-minute admin
flow, and the worst case is "re-upload the same file." If we ever
need durability we swap this for a `bulk_import_sessions` DB table
with the same surface API.

Concurrency: this module-level dict is touched by Flask's WSGI worker
threads. In practice the dev server is single-process+single-thread.
On gunicorn with multiple workers, two simultaneous admins would
NOT share session state — each worker sees its own dict. Acceptable
for v1 (admin headcount is single digits); flag for production
upgrade if it becomes a real problem.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta


_SESSIONS: dict[str, dict] = {}

# How long a parked import lives before being garbage-collected.
# Spec says 30 min; tighter than typical session TTL since the data
# is large-ish (up to 500 rows of parsed input).
_TTL = timedelta(minutes=30)


def new_session_id() -> str:
    """Returns an opaque URL-safe token. ~22 chars of base64."""
    return secrets.token_urlsafe(16)


def store(session_id: str, user_id: int, file_name: str,
          parsed_rows: list[dict], summary: dict) -> None:
    """Park a freshly-parsed import. Idempotent — overwrites any
    existing entry under the same session_id."""
    _SESSIONS[session_id] = {
        'created_at':  datetime.now(),
        'user_id':     user_id,
        'file_name':   file_name,
        'parsed_rows': parsed_rows,
        'summary':     summary,
    }


def get(session_id: str | None, user_id: int) -> dict | None:
    """Fetch a parked import. Returns None if missing, expired, or
    owned by a different user. The user_id guard is the only
    authorization layer here — the blueprint route already gates
    on `admin_required`, but defense-in-depth: don't let admin A
    see admin B's pending import."""
    if not session_id:
        return None
    data = _SESSIONS.get(session_id)
    if not data:
        return None
    if data['user_id'] != user_id:
        return None
    if datetime.now() - data['created_at'] > _TTL:
        # Lazy GC — expire on access. Caller treats expired as not-found.
        _SESSIONS.pop(session_id, None)
        return None
    return data


def discard(session_id: str | None) -> bool:
    """Drop a parked import. Returns True if anything was removed."""
    if not session_id:
        return False
    return _SESSIONS.pop(session_id, None) is not None


def gc() -> int:
    """Sweep expired entries. Returns count removed. Not called
    automatically; the route layer fires it lazily on each request."""
    now = datetime.now()
    expired = [sid for sid, data in _SESSIONS.items()
               if now - data['created_at'] > _TTL]
    for sid in expired:
        _SESSIONS.pop(sid, None)
    return len(expired)
