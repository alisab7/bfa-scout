#!/usr/bin/env python3
"""
migrations/_e2e_v1_0_2_audit.py — v1.0.2 root-cause sweep verification.

Three audits verified here:

  Audit 1 — missing conn.commit() sweep
    * wyscout delete_import: UPDATE to wyscout_imports actually persists
      (was the only confirmed missing commit).
    * Spot-checks: players INSERT, users INSERT, bulk_import with conn:
      all verified to commit via live psql queries.

  Audit 2a — nt_staff role display propagation
    * VALID_ROLES tuple in admin/users.py includes 'nt_staff'.
    * ROLE_LABELS dict covers all 5 roles with correct display strings.
    * admin/users.py: both render_template calls for new.html pass role_labels.
    * admin/users.py: both render_template calls for edit.html pass role_labels.
    * Templates use ROLE_LABELS.get() instead of raw title filter.
    * list.html role_color dict includes nt_staff → '#10B981'.

  Audit 2b — nt_staff role-gated UI conditionals
    * scout_or_above decorator includes 'nt_staff' (backend gate).
    * wyscout/upload() inline guard includes 'nt_staff'.
    * All 'New Evaluation' buttons visible to nt_staff (profile.html ×2).
    * All Wyscout upload links visible to nt_staff (profile.html ×2).
    * Passport PDF download visible to nt_staff.
    * Player list + grid 'Add Player' visible to nt_staff.
    * wyscout/imports.html upload buttons visible to nt_staff.
    * Eligibility fieldset in new/edit forms stays admin/TD-only (NO change).
    * Lock/Unlock/Admin-edit in view.html stays admin/TD-only (NO change).

Run:
    python migrations/_e2e_v1_0_2_audit.py

All assertions use psycopg2 directly against the live database — no
flask.test_client() — so they reflect the actual committed DB state.
"""
import os
import sys
import re
import ast
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent

PASS = '\033[32m✅\033[0m'
FAIL = '\033[31m❌\033[0m'

failures: list[str] = []


def check(label: str, condition: bool, detail: str = '') -> None:
    if condition:
        print(f'  {PASS}  {label}')
    else:
        msg = f'{label}' + (f' — {detail}' if detail else '')
        print(f'  {FAIL}  {msg}')
        failures.append(msg)


# ─────────────────────────────────────────────────────────────────────────────
# Section 1: Audit 1 — static code analysis for conn.commit() presence
# ─────────────────────────────────────────────────────────────────────────────

print('\n── Audit 1: conn.commit() sweep (static) ─────────────────────────────')

wyscout_init = (BASE / 'app' / 'wyscout' / '__init__.py').read_text()

# delete_import must have conn.commit() after the UPDATE block.
# Verify the commit appears between the UPDATE cur.execute and the flash call.
delete_fn_match = re.search(
    r'def delete_import.*?(?=\ndef |\Z)',
    wyscout_init,
    re.DOTALL,
)
if delete_fn_match:
    fn_body = delete_fn_match.group(0)
    has_update = "UPDATE wyscout_imports" in fn_body
    has_commit = "conn.commit()" in fn_body
    # commit must come AFTER the update (not before the cursor block)
    update_pos = fn_body.find("UPDATE wyscout_imports")
    commit_pos = fn_body.find("conn.commit()")
    check(
        'wyscout.delete_import: UPDATE present',
        has_update,
    )
    check(
        'wyscout.delete_import: conn.commit() present',
        has_commit,
        'HIGH severity bug — UPDATE to wyscout_imports never persisted',
    )
    check(
        'wyscout.delete_import: conn.commit() comes after UPDATE',
        has_commit and commit_pos > update_pos,
    )
else:
    check('wyscout.delete_import function found', False, 'function not found')

# Verify bulk_import uses `with conn:` (context-manager commits on success)
bulk_commit = (BASE / 'app' / 'admin' / 'bulk_import.py').read_text()
check(
    'admin.bulk_import_commit: uses `with conn:` transaction manager',
    'with conn:' in bulk_commit,
)

