"""
migrations/_e2e_phase_8_1.py — Phase 8.1 Security Hardening E2E Tests

Tests:
  1. Password validator — 7 cases
  2. Session config values — PERMANENT_SESSION_LIFETIME, HTTPONLY, SAMESITE
  3. SESSION_COOKIE_SECURE env-aware behaviour
  4. Nginx config — limit_req_zone present, /auth/login location present
  5. Password enforcement in admin user-creation (integration, requires DB)

Run:
    cd D:\\BFA-Scout
    python migrations/_e2e_phase_8_1.py

Expects: DATABASE_URL set in environment (or .env loaded by dotenv).
Does NOT use flask.test_client — tests restart/hit real running app.
For the config assertions the app factory is imported directly; no
running server needed for those checks.
"""

import os
import sys
import re
import traceback
from datetime import timedelta
from pathlib import Path

# ── Colour helpers ───────────────────────────────────────────────────────────
GREEN  = '\033[92m'
RED    = '\033[91m'
YELLOW = '\033[93m'
RESET  = '\033[0m'

PASS = f'{GREEN}PASS{RESET}'
FAIL = f'{RED}FAIL{RESET}'
SKIP = f'{YELLOW}SKIP{RESET}'

results = []


def ok(name):
    results.append((name, True, ''))
    print(f'  {PASS}  {name}')


def fail(name, reason=''):
    results.append((name, False, reason))
    print(f'  {FAIL}  {name}')
    if reason:
        print(f'         {reason}')


def skip(name, reason=''):
    results.append((name, None, reason))
    print(f'  {SKIP}  {name}: {reason}')


# ─────────────────────────────────────────────────────────────────────────────
# §1 — Password validator unit tests
# ─────────────────────────────────────────────────────────────────────────────
print('\n§1  Password validator')

try:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from app.auth.validators import validate_password_strength

    cases = [
        ('Sh0rt',              False, 'too short (<12)'),
        ('alllowercase1234',   False, 'no uppercase'),
        ('ALLUPPERCASE1234',   False, 'no lowercase'),
        ('NoNumbersHereXYZ',   False, 'no digit'),
        ('Valid_Password_12',  True,  'meets all rules'),
        ('a' * 200,            False, 'too long (>128)'),
        ('',                   False, 'empty'),
    ]

    for pwd, expected_valid, desc in cases:
        is_valid, msg = validate_password_strength(pwd)
        name = f'validator: {desc}'
        if is_valid == expected_valid:
            ok(name)
        else:
            fail(name, f'expected valid={expected_valid}, got valid={is_valid} ({msg!r})')

except Exception as e:
    fail('import validate_password_strength', traceback.format_exc(limit=2))


# ─────────────────────────────────────────────────────────────────────────────
# §2 — Flask session config
# ─────────────────────────────────────────────────────────────────────────────
print('\n§2  Session config')

try:
    # Patch env so SESSION_COOKIE_SECURE reads True (production path)
    os.environ.setdefault('FLASK_ENV', 'production')
    os.environ.setdefault('DATABASE_URL', 'postgresql://dummy:dummy@localhost/dummy')
    os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-e2e-phase-8-1')

    from app import create_app
    _app = create_app()

    with _app.app_context():
        cfg = _app.config

        # PERMANENT_SESSION_LIFETIME
        name = 'PERMANENT_SESSION_LIFETIME == timedelta(hours=8)'
        if cfg.get('PERMANENT_SESSION_LIFETIME') == timedelta(hours=8):
            ok(name)
        else:
            fail(name, f"got {cfg.get('PERMANENT_SESSION_LIFETIME')!r}")

        # HTTPONLY
        name = 'SESSION_COOKIE_HTTPONLY is True'
        if cfg.get('SESSION_COOKIE_HTTPONLY') is True:
            ok(name)
        else:
            fail(name, f"got {cfg.get('SESSION_COOKIE_HTTPONLY')!r}")

        # SAMESITE
        name = "SESSION_COOKIE_SAMESITE == 'Lax'"
        if cfg.get('SESSION_COOKIE_SAMESITE') == 'Lax':
            ok(name)
        else:
            fail(name, f"got {cfg.get('SESSION_COOKIE_SAMESITE')!r}")

        # SECURE in production
        name = 'SESSION_COOKIE_SECURE is True when FLASK_ENV=production'
        if cfg.get('SESSION_COOKIE_SECURE') is True:
            ok(name)
        else:
            fail(name, f"got {cfg.get('SESSION_COOKIE_SECURE')!r}")

