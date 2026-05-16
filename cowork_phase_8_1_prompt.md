# Cowork/Claude Code Session: BFA-Scout Phase 8.1 — Security Hardening (Pre-BFA Launch)

## Context

Twenty-two phases on master. Production deploy live. Before BFA staff access the tool, four security items need to land. Three are Cowork patches (~80min total). One is Ali-on-the-droplet (~5min).

This is a hardening patch, not a feature phase. Conservative scope, no behavioral surprises.

**Working folder:** `D:\BFA-Scout`.

## Four items in this patch

| # | Item | Effort | Actor |
|---|---|---|---|
| 1 | Rotate admin password + remove from .env.production | 5 min | Ali (on droplet) |
| 2 | Nginx rate limit on /auth/login | 20 min | Cowork |
| 3 | Password complexity validation | 30 min | Cowork |
| 4 | Session timeout (8hr idle) | 20 min | Cowork |

Total Cowork ~70min + Ali ~5min.

## Pre-flight gates

```powershell
git log --oneline | Select-Object -First 1   # expect: Phase 8
git status                                    # expect: clean
```

## Item 2 — Nginx rate limit on /auth/login

### Why

Without rate limiting, an attacker can brute-force the admin password indefinitely. Hash time (PBKDF2 600k iterations) slows it down but doesn't prevent it. Nginx layer is the right place — applies before any application logic, can't be bypassed.

### Implementation

Edit `nginx/conf.d/bfa-scout.conf`:

At the top of the file, before any `server { }` block, add:

```nginx
# Rate limit for login attempts: 10/minute per IP, with burst of 5
limit_req_zone $binary_remote_addr zone=login_zone:10m rate=10r/m;

# Optional: rate limit for password reset / forgot-password flows (when added)
# limit_req_zone $binary_remote_addr zone=reset_zone:10m rate=3r/m;
```

Inside the HTTPS server block, add a location-specific rule for `/auth/login`:

```nginx
location /auth/login {
    limit_req zone=login_zone burst=5 nodelay;
    limit_req_status 429;

    proxy_pass http://app:5000/auth/login;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_read_timeout 60s;
}
```

The general `location /` block stays the same — only `/auth/login` is rate-limited.

### Behavior

- First 10 attempts/minute per IP: pass through normally
- Attempts 11-15 (burst): queued, no delay
- Attempts 16+: rejected with HTTP 429 Too Many Requests

### Verification

After deploy:
1. Visit `/auth/login`, enter wrong credentials, repeat 11 times in quick succession
2. 11th+ attempt should return 429 (not 401)
3. Wait 60 seconds, attempt again — should be allowed

### Documentation

Add to `DEPLOY.md` troubleshooting section: "If legitimate users get 429 errors, the rate limit may be too aggressive. Check nginx logs for `limit_req` warnings, consider increasing rate or burst."

## Item 3 — Password complexity validation

### Why

Without complexity rules, admin can create user accounts with `password123` or similar. Real-world BFA may have non-tech-savvy users who would default to weak passwords.

### Locked policy

- Minimum 12 characters
- Must contain: at least 1 lowercase letter, 1 uppercase letter, 1 digit
- (Special character optional — too restrictive in practice)
- Maximum 128 characters (DoS prevention)

### Implementation

Create a new validator in `app/auth/validators.py` (or wherever existing validators live):

```python
import re

def validate_password_strength(password: str) -> tuple[bool, str]:
    """Returns (is_valid, error_message_or_empty).
    Policy:
    - Min 12 chars
    - At least one lowercase, uppercase, digit
    - Max 128 chars (DoS prevention)
    """
    if not password:
        return False, 'Password is required'
    if len(password) < 12:
        return False, 'Password must be at least 12 characters'
    if len(password) > 128:
        return False, 'Password must be at most 128 characters'
    if not re.search(r'[a-z]', password):
        return False, 'Password must contain at least one lowercase letter'
    if not re.search(r'[A-Z]', password):
        return False, 'Password must contain at least one uppercase letter'
    if not re.search(r'\d', password):
        return False, 'Password must contain at least one digit'
    return True, ''
```

### Apply to existing flows

Find all places that set passwords. Likely candidates:
- `app/auth/__init__.py` — user creation flow (admin-only)
- `app/admin/users/__init__.py` or similar — admin password reset flow
- Any user-facing "change my password" form (if it exists)

In each handler, before hashing:

```python
from app.auth.validators import validate_password_strength

is_valid, err = validate_password_strength(new_password)
if not is_valid:
    flash(err, 'error')
    return redirect(url_for('admin.users.create'))
```

### Template UX