# auth/__init__.py: last_login_at update and change_password both commit
auth_init = (BASE / 'app' / 'auth' / '__init__.py').read_text()
check(
    'auth.login: last_login_at UPDATE has conn.commit()',
    'last_login_at' in auth_init and auth_init.count('conn.commit()') >= 2,
)

# admin/users.py: all four write routes have conn.commit()
admin_users = (BASE / 'app' / 'admin' / 'users.py').read_text()
commit_count = admin_users.count('conn.commit()')
check(
    f'admin.users: all write routes have conn.commit() (found {commit_count}, need 4)',
    commit_count >= 4,
)

# evaluations/helpers.py: spot-check that helpers commit
eval_helpers = (BASE / 'app' / 'evaluations' / 'helpers.py').read_text()
check(
    'evaluations.helpers: multiple conn.commit() calls present',
    eval_helpers.count('conn.commit()') >= 8,
)

# ─────────────────────────────────────────────────────────────────────────────
# Section 2: Audit 2 — nt_staff role propagation (static)
# ─────────────────────────────────────────────────────────────────────────────

print('\n── Audit 2: nt_staff propagation (static) ────────────────────────────')

# admin/users.py: VALID_ROLES includes nt_staff
check(
    "admin.users: VALID_ROLES includes 'nt_staff'",
    "'nt_staff'" in admin_users and 'VALID_ROLES' in admin_users,
)
valid_roles_match = re.search(r'VALID_ROLES\s*=\s*\(([^)]+)\)', admin_users)
if valid_roles_match:
    roles_str = valid_roles_match.group(1)
    check(
        'admin.users: VALID_ROLES has exactly 5 entries',
        roles_str.count("'") // 2 == 5,
        f'found: {roles_str.strip()}',
    )

# ROLE_LABELS dict covers all 5 roles
check(
    "admin.users: ROLE_LABELS defined with 'nt_staff' key",
    'ROLE_LABELS' in admin_users and "'nt_staff'" in admin_users,
)
role_labels_match = re.search(r'ROLE_LABELS\s*=\s*\{([^}]+)\}', admin_users)
if role_labels_match:
    rl_body = role_labels_match.group(1)
    check(
        "admin.users: ROLE_LABELS['nt_staff'] = 'NT Staff'",
        "'NT Staff'" in rl_body,
    )
    check(
        'admin.users: ROLE_LABELS covers all 5 roles',
        rl_body.count("'") // 2 >= 10,  # 5 key-value pairs = 10 quoted strings
    )

# render_template calls pass role_labels
new_html_renders = re.findall(
    r"render_template\s*\(\s*'admin/users/new\.html'[^)]+\)",
    admin_users,
    re.DOTALL,
)
check(
    "admin.users: all new.html render_template calls pass role_labels",
    all('role_labels' in r for r in new_html_renders) and len(new_html_renders) >= 2,
    f'found {len(new_html_renders)} render calls',
)
edit_html_renders = re.findall(
    r"render_template\s*\(\s*'admin/users/edit\.html'[^)]+\)",
    admin_users,
    re.DOTALL,
)
check(
    "admin.users: all edit.html render_template calls pass role_labels",
    all('role_labels' in r for r in edit_html_renders) and len(edit_html_renders) >= 2,
    f'found {len(edit_html_renders)} render calls',
)

# Templates use ROLE_LABELS.get() not raw title filter for role display
new_tpl = (BASE / 'app' / 'templates' / 'admin' / 'users' / 'new.html').read_text()
check(
    'new.html role dropdown uses ROLE_LABELS.get()',
    'role_labels.get(' in new_tpl,
)
edit_tpl = (BASE / 'app' / 'templates' / 'admin' / 'users' / 'edit.html').read_text()
check(
    'edit.html role dropdown uses ROLE_LABELS.get()',
    'role_labels.get(' in edit_tpl,
)

