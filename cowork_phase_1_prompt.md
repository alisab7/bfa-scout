# Cowork Session: BFA-Scout Phase 1 — Auth & RBAC

## Context

Continuing the BFA-Scout build. Phase 0 (project scaffold) is committed. This session delivers complete authentication, role-based access control, and user management.

**Working folder:** `D:\BFA-Scout` (do NOT touch `D:\BFA-Analytics` or `D:\BFA-Analytics-AWS`).

**Attach to this session:**
- `project_brief.md` (current state in repo root)
- `PROJECT.md` + `CHANGELOG.md` (current state in repo root)

## Reference (do not copy-paste)

There is an existing auth system in `D:\BFA-Analytics-AWS\app.py` (BFA-Analytics) using Flask-Login + PBKDF2 + 3 roles. **Reference its patterns for inspiration only.** Key differences for THIS project:

| | BFA-Analytics | BFA-Scout |
|---|---|---|
| Roles | admin, coach, management (3) | admin, technical_director, scout, viewer (4) |
| User → domain link | `users.coach_id` FK to `coaches` | None — `users.id` is referenced directly by `evaluations.evaluator_id` |
| Scout role | doesn't exist | new — creates/edits own evaluations |

**Rebuild auth fresh against the BFA-Scout schema. Do not import or copy files from BFA-Analytics.**

## Goal of this session

End state:
- Login/logout works end-to-end
- 4 roles enforced via decorators across all blueprints
- Admin can create/edit/deactivate users via UI
- First-boot admin auto-seeded from env vars (one-time only)
- Last-active-admin guard prevents lockout
- All auth-relevant events logged to `audit_log`
- Sidebar shows current user + role badge + logout

**No business logic in other blueprints yet** — they remain placeholders, just protected with decorators.

## Stack additions

Add to `requirements.txt`:
- `Flask-Login==0.6.3`
- `Flask-WTF==1.2.1` (for CSRF protection only)
- `email-validator==2.1.0`

## Files to create/modify

```
app/
├── __init__.py                    [MODIFY] wire up Flask-Login + CSRFProtect
├── db.py                          [MODIFY] add seed_initial_admin() called on app start
├── auth/
│   ├── __init__.py                [REPLACE STUB] Blueprint with routes
│   ├── models.py                  [NEW] User class (Flask-Login UserMixin)
│   ├── decorators.py              [NEW] RBAC decorators
│   └── audit.py                   [NEW] log_audit() helper
├── admin/                         [NEW PACKAGE]
│   ├── __init__.py                [NEW] Blueprint registered at /admin
│   └── users.py                   [NEW] User CRUD routes
├── templates/
│   ├── base.html                  [MODIFY] add nav with user info + role badge
│   ├── auth/
│   │   ├── login.html             [NEW]
│   │   └── profile.html           [NEW] "My Profile" — edit name/phone/password
│   └── admin/
│       └── users/
│           ├── list.html          [NEW]
│           ├── new.html           [NEW]
│           └── edit.html          [NEW]
└── static/
    └── css/style.css              [MODIFY] add role badge colors

.env.example                       [MODIFY] add INITIAL_ADMIN_EMAIL, INITIAL_ADMIN_PASSWORD
```

## Implementation specifics

### `app/auth/models.py` — User class

```python
from flask_login import UserMixin
from . import audit  # for type hints

class User(UserMixin):
    """Lightweight wrapper around a row from the users table."""
    def __init__(self, row):
        self.id = row['id']
        self.email = row['email']
        self.full_name = row['full_name']
        self.full_name_ar = row.get('full_name_ar')
        self.role = row['role']
        self.phone = row.get('phone')
        self._is_active = row['is_active']
        self.last_login_at = row.get('last_login_at')

    # Flask-Login interface
    @property
    def is_active(self):
        return self._is_active

    def get_id(self):
        return str(self.id)

    # Convenience
    def has_role(self, *roles):
        return self.role in roles

    @classmethod
    def get_by_id(cls, user_id):
        # query users table, return User or None
        ...

    @classmethod
    def get_by_email(cls, email):
        ...
```

### `app/auth/decorators.py` — RBAC

```python
from functools import wraps
from flask import abort
from flask_login import current_user

def role_required(*allowed_roles):
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

# Convenience decorators
admin_required          = role_required('admin')
admin_or_td_required    = role_required('admin', 'technical_director')
scout_or_above          = role_required('admin', 'technical_director', 'scout')
any_authenticated       = role_required('admin', 'technical_director', 'scout', 'viewer')
```

Use these everywhere. **Never** write `if current_user.role == 'admin'` inline in routes.

### `app/auth/__init__.py` — Routes

Routes:
- `GET  /auth/login`        — render login.html (redirect to / if already authenticated)
- `POST /auth/login`        — validate creds, login_user(), update last_login_at, audit log, redirect to ?next or /
- `POST /auth/logout`       — logout_user(), audit log, redirect to /auth/login
- `GET  /auth/profile`      — render profile.html (any authenticated user, sees own profile)
- `POST /auth/profile`      — update own full_name, full_name_ar, phone (NOT email or role)
- `POST /auth/password`     — change own password (requires current password verification)