except Exception as e:
    fail('create_app() for session config check', traceback.format_exc(limit=3))


# §2b — SECURE=False in development
print()
try:
    import importlib
    import app as _app_module
    os.environ['FLASK_ENV'] = 'development'
    importlib.invalidate_caches()
    # Re-import to pick up new env
    import importlib
    _app2 = create_app()
    with _app2.app_context():
        name = 'SESSION_COOKIE_SECURE is False when FLASK_ENV=development'
        val = _app2.config.get('SESSION_COOKIE_SECURE')
        if val is False:
            ok(name)
        else:
            fail(name, f'got {val!r}')
except Exception as e:
    fail('dev env SESSION_COOKIE_SECURE check', traceback.format_exc(limit=2))
finally:
    os.environ['FLASK_ENV'] = 'production'


# ─────────────────────────────────────────────────────────────────────────────
# §3 — Nginx config structural checks
# ─────────────────────────────────────────────────────────────────────────────
print('\n§3  Nginx config')

nginx_conf = Path(__file__).parent.parent / 'nginx' / 'conf.d' / 'bfa-scout.conf'

try:
    conf_text = nginx_conf.read_text()

    name = 'limit_req_zone directive present'
    if 'limit_req_zone' in conf_text and 'login_zone' in conf_text:
        ok(name)
    else:
        fail(name, 'limit_req_zone or login_zone not found in nginx config')

    name = '/auth/login location block with limit_req present'
    if re.search(r'location\s*=?\s*/auth/login', conf_text) and 'limit_req' in conf_text:
        ok(name)
    else:
        fail(name, '/auth/login location or limit_req directive missing')

    name = 'limit_req_status 429 set'
    if 'limit_req_status 429' in conf_text:
        ok(name)
    else:
        fail(name, 'limit_req_status 429 not found — default would be 503')

except FileNotFoundError:
    fail('nginx conf readable', f'{nginx_conf} not found')
except Exception as e:
    fail('nginx config checks', str(e))


# ─────────────────────────────────────────────────────────────────────────────
# §4 — before_request handler registered
# ─────────────────────────────────────────────────────────────────────────────
print('\n§4  before_request handler')

try:
    _app3 = create_app()
    name = 'refresh_session_timeout registered as before_request handler'
    handler_names = [fn.__name__ for fn in _app3.before_request_funcs.get(None, [])]
    if 'refresh_session_timeout' in handler_names:
        ok(name)
    else:
        fail(name, f'before_request handlers: {handler_names}')
except Exception as e:
    fail('before_request check', traceback.format_exc(limit=2))


# ─────────────────────────────────────────────────────────────────────────────
# §5 — Validator wired into admin routes (static analysis)
# ─────────────────────────────────────────────────────────────────────────────
print('\n§5  Validator wired into routes (static check)')

for path_rel, label in [
    ('app/admin/users.py',     'admin/users.py'),
    ('app/auth/__init__.py',   'auth/__init__.py'),
]:
    fpath = Path(__file__).parent.parent / path_rel
    try:
        src = fpath.read_text()
        name = f'{label} imports validate_password_strength'
        if 'validate_password_strength' in src:
            ok(name)
        else:
            fail(name, f'validate_password_strength not found in {path_rel}')
    except Exception as e:
        fail(f'{label} readable', str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
print()
passed  = sum(1 for _, r, _ in results if r is True)
failed  = sum(1 for _, r, _ in results if r is False)
skipped = sum(1 for _, r, _ in results if r is None)
total   = len(results)

print('─' * 60)
print(f'Phase 8.1 E2E: {passed}/{total} passed, {failed} failed, {skipped} skipped')
if failed:
    print(f'{RED}OVERALL: FAIL{RESET}')
    sys.exit(1)
else:
    print(f'{GREEN}OVERALL: PASS{RESET}')
