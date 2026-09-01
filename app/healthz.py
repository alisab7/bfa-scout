"""
Phase 8 — healthcheck endpoint.

`GET /healthz` returns:
  200 {"status":"ok","sha":"<short>"}                 app up AND DB reachable
  503 {"status":"error","detail":...,"sha":"<short>"}  DB unreachable / any failure

Consumed by:
  * Docker HEALTHCHECK (Dockerfile + compose healthcheck)
  * Cloudflare origin health
  * scripts/deploy.sh post-deploy gate
  * ship.sh's "did my change actually go live?" SHA check

The response also carries `sha` — the short git SHA that was baked into
the image at build time via the `GIT_SHA` build arg (Dockerfile ARG ->
ENV, wired through docker-compose.prod.yml's `build.args`). It is read
once at import from the environment, so serving it costs nothing: no
file read, no DB hit, no subprocess. When the build arg was not supplied
(e.g. a plain `docker build` or a locally-run Flask process) it degrades
to "unknown" and the endpoint behaves exactly as before, so the
container healthcheck still passes.

Implementation note: the spec sketch did `from app.db import
get_connection` — that function doesn't exist. The real db module
exposes `get_db()` (request-scoped, needs flask.g) and `_get_pool()`
(pool-direct). We use the pool directly and explicitly `putconn()` in
a finally, so a healthcheck hit can't slowly leak pooled connections
even if a teardown path misbehaves under load.
"""
import os

from flask import Blueprint, jsonify

from app.db import _get_pool

healthz_bp = Blueprint('healthz', __name__)


def _build_sha():
    """Short git SHA baked in at image build time, or 'unknown'.

    Resolved once at import — /healthz is the container health probe and
    must stay dependency-light. Anything that is not a plausible SHA
    (empty, the unsubstituted default, whitespace) becomes 'unknown'
    rather than leaking a placeholder into the deploy verification.
    """
    raw = (os.environ.get('GIT_SHA') or '').strip()
    if not raw or raw.lower() in ('unknown', 'none', '$git_sha', '${git_sha}'):
        return 'unknown'
    return raw[:7]


GIT_SHA = _build_sha()


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
        return jsonify(status="ok", sha=GIT_SHA), 200
    except Exception as exc:                       # noqa: BLE001 — report any failure
        return jsonify(status="error", detail=str(exc), sha=GIT_SHA), 503
    finally:
        if conn is not None and pool is not None:
            try:
                pool.putconn(conn)
            except Exception:
                pass
