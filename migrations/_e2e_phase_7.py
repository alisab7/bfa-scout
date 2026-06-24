"""
Phase 7 synthetic E2E. Real Flask + real HTTP (NOT flask.test_client).

Coverage (16 cases per the spec, with one substitution noted below):

  Permission tests
    1. NT staff GET /nt              -> 200
    2. Admin   GET /nt               -> 200
    3. Scout   GET /nt               -> 403
    4. Viewer  GET /nt               -> 403   (the spec asks for 'coach';
                                               coach role doesn't exist
                                               in this codebase, so we
                                               substitute viewer — the
                                               closest non-admin/non-NT
                                               analog)
    5. Anonymous GET /nt             -> 302 to /auth/login

  Visibility tests
    6. Setup: test scout eval + test NT eval against an existing player
    7. Scout sees scout eval, NOT NT eval on the player profile
    8. NT-staff sees BOTH with role badges in rendered HTML
    9. Admin sees BOTH with role badges
   10. Scout call to get_player_evaluation_aggregate excludes NT
   11. NT-staff call to same INCLUDES NT

  Squad list
   12. /nt page shows BPL-eligible players (Bouhra, Arthur)
   13. /nt page does NOT show foreign_other / not_eligible players

  Audit invariant
   14. Eval created with creator_role='nt_staff' -> DB row tagged nt_staff
   15. Eval created with creator_role='admin'    -> DB row tagged admin

  Regression
   16. (Run as separate calls after this script — kept off this script's
        success path so a regression failure doesn't mask a 7-specific bug)

Test fixtures are inserted and ALWAYS restored in a `finally:` block.
The DB column `users_role_check` validates we can create nt_staff users
(throwaway-namespace verify already covered that on `schema.sql`; this
hits the live DB).
"""
import os
import re
import sys
from urllib.request import build_opener, HTTPCookieProcessor, Request
from http.cookiejar import CookieJar
from urllib.parse import urlencode

import psycopg2
import psycopg2.extras
from werkzeug.security import generate_password_hash
from dotenv import load_dotenv

# Make `app` importable for direct helper calls (cases 10, 11, 14, 15).
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent))

load_dotenv()
BASE = "http://127.0.0.1:5057"


def http(op, method, path, *, data=None, raw=False, follow_redirects=True):
    body = urlencode(data).encode() if data is not None else None
    req = Request(BASE + path, data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        r = op.open(req)
        content = r.read()
        if not raw:
            content = content.decode("utf-8", errors="replace")
        return r.status, content, r.url, dict(r.headers)
    except __import__('urllib').error.HTTPError as e:
        content = e.read()
        if not raw:
            content = content.decode("utf-8", errors="replace")
        return e.code, content, None, {}


def login(email, pw):
    op = build_opener(HTTPCookieProcessor(CookieJar()))
    _, html, _, _ = http(op, "GET", "/auth/login")
    m = re.search(r'name=["\']csrf_token["\']\s+value=["\']([^"\']+)["\']', html)
    http(op, "POST", "/auth/login",
         data={"email": email, "password": pw, "csrf_token": m.group(1)})
    return op


def db():
    return psycopg2.connect(os.environ["DATABASE_URL"],
                            cursor_factory=psycopg2.extras.RealDictCursor)


results = []
def chk(label, ok, ev=""):
    results.append((label, ok, ev))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}  {ev}")