In the user creation form (`app/templates/admin/users/_form.html` or similar), add hint text near the password input:

```html
<label class="block text-sm font-medium mb-1">Password</label>
<input type="password" name="password" minlength="12" maxlength="128" required>
<p class="text-xs text-muted mt-1">
  Minimum 12 characters. Must include uppercase, lowercase, and digits.
</p>
```

The `minlength` HTML5 attribute provides front-end hint; server-side validation is the source of truth.

### What NOT to do

- Do NOT enforce on existing passwords — they're already hashed, can't re-validate
- Do NOT block bootstrap admin (`scripts/bootstrap_admin.py`) — that runs once with env-var-provided password; trust the env
- Do NOT add password expiry / forced rotation — adds UX friction without proportional security gain

### Verification

In `migrations/_e2e_phase_8_1.py`:

```python
def test_password_validator():
    cases = [
        ('Sh0rt', False, 'too short'),
        ('alllowercase12345', False, 'no uppercase'),
        ('ALLUPPERCASE12345', False, 'no lowercase'),
        ('NoNumbersHere!', False, 'no digit'),
        ('Valid_Password_12', True, 'meets all rules'),
        ('a' * 200, False, 'too long'),
        ('', False, 'empty'),
    ]
    for pwd, expected_valid, desc in cases:
        is_valid, _ = validate_password_strength(pwd)
        assert is_valid == expected_valid, f'{desc}: expected {expected_valid}'
```

Plus integration test: create user with weak password via admin UI → should fail validation, no user created.

## Item 4 — Session timeout (8hr idle)

### Why

Sessions today are permanent. If a scout logs in on a shared device and walks away, the session stays valid indefinitely. 8 hours idle is enough for a normal workday but forces re-login overnight.

### Implementation

In `app/__init__.py`, add to Flask app config:

```python
from datetime import timedelta

app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)
app.config['SESSION_COOKIE_SECURE'] = True   # Only over HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True  # No JS access
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # CSRF mitigation
```

Add a request handler that refreshes session lifetime on each request:

```python
@app.before_request
def refresh_session_timeout():
    """Sliding window — each request resets the 8hr countdown.
    User must idle for 8hr to be logged out."""
    from flask import session
    session.permanent = True
    session.modified = True
```

`SESSION_COOKIE_SECURE=True` requires HTTPS — production is HTTPS via Cloudflare, so OK. In dev (HTTP), this would block sessions; either set to False in dev or trust the env.

Make it env-aware:

```python
app.config['SESSION_COOKIE_SECURE'] = (os.environ.get('FLASK_ENV') == 'production')
```

### Verification

- Login as admin
- Idle (no requests) for 8+ hours
- Next request → redirected to login
- Login again → fresh session, no error

For tests, use a shorter timeout temporarily and verify the behavior.

### Behavior tradeoffs

