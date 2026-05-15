"""
Gunicorn config for BFA-Scout production (Phase 8).

Sizing rationale for the $12/mo 2GB / 1-vCPU droplet:
  * workers = 2 — WeasyPrint holds a lot of RSS while rendering a
    passport PDF (~150-250MB transient). 2 sync-ish workers fit in 2GB
    with headroom; 4 risks OOM-kill mid-render.
  * gthread + threads = 4 — most requests are I/O-bound (DB, Spaces).
    Threads give concurrency without the per-worker memory cost.
  * timeout = 120 — a passport PDF is ~3s on Linux but bulk-import
    commit of ~500 rows + WeasyPrint cold paths can spike; 120s is a
    safe ceiling well above the nginx proxy_read_timeout (also 120s).
  * preload_app = True — fork after the app is imported: shorter
    worker boot, shared read-only pages. NOTE: the psycopg2 pool in
    app/db.py is created lazily on first use (per worker, post-fork),
    so preload does NOT share a pool across workers — safe.
"""
bind = "0.0.0.0:5000"
workers = 2
threads = 4
worker_class = "gthread"
timeout = 120
graceful_timeout = 30
keepalive = 5
preload_app = True

# Log to stdout/stderr so `docker logs` / journald is the single
# source of truth (no log files inside the container).
accesslog = "-"
errorlog = "-"
loglevel = "info"