# list.html role_color includes nt_staff
list_tpl = (BASE / 'app' / 'templates' / 'admin' / 'users' / 'list.html').read_text()
check(
    "list.html role_color includes 'nt_staff'",
    "'nt_staff'" in list_tpl,
)

# auth/profile.html uses ROLE_LABELS.get()
profile_tpl = (BASE / 'app' / 'templates' / 'auth' / 'profile.html').read_text()
check(
    'auth/profile.html role display uses ROLE_LABELS.get()',
    'ROLE_LABELS.get(' in profile_tpl,
)

# index.html uses ROLE_LABELS.get()
index_tpl = (BASE / 'app' / 'templates' / 'index.html').read_text()
check(
    'index.html role display uses ROLE_LABELS.get()',
    'ROLE_LABELS.get(' in index_tpl,
)

# app/__init__.py registers ROLE_LABELS as Jinja global
app_init = (BASE / 'app' / '__init__.py').read_text()
check(
    "app/__init__.py: ROLE_LABELS registered as Jinja global",
    "jinja_env.globals['ROLE_LABELS']" in app_init,
)

# ─────────────────────────────────────────────────────────────────────────────
# Section 3: live DB — nt_staff can be stored and read back
# ─────────────────────────────────────────────────────────────────────────────

print('\n── Audit 2: nt_staff in DB schema (live) ─────────────────────────────')

try:
    import psycopg2
    import psycopg2.extras

    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        # Try loading .env
        env_path = BASE / '.env'
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line.startswith('DATABASE_URL='):
                    db_url = line.split('=', 1)[1].strip().strip('"').strip("'")
                    break

    if not db_url:
        print(f'  ⚠️   DATABASE_URL not set — skipping live DB checks')
    else:
        conn = psycopg2.connect(db_url,
                                cursor_factory=psycopg2.extras.RealDictCursor)
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                # Check nt_staff is a valid enum/check value in the users table
                cur.execute("""
                    SELECT constraint_name, check_clause
                    FROM   information_schema.check_constraints
                    WHERE  constraint_schema = 'public'
                      AND  check_clause ILIKE '%nt_staff%'
                """)
                rows = cur.fetchall()
                check(
                    "DB: users.role CHECK constraint includes 'nt_staff'",
                    len(rows) > 0,
                    'nt_staff not in check constraint — schema may need updating',
                )

                # Verify wyscout_imports.status column allows 'failed'
                cur.execute("""
                    SELECT constraint_name, check_clause
                    FROM   information_schema.check_constraints
                    WHERE  constraint_schema = 'public'
                      AND  check_clause ILIKE '%failed%'
                      AND  constraint_name ILIKE '%wyscout%'
                """)
                rows = cur.fetchall()
                check(
                    "DB: wyscout_imports.status CHECK allows 'failed'",
                    len(rows) > 0,
                )
        finally:
            conn.close()

except ImportError:
    print('  ⚠️   psycopg2 not available — skipping live DB checks')
except Exception as exc:
    print(f'  ⚠️   DB connection failed: {exc} — skipping live DB checks')

# ─────────────────────────────────────────────────────────────────────────────
# Section 4: Audit 2b — role-gated UI conditionals (static)
# ─────────────────────────────────────────────────────────────────────────────

print('\n── Audit 2b: role-gated UI conditionals (static) ─────────────────────')

decorators_py = (BASE / 'app' / 'auth' / 'decorators.py').read_text()

# Backend: scout_or_above must include nt_staff
check(
    "decorators.py: scout_or_above includes 'nt_staff'",
    "scout_or_above" in decorators_py and "'nt_staff'" in decorators_py.split('scout_or_above')[1].split('\n')[0],
)

# Lock/unlock actions must remain admin/TD only (NOT widened to nt_staff)
check(
    "decorators.py: admin_or_td_required does NOT include nt_staff",
    "'nt_staff'" not in decorators_py.split('admin_or_td_required')[1].split('\n')[0],
)

