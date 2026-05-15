import os
import sys
import click
import psycopg2
import psycopg2.pool
import psycopg2.extras
from flask import g, current_app


_pool = None


def _get_pool():
    """Return (or lazily create) the shared ThreadedConnectionPool."""
    global _pool
    if _pool is None:
        database_url = current_app.config.get('DATABASE_URL') or os.environ.get('DATABASE_URL')
        if not database_url:
            raise RuntimeError('DATABASE_URL environment variable is not set.')
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=database_url,
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
    return _pool


def get_db():
    """Return a connection from the pool, attached to flask.g for this request."""
    if 'db_conn' not in g:
        g.db_conn = _get_pool().getconn()
    return g.db_conn


def close_db(e=None):
    """Return the connection to the pool at end of request/teardown."""
    conn = g.pop('db_conn', None)
    if conn is not None:
        try:
            _get_pool().putconn(conn)
        except Exception:
            pass


def init_db():
    """Read schema.sql and execute it against the DB (idempotent — uses IF NOT EXISTS)."""
    schema_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'schema.sql'
    )
    conn = _get_pool().getconn()
    try:
        with conn.cursor() as cur:
            with open(schema_path, 'r', encoding='utf-8') as f:
                sql = f.read()
            cur.execute(sql)
        conn.commit()
        click.echo('Database initialised from schema.sql')
    except Exception as e:
        conn.rollback()
        click.echo(f'Error initialising database: {e}', err=True)
        raise
    finally:
        _get_pool().putconn(conn)


def seed_initial_admin():
    """
    Create the initial admin user from INITIAL_ADMIN_EMAIL / INITIAL_ADMIN_PASSWORD
    env vars — one-shot only. Once any admin row exists this function is a no-op.
    Called at app startup inside an app_context, so current_app and _get_pool() work,
    but g (request context) is NOT available — use pool directly.
    """
    conn = _get_pool().getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM users WHERE role = 'admin'")
            if cur.fetchone()['n'] > 0:
                return  # Admin already exists — env vars are ignored

        # Phase 8: accept the spec's ADMIN_* names, falling back to the
        # legacy INITIAL_ADMIN_* the codebase shipped with. One
        # idempotent seed path, two accepted env conventions, so the
        # startup seeder and scripts/bootstrap_admin.py never disagree.
        email    = (os.environ.get('ADMIN_EMAIL')
                    or os.environ.get('INITIAL_ADMIN_EMAIL'))
        password = (os.environ.get('ADMIN_PASSWORD')
                    or os.environ.get('INITIAL_ADMIN_PASSWORD'))

        if not email or not password:
            current_app.logger.warning(
                'No admin user exists and neither ADMIN_EMAIL/PASSWORD nor '
                'INITIAL_ADMIN_EMAIL/PASSWORD are set. Add a pair to the '
                'env file and restart to seed the first admin.'
            )
            return

        from werkzeug.security import generate_password_hash
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (email, password_hash, full_name, role, is_active)
                VALUES (%s, %s, 'Initial Administrator', 'admin', TRUE)
                """,
                (email, generate_password_hash(password, method='pbkdf2:sha256:600000'))
            )
        conn.commit()
        current_app.logger.info(f'Seeded initial admin: {email}')

    except Exception as exc:
        conn.rollback()
        print(f'[db] ERROR in seed_initial_admin: {exc}', file=sys.stderr)
    finally:
        _get_pool().putconn(conn)


@click.command('init-db')
def init_db_command():
    """CLI command: flask init-db — run schema.sql against the configured database."""
    init_db()


def init_app(app):
    """Register teardown and CLI command with the Flask app."""
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
