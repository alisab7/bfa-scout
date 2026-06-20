"""
E2E — bulk position-assign screen (/admin/assign-positions).

Real Flask + real HTTP (NOT flask.test_client). Server on 127.0.0.1:5057.

  1  a position-less active player appears in the assign list
  2  a player who already HAS a position does NOT appear
  3  assigning a position sets primary_position_id (DB) + drops off the list
  4  after assigning, evaluate no longer redirects (GET ends on /evaluate, 200)
     (and BEFORE assigning it DID redirect to /edit)
  5  players left blank stay unassigned (still NULL, still listed)
  6  non-admin (scout) → 403; technical_director → 200 (admin + TD access)
  7  conn.commit() — change persists across a fresh request / direct DB read
"""
from __future__ import annotations

import os
import re
import sys
from urllib.request import build_opener, HTTPCookieProcessor, Request
from urllib.error import HTTPError
from http.cookiejar import CookieJar
from urllib.parse import urlencode

import psycopg2
import psycopg2.extras
from werkzeug.security import generate_password_hash
from dotenv import load_dotenv

sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent))

load_dotenv()
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
BASE = "http://127.0.0.1:5057"
PREFIX = "E2E-APOS"


def http(op, method, path, *, data=None):
    body = urlencode(data).encode() if data is not None else None
    req = Request(BASE + path, data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        r = op.open(req)
        return r.status, r.read().decode("utf-8", "replace"), r.url
    except HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), getattr(e, 'url', None)


def csrf_of(html):
    m = re.search(r'name=["\']csrf_token["\']\s+value=["\']([^"\']+)["\']', html)
    return m.group(1) if m else None


def login(email, pw):
    op = build_opener(HTTPCookieProcessor(CookieJar()))
    _, html, _ = http(op, "GET", "/auth/login")
    http(op, "POST", "/auth/login", data={"email": email, "password": pw, "csrf_token": csrf_of(html)})
    return op


def db():
    return psycopg2.connect(os.environ["DATABASE_URL"], cursor_factory=psycopg2.extras.RealDictCursor)


results = []
def chk(label, ok, ev=""):
    results.append((label, ok, ev))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}  {ev}")


PID = os.getpid()
SCOUT = (f"e2e-apos-scout-{PID}@bfa.bh", f"pw-{PID}", 'scout')
TD    = (f"e2e-apos-td-{PID}@bfa.bh",    f"pw-{PID}", 'technical_director')
INSERTED_USER_IDS = []
ids = {}

A = f"{PREFIX}-NoPosA"     # will be assigned
B = f"{PREFIX}-NoPosB"     # left blank → stays unassigned
POSITIONED = f"{PREFIX}-HasPos"   # already has a position → excluded from list


def cleanup():
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM players WHERE full_name LIKE %s", (f'{PREFIX}-%',))
        pids = [r['id'] for r in cur.fetchall()]
        if pids:
            cur.execute("DELETE FROM audit_log WHERE entity_type='player' AND entity_id = ANY(%s)", (pids,))
            cur.execute("DELETE FROM players WHERE id = ANY(%s)", (pids,))
        if INSERTED_USER_IDS:
            cur.execute("DELETE FROM users WHERE id = ANY(%s)", (INSERTED_USER_IDS,))
        conn.commit()


print("=== Setup ===")
cleanup()
with db() as conn, conn.cursor() as cur:
    for (email, pw, role) in (SCOUT, TD):
        cur.execute("""INSERT INTO users (email,password_hash,full_name,role,is_active)
                       VALUES (%s,%s,%s,%s,TRUE) RETURNING id""",
                    (email, generate_password_hash(pw, method='pbkdf2:sha256:600000'),
                     f'E2E APOS {role}', role))
        INSERTED_USER_IDS.append(cur.fetchone()['id'])
    cur.execute("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1")
    admin_id = cur.fetchone()['id']
    cur.execute("SELECT id FROM positions ORDER BY id LIMIT 1")
    POS_ID = cur.fetchone()['id']

    def mk(name, primary_pos):
        cur.execute("""INSERT INTO players (full_name, national_id, age_group,
                         primary_position_id, is_active, created_by)
                       VALUES (%s,%s,'senior',%s,TRUE,%s) RETURNING id""",
                    (name, f'APOS{abs(hash(name))%1000000}', primary_pos, admin_id))
        return cur.fetchone()['id']

    ids['A'] = mk(A, None)
    ids['B'] = mk(B, None)
    ids['POSITIONED'] = mk(POSITIONED, POS_ID)
    conn.commit()
print(f"  players={ids}, POS_ID={POS_ID}")


try:
    admin = login(os.environ["INITIAL_ADMIN_EMAIL"], os.environ["INITIAL_ADMIN_PASSWORD"])
    scout = login(*SCOUT[:2])
    td    = login(*TD[:2])

    print("\n=== access ===")
    s, _, _ = http(scout, "GET", "/admin/assign-positions")
    chk("6a scout GET → 403", s == 403, f"got {s}")
    s, _, _ = http(td, "GET", "/admin/assign-positions")
    chk("6b technical_director GET → 200 (admin+TD access)", s == 200, f"got {s}")

    print("\n=== list contents ===")
    s, list_html, _ = http(admin, "GET", "/admin/assign-positions")
    chk("1 position-less player A appears", A in list_html)
    chk("1b position-less player B appears", B in list_html)
    chk("2 already-positioned player does NOT appear", POSITIONED not in list_html)

    print("\n=== evaluate redirects BEFORE assignment ===")
    s, _, final = http(admin, "GET", f"/players/{ids['A']}/evaluate")
    chk("4-pre evaluate redirects to edit (no position yet)",
        final is not None and "/edit" in final, f"final={final}")

    print("\n=== assign A, leave B blank ===")
    tok = csrf_of(list_html)
    http(admin, "POST", "/admin/assign-positions",
         data={"csrf_token": tok,
               f"position_{ids['A']}": str(POS_ID),
               f"position_{ids['B']}": ""})   # B blank
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, primary_position_id FROM players WHERE id = ANY(%s)",
                    ([ids['A'], ids['B']],))
        rows = {r['id']: r['primary_position_id'] for r in cur.fetchall()}
    chk("3 player A primary_position_id set (DB)", rows[ids['A']] == POS_ID, f"got {rows[ids['A']]}")
    chk("5 player B left blank stays unassigned", rows[ids['B']] is None)

    print("\n=== list refresh + commit persistence ===")
    s, list_html2, _ = http(admin, "GET", "/admin/assign-positions")
    chk("3b assigned player A dropped off the list", A not in list_html2)
    chk("5b unassigned player B still on the list", B in list_html2)
    # fresh DB connection read (proves commit, not just same-txn visibility)
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT primary_position_id FROM players WHERE id=%s", (ids['A'],))
        chk("7 change persisted (fresh connection sees it)",
            cur.fetchone()['primary_position_id'] == POS_ID)

    print("\n=== evaluate works AFTER assignment ===")
    s, _, final = http(admin, "GET", f"/players/{ids['A']}/evaluate")
    chk("4 evaluate no longer redirects (200, ends on /evaluate)",
        s == 200 and final is not None and final.rstrip('/').endswith('/evaluate'),
        f"status={s} final={final}")

finally:
    print("\n(cleanup)")
    cleanup()
    print("  done")

print("\n" + "=" * 60)
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"Assign-positions E2E summary: {n_pass} pass / {n_fail} fail (of {len(results)})")
sys.exit(0 if n_fail == 0 else 2)
