#!/usr/bin/env python3
"""
Phase 8 — one-time admin bootstrap (idempotent).

Run once on the droplet after the schema is loaded:

    docker compose -f docker-compose.prod.yml run --rm app \
        python scripts/bootstrap_admin.py

Reuses the app's existing `seed_initial_admin()` (app/db.py) so there
is exactly ONE admin-seeding code path. That function:
  * is a no-op if any admin row already exists (safe to re-run);
  * accepts ADMIN_EMAIL/ADMIN_PASSWORD (Phase 8 spec names) OR the
    legacy INITIAL_ADMIN_EMAIL/INITIAL_ADMIN_PASSWORD;
  * hashes the password with pbkdf2:sha256:600000 (same as every
    other user in the system).

Exit codes:
  0  admin already existed OR was just created
  1  no admin exists AND no usable env var pair was provided
"""
import sys
from pathlib import Path

# `python scripts/bootstrap_admin.py` puts scripts/ on sys.path, not
# the repo root — so `import app` fails (true in the container too,
# WORKDIR=/app notwithstanding). Prepend the repo root explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app
from app.db import _get_pool, seed_initial_admin


def main() -> int:
    app = create_app()
    with app.app_context():
        seed_initial_admin()  # logs + no-ops appropriately

        # Verify the post-condition rather than trust the return: an
        # admin must now exist, else the env vars were missing.
        conn = _get_pool().getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS n FROM users WHERE role = 'admin'")
                n = cur.fetchone()['n']
        finally:
            _get_pool().putconn(conn)

    if n > 0:
        print(f"[bootstrap_admin] OK — {n} admin user(s) present.")
        return 0
    print("[bootstrap_admin] FAILED — no admin exists and no "
          "ADMIN_EMAIL/PASSWORD (or INITIAL_ADMIN_*) provided.",
          file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