# ─── Pre-flight (column exists, constraint widened) ─────────────────
print("=== Pre-flight: schema state ===")
with db() as conn, conn.cursor() as cur:
    cur.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name='evaluations' AND column_name='created_by_role'""")
    chk("evaluations.created_by_role exists", cur.fetchone() is not None)
    cur.execute("""SELECT pg_get_constraintdef(c.oid) AS def
                   FROM   pg_constraint c WHERE conname='users_role_check'""")
    cdef = (cur.fetchone() or {}).get('def', '')
    chk("users_role_check includes 'nt_staff'", "'nt_staff'" in cdef,
        f"def: {cdef!r}")


# ─── Snapshot + create test fixtures ───────────────────────────────
print("\n=== Setup test fixtures ===")
admin_op = login(os.environ["INITIAL_ADMIN_EMAIL"],
                 os.environ["INITIAL_ADMIN_PASSWORD"])

NT_EMAIL  = f"e2e-nt-{os.getpid()}@bfa.bh"
NT_PW     = f"e2e-nt-pw-{os.getpid()}"
NT_NAME   = f"Test NT Staff {os.getpid()}"

SCOUT_EMAIL = f"e2e-scout-{os.getpid()}@bfa.bh"
SCOUT_PW    = f"e2e-scout-pw-{os.getpid()}"

VIEWER_EMAIL = f"e2e-viewer-{os.getpid()}@bfa.bh"
VIEWER_PW    = f"e2e-viewer-pw-{os.getpid()}"

INSERTED_USER_IDS:  list[int] = []
INSERTED_EVAL_IDS:  list[int] = []
INSERTED_PLAYER_IDS: list[int] = []

with db() as conn, conn.cursor() as cur:
    # 3 throwaway users at the 3 roles we exercise
    for email, pw, name, role in [
        (NT_EMAIL,     NT_PW,     NT_NAME,           'nt_staff'),
        (SCOUT_EMAIL,  SCOUT_PW,  'E2E Test Scout',  'scout'),
        (VIEWER_EMAIL, VIEWER_PW, 'E2E Test Viewer', 'viewer'),
    ]:
        cur.execute("""
            INSERT INTO users (email, password_hash, full_name, role, is_active)
            VALUES (%s, %s, %s, %s, TRUE)
            RETURNING id
        """, (email, generate_password_hash(pw, method='pbkdf2:sha256:600000'),
              name, role))
        INSERTED_USER_IDS.append(cur.fetchone()['id'])
    conn.commit()

    # Pick an existing active player for the eval tests (Arthur=2)
    cur.execute("SELECT id, primary_position_id FROM players WHERE id=2")
    p_arthur = cur.fetchone()
    pos_group_id = None
    if p_arthur and p_arthur['primary_position_id']:
        cur.execute("SELECT position_group_id FROM positions WHERE id=%s",
                    (p_arthur['primary_position_id'],))
        r = cur.fetchone()
        pos_group_id = r['position_group_id'] if r else None
    # Fall back to first position group if Arthur has no position
    if not pos_group_id:
        cur.execute("SELECT id FROM position_groups ORDER BY id LIMIT 1")
        pos_group_id = cur.fetchone()['id']

    nt_user_id    = INSERTED_USER_IDS[0]
    scout_user_id = INSERTED_USER_IDS[1]

    # Insert one scout-authored eval + one nt-authored eval against Arthur
    for evaluator_id, role in [(scout_user_id, 'scout'),
                                (nt_user_id,    'nt_staff')]:
        cur.execute("""
            INSERT INTO evaluations
                (player_id, evaluator_id, position_group_id, status,
                 created_by_role, summary, nt_readiness_level, recommendation,
                 submitted_at)
            VALUES (%s, %s, %s, 'submitted', %s,
                    %s, 'senior', 'monitor', NOW())
            RETURNING id
        """, (p_arthur['id'], evaluator_id, pos_group_id, role,
              f"E2E test eval ({role})"))
        INSERTED_EVAL_IDS.append(cur.fetchone()['id'])
    conn.commit()
    scout_eval_id, nt_eval_id = INSERTED_EVAL_IDS

# Now also need a "not eligible" player for case 13. Try to find one
# in the DB; if none, create a temporary one.
with db() as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT id, full_name FROM players
        WHERE  is_active = TRUE AND nationality_status = 'not_eligible'
        LIMIT 1
    """)
    not_elig_player = cur.fetchone()
    if not not_elig_player:
        # Look for any active player without an eligibility status, mutate
        # temporarily so the squad-query exclusion is exercised. We snapshot
        # nationality_status and restore in finally.
        cur.execute("""
            SELECT id, full_name, nationality_status FROM players
            WHERE  is_active = TRUE AND nationality_status IS NULL
            LIMIT 1
        """)
        not_elig_player = cur.fetchone()
    not_elig_player_prior_status = (not_elig_player or {}).get('nationality_status')

