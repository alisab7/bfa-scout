"""
Phase 7.1 verification — TD on /nt, viewer filtered from NT evals.

Phase 7 locked two design calls that have since flipped:

  Phase 7 default                Phase 7.1 (this verifier)
  ─────────────────────────      ─────────────────────────
  /nt: admin + nt_staff          /nt: admin + TD + nt_staff
  NT-filter: scout only          NT-filter: scout + viewer

Both flips are one-line decorator / helper edits — Phase 7's E2E was
written against the narrower contract, so this script tops up the
coverage. Stays small (4 cases): full regression of the 7 suite
still passes unchanged, so we don't need to retest everything.
"""
from __future__ import annotations

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

sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent))

load_dotenv()
BASE = "http://127.0.0.1:5057"


def http(op, method, path, *, data=None):
    body = urlencode(data).encode() if data is not None else None
    req = Request(BASE + path, data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        r = op.open(req)
        return r.status, r.read().decode('utf-8', errors='replace'), r.url
    except __import__('urllib').error.HTTPError as e:
        return e.code, e.read().decode('utf-8', errors='replace'), None


def login(email, pw):
    op = build_opener(HTTPCookieProcessor(CookieJar()))
    _, html, _ = http(op, "GET", "/auth/login")
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


# ───────── Fixtures ────────────────────────────────────────────────
TD_EMAIL     = f"e2e-71-td-{os.getpid()}@bfa.bh"
TD_PW        = f"e2e-71-td-pw-{os.getpid()}"
VIEW_EMAIL   = f"e2e-71-viewer-{os.getpid()}@bfa.bh"
VIEW_PW      = f"e2e-71-viewer-pw-{os.getpid()}"
NT_EMAIL     = f"e2e-71-nt-{os.getpid()}@bfa.bh"
NT_PW        = f"e2e-71-nt-pw-{os.getpid()}"

INSERTED_USER_IDS: list[int] = []
INSERTED_EVAL_IDS: list[int] = []

print("=== Setup fixtures ===")
with db() as conn, conn.cursor() as cur:
    for email, pw, role, name in [
        (TD_EMAIL,   TD_PW,   'technical_director', 'E2E-71 TD'),
        (VIEW_EMAIL, VIEW_PW, 'viewer',             'E2E-71 Viewer'),
        (NT_EMAIL,   NT_PW,   'nt_staff',           'E2E-71 NT'),
    ]:
        cur.execute("""INSERT INTO users (email, password_hash, full_name, role, is_active)
                       VALUES (%s, %s, %s, %s, TRUE) RETURNING id""",
                    (email,
                     generate_password_hash(pw, method='pbkdf2:sha256:600000'),
                     name, role))
        INSERTED_USER_IDS.append(cur.fetchone()['id'])
    conn.commit()
nt_user_id = INSERTED_USER_IDS[2]
print(f"  td_user_id={INSERTED_USER_IDS[0]}, "
      f"viewer_user_id={INSERTED_USER_IDS[1]}, nt_user_id={nt_user_id}")


# Insert a single NT-authored evaluation against Arthur (id=2) so we
# can verify the viewer filter hides it.
with db() as conn, conn.cursor() as cur:
    cur.execute("SELECT primary_position_id FROM players WHERE id=2")
    arthur_pos = cur.fetchone()['primary_position_id']
    pos_group_id = None
    if arthur_pos:
        cur.execute("SELECT position_group_id FROM positions WHERE id=%s",
                    (arthur_pos,))
        pos_group_id = cur.fetchone()['position_group_id']
    if not pos_group_id:
        cur.execute("SELECT id FROM position_groups ORDER BY id LIMIT 1")
        pos_group_id = cur.fetchone()['id']
    cur.execute("""
        INSERT INTO evaluations
            (player_id, evaluator_id, position_group_id, status,
             created_by_role, summary, nt_readiness_level, recommendation,
             submitted_at)
        VALUES (2, %s, %s, 'submitted', 'nt_staff',
                'PHASE 7.1 SENTINEL NT-only eval', 'senior', 'monitor',
                NOW())
        RETURNING id
    """, (nt_user_id, pos_group_id))
    INSERTED_EVAL_IDS.append(cur.fetchone()['id'])
    conn.commit()


try:
    # ── Case 1: TD can GET /nt (was 403 in 7.0; now 200) ───────────
    print("\n=== Case 1: TD access to /nt (widened) ===")
    td_op = login(TD_EMAIL, TD_PW)
    status, _, _ = http(td_op, "GET", "/nt/")
    chk("Case 1: TD GET /nt → 200 (widened from 403 in 7.0)",
        status == 200, f"got: {status}")

    # ── Case 2: TD sees /nt nav link on dashboard ───────────────────
    _, dash_td, _ = http(td_op, "GET", "/")
    chk("Case 2: TD dashboard has the /nt nav-link href",
        'href="/nt/"' in dash_td or 'href="/nt"' in dash_td)

    # ── Case 3: viewer's profile-page eval list omits NT eval ──────
    print("\n=== Case 3: viewer's player profile filters NT evals ===")
    view_op = login(VIEW_EMAIL, VIEW_PW)
    status, profile_html, _ = http(view_op, "GET", "/players/2")
    chk("Case 3a: viewer can view player profile (200)",
        status == 200)
    chk("Case 3b: viewer profile does NOT contain the NT sentinel",
        "PHASE 7.1 SENTINEL NT-only eval" not in profile_html,
        f"found at idx {profile_html.find('PHASE 7.1 SENTINEL')}"
        if "PHASE 7.1 SENTINEL" in profile_html else "")
    chk("Case 3c: viewer profile does NOT show 'role-nt' badge",
        'role-nt' not in profile_html)

    # ── Case 4: viewer's aggregate-helper call excludes NT eval ────
    print("\n=== Case 4: viewer's evaluation_aggregate excludes NT ===")
    from app import create_app
    from app.evaluations.helpers import (
        get_evaluation_count_active, get_player_evaluation_aggregate,
    )
    flask_app = create_app()
    with flask_app.app_context():
        n_view = get_evaluation_count_active(2, requesting_user_role='viewer')
        n_adm  = get_evaluation_count_active(2, requesting_user_role='admin')
    chk("Case 4a: viewer's count < admin's count "
        "(NT-only eval hidden from viewer)",
        n_view < n_adm, f"viewer={n_view}, admin={n_adm}")
    chk("Case 4b: gap is exactly 1 (the sentinel NT eval)",
        n_adm - n_view == 1, f"diff: {n_adm - n_view}")

    # ── Case 5 (bonus): admin-class still sees everything ──────────
    admin_op = login(os.environ["INITIAL_ADMIN_EMAIL"],
                     os.environ["INITIAL_ADMIN_PASSWORD"])
    _, admin_profile, _ = http(admin_op, "GET", "/players/2")
    chk("Case 5: admin still sees NT sentinel "
        "(only frontline roles get filtered)",
        "PHASE 7.1 SENTINEL NT-only eval" in admin_profile)


finally:
    # Cleanup — strict, in case any assertion fired mid-flight.
    with db() as conn, conn.cursor() as cur:
        if INSERTED_EVAL_IDS:
            cur.execute("DELETE FROM evaluation_scores WHERE evaluation_id = ANY(%s)",
                        (INSERTED_EVAL_IDS,))
            cur.execute("DELETE FROM evaluations WHERE id = ANY(%s)",
                        (INSERTED_EVAL_IDS,))
        if INSERTED_USER_IDS:
            cur.execute("DELETE FROM users WHERE id = ANY(%s)",
                        (INSERTED_USER_IDS,))
        conn.commit()
    print(f"\n(cleanup: deleted {len(INSERTED_EVAL_IDS)} evals + "
          f"{len(INSERTED_USER_IDS)} users)")


print("\n" + "=" * 60)
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"E2E summary: {n_pass} pass / {n_fail} fail (of {len(results)})")
sys.exit(0 if n_fail == 0 else 2)