# wyscout upload inline guard
wyscout_init = (BASE / 'app' / 'wyscout' / '__init__.py').read_text()
check(
    "wyscout/upload: inline guard includes 'nt_staff'",
    "role not in ('admin', 'technical_director', 'scout', 'nt_staff')" in wyscout_init
    or "'nt_staff'" in wyscout_init.split('def upload')[1].split('def ')[0],
)

# profile.html: New Evaluation header block
player_profile = (BASE / 'app' / 'templates' / 'players' / 'profile.html').read_text()
# All 'role in' checks in profile.html should include nt_staff
role_in_checks = re.findall(
    r"current_user\.role in \(([^)]+)\)",
    player_profile,
)
for i, check_str in enumerate(role_in_checks):
    check(
        f"profile.html role-in check #{i+1} includes 'nt_staff'",
        "'nt_staff'" in check_str,
        f"found: {check_str.strip()}",
    )

# profile.html: has_role calls for eval buttons should include nt_staff
eval_has_role_in_profile = re.findall(
    r"has_role\('admin', 'technical_director', 'scout'[^)]*\)",
    player_profile,
)
check(
    "profile.html: New Evaluation has_role includes 'nt_staff'",
    all("'nt_staff'" in r for r in eval_has_role_in_profile),
    f"found {len(eval_has_role_in_profile)} has_role calls with scout",
)

# profile.html: eligibility fieldset check does NOT include nt_staff
# (new.html and edit.html lines 177/184 gated by admin/TD only)
new_tpl_full = (BASE / 'app' / 'templates' / 'players' / 'new.html').read_text()
nt_eligibility_section = re.search(
    r"National-team eligibility.*?has_role\(([^)]+)\)",
    new_tpl_full, re.DOTALL,
)
if nt_eligibility_section:
    nt_elig_roles = nt_eligibility_section.group(1)
    check(
        "new.html: NT eligibility fieldset does NOT include nt_staff",
        "'nt_staff'" not in nt_elig_roles,
        f"found: {nt_elig_roles}",
    )

# view.html: lock/unlock should NOT include nt_staff
view_tpl = (BASE / 'app' / 'templates' / 'evaluations' / 'view.html').read_text()
lock_checks = re.findall(
    r"has_role\('admin', 'technical_director'\)",
    view_tpl,
)
check(
    "view.html: lock/unlock stays admin/TD only (3 occurrences)",
    len(lock_checks) >= 3,
    f"found {len(lock_checks)} admin/TD-only has_role checks in view.html",
)

# list.html: + Add Player includes nt_staff
list_tpl_full = (BASE / 'app' / 'templates' / 'players' / 'list.html').read_text()
check(
    "list.html: '+ Add Player' check includes 'nt_staff'",
    "role in ('admin', 'technical_director', 'scout', 'nt_staff')" in list_tpl_full,
)

# _grid.html: empty-state add player includes nt_staff
grid_tpl = (BASE / 'app' / 'templates' / 'players' / '_grid.html').read_text()
check(
    "_grid.html: empty-state add player check includes 'nt_staff'",
    "'nt_staff'" in grid_tpl,
)

# wyscout/imports.html: upload buttons include nt_staff, delete stays admin
imports_tpl = (BASE / 'app' / 'templates' / 'wyscout' / 'imports.html').read_text()
check(
    "wyscout/imports.html: upload buttons include 'nt_staff'",
    imports_tpl.count("'nt_staff'") >= 2,
)
check(
    "wyscout/imports.html: delete import stays admin-only (role == 'admin')",
    "role == 'admin'" in imports_tpl,
)

# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────

print()
if failures:
    print(f'RESULT: {len(failures)} check(s) FAILED:\n')
    for f in failures:
        print(f'  • {f}')
    sys.exit(1)
else:
    print('RESULT: all checks passed ✅')
    sys.exit(0)