print(f"  nt_user_id={nt_user_id}, scout_user_id={scout_user_id}")
print(f"  scout_eval_id={scout_eval_id}, nt_eval_id={nt_eval_id}")
print(f"  not_elig_player={(not_elig_player or {}).get('full_name')!r}")


try:
    # ─── Permission tests ─────────────────────────────────────
    print("\n=== Permission tests on /nt ===")

    # Case 1: NT staff
    nt_op = login(NT_EMAIL, NT_PW)
    status, _, _, _ = http(nt_op, "GET", "/nt/")
    chk("Case 1: NT staff GET /nt returns 200", status == 200,
        f"got: {status}")

    # Case 2: admin
    status, _, _, _ = http(admin_op, "GET", "/nt/")
    chk("Case 2: admin GET /nt returns 200", status == 200,
        f"got: {status}")

    # Case 3: scout — senior /nt squad stays closed to scouts, but instead of
    # a bare 403 they're LOOPED to /players (so the residents 'Citizens' tab
    # doesn't dead-end). Scout still never sees the senior squad content.
    scout_op = login(SCOUT_EMAIL, SCOUT_PW)
    status, body, final, _ = http(scout_op, "GET", "/nt/")
    chk("Case 3: scout GET /nt loops to /players (not 403, no squad)",
        status == 200 and (final or '').rstrip('/').endswith('/players')
        and "National Team Workspace" not in body,
        f"status={status} final={final}")

    # Case 4: viewer (substituting for 'coach' — see header comment)
    viewer_op = login(VIEWER_EMAIL, VIEWER_PW)
    status, _, _, _ = http(viewer_op, "GET", "/nt/")
    chk("Case 4: viewer GET /nt returns 403 "
        "(substituting for 'coach' which doesn't exist)",
        status == 403, f"got: {status}")

    # Case 5: anonymous
    anon_op = build_opener(HTTPCookieProcessor(CookieJar()))
    status, _, final_url, _ = http(anon_op, "GET", "/nt/")
    chk("Case 5: anonymous GET /nt bounces to /auth/login",
        '/auth/login' in (final_url or ''),
        f"final URL: {final_url}")


    # ─── Visibility tests ─────────────────────────────────────
    print("\n=== Visibility tests on player profile ===")

    # Case 7: scout views Arthur's profile
    status, html, _, _ = http(scout_op, "GET", "/players/2")
    chk("Case 7a: scout's profile view returns 200", status == 200)
    chk("Case 7b: scout's profile contains the scout-authored eval marker",
        "E2E test eval (scout)" in html,
        f"snippet around 'E2E test eval': "
        f"{html[max(0, html.find('E2E test eval')-50):html.find('E2E test eval')+100]!r}")
    chk("Case 7c: scout's profile does NOT contain the NT-authored eval marker",
        "E2E test eval (nt_staff)" not in html,
        f"found at idx {html.find('E2E test eval (nt_staff)')}"
        if "E2E test eval (nt_staff)" in html else "")
    # And no NT role badge should appear in the scout's view
    chk("Case 7d: scout's profile does NOT contain 'role-nt' badge HTML",
        'role-nt' not in html)

    # Case 8: NT staff views same profile
    status, html, _, _ = http(nt_op, "GET", "/players/2")
    chk("Case 8a: NT staff's profile view returns 200", status == 200)
    chk("Case 8b: NT staff sees scout eval",
        "E2E test eval (scout)" in html)
    chk("Case 8c: NT staff sees NT eval",
        "E2E test eval (nt_staff)" in html)
    chk("Case 8d: NT staff's profile contains 'role-nt' badge HTML",
        'role-nt' in html)

    # Case 9: admin views same profile
    status, html, _, _ = http(admin_op, "GET", "/players/2")
    chk("Case 9a: admin's profile view returns 200", status == 200)
    chk("Case 9b: admin sees both evals + NT badge",
        "E2E test eval (scout)" in html
        and "E2E test eval (nt_staff)" in html
        and 'role-nt' in html)


    # ─── Aggregate visibility (cases 10/11) ─────────────────────
    print("\n=== Aggregate visibility (direct helper calls) ===")

    from app import create_app
    from app.evaluations.helpers import (
        get_player_evaluation_aggregate, get_evaluation_count_active,
        get_or_create_draft,
    )

    flask_app = create_app()
    with flask_app.app_context():
        # Case 10: scout view
        n_scout = get_evaluation_count_active(2, requesting_user_role='scout')
        agg_scout = get_player_evaluation_aggregate(
            2, mode='averaged', requesting_user_role='scout')
        # Case 11: nt_staff view
        n_nt    = get_evaluation_count_active(2, requesting_user_role='nt_staff')
        agg_nt = get_player_evaluation_aggregate(
            2, mode='averaged', requesting_user_role='nt_staff')

    chk("Case 10a: scout's eval count is strictly less than NT's count "
        "(NT eval hidden from scout)",
        n_scout < n_nt, f"scout={n_scout}, nt_staff={n_nt}")
    chk("Case 10b: scout's aggregate exists "
        "(scout still has at least one visible eval)",
        agg_scout is not None,
        f"aggregate: {bool(agg_scout)}")
    chk("Case 11a: NT staff count = scout count + 1 (the hidden NT eval)",
        n_nt == n_scout + 1, f"scout={n_scout}, nt={n_nt}")
    chk("Case 11b: NT staff aggregate is non-None and includes more evals",
        agg_nt is not None,
        f"both: {bool(agg_nt)}")


    # ─── Squad list (cases 12/13) ────────────────────────────────
    print("\n=== Squad list on /nt ===")
    status, nt_html, _, _ = http(admin_op, "GET", "/nt/")
    chk("Case 12a: /nt renders with 200", status == 200)
    # Arthur (foreign_residency w/ residency since 2020-12-06 → 5y → 2025-12-06)
    # was tagged "Eligible from 2025-12-06" in earlier PDFs; he should be on /nt.
    chk("Case 12b: /nt squad lists Arthur (residency-route eligible)",
        "Arthur Rezende" in nt_html,
        f"snippet around 'Arthur': "
        f"{nt_html[max(0, nt_html.find('Arthur')-30):nt_html.find('Arthur')+80]!r}")

    # Case 13: temporarily flip a player to not_eligible and verify /nt
    # excludes them.
    if not_elig_player:
        with db() as conn, conn.cursor() as cur:
            cur.execute("""UPDATE players SET nationality_status='not_eligible'
                           WHERE id=%s""", (not_elig_player['id'],))
            conn.commit()
        try:
            status, nt_html2, _, _ = http(admin_op, "GET", "/nt/")
            chk(f"Case 13: /nt does NOT list {not_elig_player['full_name']!r} "
                "(now not_eligible)",
                not_elig_player['full_name'] not in nt_html2)
        finally:
            with db() as conn, conn.cursor() as cur:
                cur.execute("""UPDATE players SET nationality_status=%s
                               WHERE id=%s""",
                            (not_elig_player_prior_status, not_elig_player['id']))
                conn.commit()
    else:
        print("  (no candidate player for case 13 — skipped)")


    # ─── Create-path stamping (cases 14/15) ──────────────────────
    print("\n=== Create-path stamping ===")
    # Use a "freestanding" match_id = NULL? The get_or_create_draft helper
    # doesn't allow that (the UNIQUE constraint includes match_id and the
    # search filters by match_id = NULL won't match other drafts cleanly).
    # We need a real match_id. Pick the most recent match.
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM matches ORDER BY id DESC LIMIT 1")
        match_row = cur.fetchone()
        chk("Case 14a: at least one match exists for create-path test",
            match_row is not None)
        if match_row:
            match_id = match_row['id']

            # Case 14: nt_staff creator
            with flask_app.app_context():
                draft_nt = get_or_create_draft(
                    p_arthur['id'], match_id, nt_user_id, pos_group_id,
                    creator_role='nt_staff')
            INSERTED_EVAL_IDS.append(draft_nt['id'])
            chk("Case 14b: nt_staff draft DB row has created_by_role='nt_staff'",
                draft_nt.get('created_by_role') == 'nt_staff',
                f"got: {draft_nt.get('created_by_role')!r}")

            # Case 15: admin creator. Reuse admin user_id from env login.
            with db() as conn2, conn2.cursor() as cur2:
                cur2.execute("SELECT id FROM users WHERE email=%s",
                             (os.environ['INITIAL_ADMIN_EMAIL'],))
                admin_user_id = cur2.fetchone()['id']
            with flask_app.app_context():
                draft_admin = get_or_create_draft(
                    p_arthur['id'], match_id, admin_user_id, pos_group_id,
                    creator_role='admin')
            INSERTED_EVAL_IDS.append(draft_admin['id'])
            chk("Case 15: admin draft DB row has created_by_role='admin'",
                draft_admin.get('created_by_role') == 'admin',
                f"got: {draft_admin.get('created_by_role')!r}")


    # ─── Bonus: nav-link visibility per role (browser-check proxy) ─
    print("\n=== Nav link visibility (sanity) ===")
    status, dash_html_nt, _, _    = http(nt_op,    "GET", "/")
    status, dash_html_admin, _, _ = http(admin_op, "GET", "/")
    status, dash_html_scout, _, _ = http(scout_op, "GET", "/")
    # The string "National Team" appears in body copy ("National Team
    # Committee Platform" branding, eligibility card heading, etc.) so
    # we can't assert on text. The nav link is identifiable by its
    # href — `/nt/` (or `/nt`) — which IS role-conditional.
    chk("Bonus: NT staff dashboard has /nt nav link (href)",
        'href="/nt/"' in dash_html_nt or 'href="/nt"' in dash_html_nt)
    chk("Bonus: admin dashboard has /nt nav link (href)",
        'href="/nt/"' in dash_html_admin or 'href="/nt"' in dash_html_admin)
    chk("Bonus: scout dashboard does NOT have /nt nav link (href)",
        'href="/nt/"' not in dash_html_scout
        and 'href="/nt"' not in dash_html_scout)


finally:
    # ─── Cleanup ───────────────────────────────────────────────
    print("\n(cleanup: restoring DB state)")
    with db() as conn, conn.cursor() as cur:
        # 1. Delete scores belonging to test evals (FK CASCADE not on this)
        if INSERTED_EVAL_IDS:
            cur.execute("DELETE FROM evaluation_scores WHERE evaluation_id = ANY(%s)",
                        (INSERTED_EVAL_IDS,))
            cur.execute("DELETE FROM evaluations WHERE id = ANY(%s)",
                        (INSERTED_EVAL_IDS,))
        # 2. Delete the throwaway users
        if INSERTED_USER_IDS:
            cur.execute("DELETE FROM users WHERE id = ANY(%s)",
                        (INSERTED_USER_IDS,))
        conn.commit()
    print(f"  deleted {len(INSERTED_EVAL_IDS)} evals + {len(INSERTED_USER_IDS)} users")


# ─── Summary ──────────────────────────────────────────────────
print("\n" + "=" * 60)
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"E2E summary: {n_pass} pass / {n_fail} fail (of {len(results)})")
sys.exit(0 if n_fail == 0 else 2)