- 8hr is conservative — most office workdays are <8hr
- "Idle" = no requests; opening a tab and not clicking still counts as idle (sessions don't auto-refresh from open tabs)
- Existing sessions may be cut shorter when this deploys — minor inconvenience, not a bug

### What NOT to do

- Do NOT add a "session expires in X minutes" warning popup — feature creep
- Do NOT implement absolute session lifetime separately — sliding window is enough
- Do NOT log session timeouts to audit_log — too noisy

## Item 1 — Admin password rotation (Ali on droplet)

This is NOT a Cowork item. After Cowork's patches are committed and deployed:

```bash
# 1. SSH into droplet
ssh -i your-key root@164.90.181.13

# 2. Login to live app at https://<domain>/auth/login with current admin creds
# 3. Go to /admin/users, find admin user, change password to a strong new one
#    (must now pass the new 12-char complexity rule)

# 4. SSH into droplet, edit .env.production
cd /home/bfa/bfa-scout
nano .env.production

# 5. Comment out or remove these lines:
# ADMIN_EMAIL=admin@bfa.bh
# ADMIN_PASSWORD=<bootstrap-value>

# 6. Restart app container to apply env changes:
docker compose -f docker-compose.prod.yml restart app

# 7. Verify bootstrap script no-ops:
docker exec bfa-scout_app_1 python scripts/bootstrap_admin.py
# Expected: "Admin user already exists" or similar — no new user, no password reset
```

Document this in CHANGELOG as the post-deploy step Ali completes.

## Files to create / modify (Cowork-side)

```
app/__init__.py                          [MODIFY] Session timeout config + before_request handler
app/auth/validators.py                   [NEW or MODIFY] Add validate_password_strength()
app/auth/__init__.py                     [MODIFY] Apply password validation to user creation flow
app/admin/users/__init__.py              [MODIFY if exists] Apply password validation to admin password reset
app/templates/admin/users/_form.html     [MODIFY if exists] Add minlength + hint text
nginx/conf.d/bfa-scout.conf              [MODIFY] Add limit_req_zone + login rate limit
DEPLOY.md                                [MODIFY] Add troubleshooting section for 429 on /auth/login
CHANGELOG.md                             [APPEND] v1.0.1 entry
migrations/_e2e_phase_8_1.py             [NEW] Test password validator + session config presence
PROJECT.md                               [UPDATE] Mark 8.1 complete; queue 8.2 (items 5-6) for v1.1
```

## Verification

### E2E — `migrations/_e2e_phase_8_1.py`

Cover:
1. Password validator: 7 cases (short, no-upper, no-lower, no-digit, valid, too-long, empty)
2. Session config: `PERMANENT_SESSION_LIFETIME == timedelta(hours=8)` is set
3. SESSION_COOKIE_HTTPONLY is True
4. Create user via admin UI with weak password → 400/redirect with error
5. Create user via admin UI with strong password → 201/redirect with success
6. Existing admin login still works (no regression)

### Regression

All prior E2E suites must still pass:
- 4.2, 5d-1, 6.0, 6.1, 6.2, 6.2.1, 7, 7.1, 9, 8 (where applicable)

### Manual verification

Post-deploy on the droplet:
1. Login flow works
2. Rate limit kicks in after 10 attempts/minute
3. User creation with weak password rejected
4. User creation with strong password succeeds
5. Session times out after 8 hours of idle

## Acceptance criteria

- ✅ Pre-flight gates pass
- ✅ Nginx config has `limit_req_zone` and `/auth/login` is rate-limited (10/min, 5 burst)
- ✅ `validate_password_strength()` exists and validates per the 12-char policy
- ✅ Admin user creation form applies validation
- ✅ Admin password reset form applies validation (if it exists)
- ✅ Flask config has `PERMANENT_SESSION_LIFETIME = timedelta(hours=8)`
- ✅ `before_request` handler refreshes session lifetime
- ✅ `SESSION_COOKIE_SECURE = True` in production, `False` in dev
- ✅ `SESSION_COOKIE_HTTPONLY = True`
- ✅ `SESSION_COOKIE_SAMESITE = 'Lax'`
- ✅ E2E PASS (all cases)
- ✅ All prior E2E suites still pass
- ✅ DEPLOY.md documents the rate limit + Ali's manual rotation steps
- ✅ CHANGELOG v1.0.1 entry

## Hard rules

- ❌ Do NOT modify schema (no DB migration)
- ❌ Do NOT modify the bootstrap_admin script (it's already idempotent)
- ❌ Do NOT enforce password complexity retroactively on existing hashes
- ❌ Do NOT add CSRF, 2FA, or password reset email here (items 5-6, deferred)
- ❌ Do NOT add session warning popups
- ❌ Do NOT add audit log entries for session timeouts (too noisy)
- ❌ Do NOT change session storage backend (Flask default is fine)
- ❌ Do NOT use flask.test_client() for verification — restart real Flask + real HTTP
- ❌ Do NOT initialize git or commit — Ali commits manually
- ❌ Do NOT touch `D:\BFA-Analytics` or `D:\BFA-Analytics-AWS`
- ✅ Snapshot+restore any test users in E2E
- ✅ Append v1.0.1 entry to CHANGELOG.md
- ✅ Mark 8.1 complete in PROJECT.md; queue 8.2 (items 5-6) for v1.1

## Out of scope

- 2FA / MFA (deferred — Phase 8.2 v1.1)
- Password reset email flow (deferred — Phase 8.2 v1.1)
- CSP headers (deferred — v1.2 polish)
- IP allowlist for admin accounts (deferred)
- Account lockout after N failed attempts (rate limit handles this at the IP layer for now)
- Audit log view UI (deferred — v1.2)

## Commit

```powershell
cd D:\BFA-Scout
git add -A
git commit -m "Phase 8.1: Security hardening (nginx rate limit, password complexity, session timeout)"
```

## Post-deploy procedure (Ali, after commit + deploy)

1. Pull commit on droplet: `cd /home/bfa/bfa-scout && git pull origin master`
2. Rebuild: `docker compose -f docker-compose.prod.yml build app`
3. Restart: `docker compose -f docker-compose.prod.yml up -d`
4. Verify nginx reload: `docker compose -f docker-compose.prod.yml restart nginx`
5. Item 1 manual step (admin password rotation + remove from .env)

After all 4 items: BFA-Scout is genuinely hardened for production use. Items 5-6 ship as v1.1 within first month of usage.
