"""
Phase 8 — healthcheck endpoint.

`GET /healthz` returns:
  200 {"status":"ok"}                 app up AND DB reachable
  503 {"status":"error","detail":...} DB unreachable / any failure

Consumed by:
  * Docker HEALTHCHECK (Dockerfile + compose healthcheck)
  * Cloudflare origin health
  * scripts/deploy.sh post-deploy gate

Implementation note: the spec sketch did `from app.db import
get_connection` — that function doesn't exist. The real db module
exposes `get_db()` (request-scoped, needs flask.g) and `_get_pool()`
(pool-direct). We use the pool directly and explicitly `putconn()` in
a finally, so a healthcheck hit can't slowly leak pooled connections
even if a teardown path misbehaves under load.
"""
from flask import Blueprint, jsonify

from app.db import _get_pool

healthz_bp = Blueprint('healthz', __name__)


@healthz_bp.route('/healthz')
def healthz():
    conn = None
    pool = None
    try:
        pool = _get_pool()
        conn = pool.getconn()
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return jsonify(status="ok"), 200
    except Exception as exc:                       # noqa: BLE001 — report any failure
        return jsonify(status="error", detail=str(exc)), 503
    finally:
        if conn is not None and pool is not None:
            try:
                pool.putconn(conn)
            except Exception:
                pass