Login validation:
- Email format valid
- User exists, `is_active = true`
- Password verified via `werkzeug.security.check_password_hash`
- On failure: generic "Invalid credentials" (do not reveal which field failed)
- Audit log entry on both success AND failure (`auth.login.success`, `auth.login.failure`)

### `app/admin/users.py` — User CRUD

Routes (all `@admin_required`):
- `GET  /admin/users`               — list all users with role badges, active toggle
- `GET  /admin/users/new`           — form
- `POST /admin/users/new`           — create user, send temporary password (display once)
- `GET  /admin/users/<id>/edit`     — form
- `POST /admin/users/<id>/edit`     — update full_name, role, is_active, phone (NOT password — that's a separate flow)
- `POST /admin/users/<id>/reset-password` — generate new random password, display once, force change on next login (next-login flag deferred to v1.1; for v1 just display)
- `POST /admin/users/<id>/deactivate` — set is_active=false (NOT hard delete)

**Last-admin guard** — applies to all destructive admin actions:
```python
def is_last_active_admin(user_id):
    """True if user_id is the only remaining active admin."""
    # SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=true AND id != %s
    # Returns True if count == 0
```
Block these actions when `is_last_active_admin(user_id)` is True:
- Deactivating that user
- Changing their role away from 'admin'
- Self-deactivation regardless

Return user-visible error: "Cannot deactivate the last active administrator. Promote another user to admin first."

### `app/auth/audit.py` — Audit logging helper

```python
def log_audit(user_id, action, entity_type, entity_id=None, details=None, ip_address=None):
    """Insert a row into audit_log. Never raise — log audit failures to stderr."""
    # action examples: 'auth.login.success', 'auth.login.failure', 'auth.logout',
    #                  'auth.password.change', 'user.create', 'user.edit',
    #                  'user.deactivate', 'user.role.change'
```

Wrap in try/except — audit failure must NEVER block the action. Log to stderr if it fails.

### First-boot admin seed

In `app/db.py`, add `seed_initial_admin()` called from `init_app()` after schema is verified:

```python
def seed_initial_admin():
    """Create initial admin from env vars if no admin user exists in DB."""
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM users WHERE role='admin'")
        if cur.fetchone()['n'] > 0:
            return  # Already have an admin — env vars are ignored from now on

        email = os.environ.get('INITIAL_ADMIN_EMAIL')
        password = os.environ.get('INITIAL_ADMIN_PASSWORD')
        if not email or not password:
            app.logger.warning(
                'No admin user exists and INITIAL_ADMIN_EMAIL/PASSWORD not set. '
                'Set them in .env and restart to seed the first admin.'
            )
            return

        from werkzeug.security import generate_password_hash
        cur.execute("""
            INSERT INTO users (email, password_hash, full_name, role, is_active)
            VALUES (%s, %s, %s, 'admin', TRUE)
        """, (email, generate_password_hash(password, method='pbkdf2:sha256:600000'),
              'Initial Administrator'))
        conn.commit()
        app.logger.info(f'Seeded initial admin: {email}')
```

**Critical:** This runs ONCE — once an admin exists, `INITIAL_ADMIN_PASSWORD` is ignored forever. The env var is not a "reset password" backdoor.

### `app/__init__.py` — wire up Flask-Login + CSRF

```python
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect

login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please sign in to continue.'
csrf = CSRFProtect()

def create_app(config_class=Config()):
    app = Flask(__name__)
    app.config.from_object(config_class)

    login_manager.init_app(app)
    csrf.init_app(app)

    from .auth.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.get_by_id(int(user_id))

    # ... (rest of factory)
    # After db.init_app(app):
    with app.app_context():
        db.seed_initial_admin()
```

### Apply decorators to ALL existing blueprint stubs

Modify the 8 blueprint stubs from Phase 0:

| Blueprint | Decorator |
|---|---|
| `auth` | none on login/logout, `@login_required` on profile/password |
| `players` | `@any_authenticated` |
| `evaluations` | `@scout_or_above` |
| `criteria` | `@admin_required` |
| `wyscout` | `@admin_or_td_required` |
| `reports` | `@any_authenticated` |
| `ai` | `@scout_or_above` |
| `api` | per-route (defer to later phases) |

Index route `/` is public; redirects to `/auth/login` if not authenticated, otherwise renders dashboard placeholder.

`/health` remains public (no auth) — load balancers need it.

### `base.html` modifications

Top nav layout (mobile-first):
- Left: BFA crest + "BFA Scout" wordmark
- Right (when authenticated):
  - User name (truncate on mobile)
  - Role badge with color (see CSS below)
  - Hamburger → menu with: My Profile / [Admin: Users] / Logout

Role badge colors (in style.css):
```css
.role-admin              { background: #C8102E; color: white; }
.role-technical_director { background: #B5924C; color: #0E1116; }
.role-scout              { background: #3B82F6; color: white; }
.role-viewer             { background: #6B7280; color: white; }
```

### `.env.example` additions

```
INITIAL_ADMIN_EMAIL=admin@bfa.bh
INITIAL_ADMIN_PASSWORD=ChangeMeOnFirstLogin!
```

Add comment in `.env.example`:
```
# INITIAL_ADMIN_* are FIRST-BOOT ONLY.
# Once an admin exists in the database, these are ignored.
# To rotate the admin password, log in as that admin and use the change-password flow,
# or have another admin reset it from /admin/users.
```

## Acceptance criteria

Before ending the session, verify each item with `docker-compose restart web` + curl/browser. **Do not use Flask test_client — it re-imports the app and hides stale-process bugs.**

1. ✅ `docker-compose up --build` succeeds, no errors
2. ✅ Initial admin auto-seeded on first boot with email matching `INITIAL_ADMIN_EMAIL`. Verify: `docker-compose exec db psql -U bfa -d bfa_scout -c "SELECT email, role, is_active FROM users;"`
3. ✅ `curl -i http://localhost:5000/players/` returns 302 to `/auth/login` when not authenticated
4. ✅ Login flow: POST valid creds to `/auth/login` returns 302 + sets session cookie
5. ✅ After login, GET `/players/` returns 200 (placeholder content)
6. ✅ Logged in as scout, GET `/admin/users` returns 403
7. ✅ Logged in as admin, GET `/admin/users` returns 200 with the user list
8. ✅ Last-admin guard: try to deactivate the only admin → returns error, DB unchanged. Verify with: `SELECT count(*) FROM users WHERE role='admin' AND is_active=true;` (should remain 1)
9. ✅ Create a second user via `/admin/users/new` (role=scout), then log in as that scout. Verify they cannot access admin pages.
10. ✅ Audit log populated. Verify: `SELECT action, entity_type, entity_id FROM audit_log ORDER BY id DESC LIMIT 10;` shows login, user_create, etc.
11. ✅ Restart container, verify INITIAL_ADMIN_PASSWORD env var is now ignored (admin exists, no second seed)
12. ✅ All 8 placeholder blueprints redirect to login when accessed unauthenticated

## Hard rules (do not violate)

- ❌ NO copying files from BFA-Analytics. Reference patterns only, rebuild fresh.
- ❌ NO inline role checks like `if current_user.role == 'admin'`. Always use decorators.
- ❌ NO hard-deleting users. Always `is_active = false`. (Preserves FK integrity with evaluations.)
- ❌ NO env-var fallback for admin password after first boot. `INITIAL_ADMIN_PASSWORD` is one-shot.
- ❌ NO `cursor.execute(f"...{var}...")`. Parameterized queries only.
- ❌ NO `flask.test_client()` for verification — it re-imports and hides stale-Flask-process bugs. Always restart container + curl.
- ✅ All passwords hashed with `pbkdf2:sha256:600000`
- ✅ All RBAC enforcement via `@role_required` decorators
- ✅ Last-active-admin guard on every admin-state-changing action
- ✅ Audit log entry on every auth event (success AND failure for login)
- ✅ CSRF protection enabled on all POST forms via Flask-WTF
- ✅ After every code change to auth: `docker-compose restart web`, then verify via real curl

## Stale-Flask-process verification protocol

This bit us 3 times in BFA-Analytics. After ANY change to auth code:

```powershell
docker-compose restart web
docker-compose logs --tail=20 web   # confirm Flask started fresh
curl -i http://localhost:5000/auth/login   # verify response from real process
```

`flask.test_client()` will appear to work because it re-imports the app — but the running gunicorn workers still have stale function objects in memory. **Always test against the real process.**

## Out of scope (do NOT build in this session)

- Forgot password / email-based reset (v1.1)
- 2FA / MFA
- Session timeout / refresh tokens
- Rate limiting on login endpoint (Phase 8 deploy)
- Password complexity rules beyond min 8 chars
- Force-change-password-on-next-login flag (v1.1)
- API token auth for headless clients (later)
- Player CRUD (Phase 3)
- Any business logic in players/evaluations/criteria/wyscout/reports/ai blueprints

## Session discipline

- Target: 8–10 messages
- After every auth code change: `docker-compose restart web` + curl verify
- End by updating `PROJECT.md` (current phase = 1 complete, next = 2)
- End by appending to `CHANGELOG.md` (`v0.1.0 — Auth & RBAC`)
- Last action: print acceptance-criteria checklist with ✅/❌ per item
- After session ends, Ali commits from PowerShell:
  ```powershell
  git add -A
  git commit -m "Phase 1: Auth & RBAC — Flask-Login, 4 roles, user CRUD, audit log"
  ```
