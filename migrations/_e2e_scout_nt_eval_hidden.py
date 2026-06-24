"""
E2E — scout access boundary (security):
  Part A: NT-staff evaluations are INVISIBLE to scouts (and viewers) on every
          surface — no list entry, no count, and a direct URL behaves as
          not-found (404), NOT 403. admin/TD/nt_staff see everything.
  Part B: scouts CAN view /nt/residents, but NOT the senior /nt squad page.

Real Flask + real HTTP (NOT flask.test_client). Server on 127.0.0.1:5057.
"""
from __future__ import annotations

import os
import re
import sys
from datetime import date
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
PREFIX = "E2E-SNE"


def http(op, method, path, *, data=None):
    body = urlencode(data).encode() if data is not None else None
    req = Request(BASE + path, data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        r = op.open(req)
        return r.status, r.read().decode("utf-8", "replace"), r.url
    except HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), None


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
USERS = {
    'scout':  (f"e2e-sne-scout-{PID}@bfa.bh",  f"pw-{PID}", 'scout'),
    'td':     (f"e2e-sne-td-{PID}@bfa.bh",     f"pw-{PID}", 'technical_director'),
    'nt':     (f"e2e-sne-nt-{PID}@bfa.bh",     f"pw-{PID}", 'nt_staff'),
    'viewer': (f"e2e-sne-viewer-{PID}@bfa.bh", f"pw-{PID}", 'viewer'),
}
SCOUT_EVALUATOR = "E2E SNE ScoutEvaluator"
NT_EVALUATOR    = "E2E SNE NtEvaluator"
PLAYER = f"{PREFIX}-Player"
RESIDENT = f"{PREFIX}-Resident"
INSERTED_USER_IDS = []
INSERTED_PLAYER_IDS = []
ids = {}


def cleanup():
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM players WHERE full_name LIKE %s", (f'{PREFIX}-%',))
        pids = [r['id'] for r in cur.fetchall()]
        if pids:
            cur.execute("DELETE FROM evaluation_scores WHERE evaluation_id IN "
                        "(SELECT id FROM evaluations WHERE player_id = ANY(%s))", (pids,))
            cur.execute("DELETE FROM evaluations WHERE player_id = ANY(%s)", (pids,))
            cur.execute("DELETE FROM players WHERE id = ANY(%s)", (pids,))
        cur.execute("DELETE FROM users WHERE email LIKE %s", (f'e2e-sne-%-{PID}@bfa.bh',))
        cur.execute("DELETE FROM users WHERE full_name LIKE %s", (f'{"E2E SNE"}%',))
        conn.commit()


print("=== Setup ===")
cleanup()
with db() as conn, conn.cursor() as cur:
    for (email, pw, role) in USERS.values():
        cur.execute("""INSERT INTO users (email,password_hash,full_name,role,is_active)
                       VALUES (%s,%s,%s,%s,TRUE) RETURNING id""",
                    (email, generate_password_hash(pw, method='pbkdf2:sha256:600000'),
                     f'E2E SNE {role}', role))
        INSERTED_USER_IDS.append(cur.fetchone()['id'])
    # distinct evaluator users so we can detect their names on the profile
    cur.execute("""INSERT INTO users (email,password_hash,full_name,role,is_active)
                   VALUES (%s,%s,%s,'scout',TRUE) RETURNING id""",
                (f"e2e-sne-screval-{PID}@bfa.bh", generate_password_hash('x', method='pbkdf2:sha256:600000'),
                 SCOUT_EVALUATOR))
    scout_eval_uid = cur.fetchone()['id']
    cur.execute("""INSERT INTO users (email,password_hash,full_name,role,is_active)
                   VALUES (%s,%s,%s,'nt_staff',TRUE) RETURNING id""",
                (f"e2e-sne-nteval-{PID}@bfa.bh", generate_password_hash('x', method='pbkdf2:sha256:600000'),
                 NT_EVALUATOR))
    nt_eval_uid = cur.fetchone()['id']

    cur.execute("SELECT id, position_group_id FROM positions ORDER BY id LIMIT 1")
    pos = cur.fetchone()

    # senior player WITH a position (so the profile/eval surfaces render)
    cur.execute("""INSERT INTO players (full_name, national_id, age_group,
                     primary_position_id, is_active, created_by)
                   VALUES (%s,%s,'senior',%s,TRUE,%s) RETURNING id""",
                (PLAYER, f'SNE{PID%100000}', pos['id'], scout_eval_uid))
    ids['player'] = cur.fetchone()['id']
    INSERTED_PLAYER_IDS.append(ids['player'])

    # a foreign_residency player so /nt/residents has content
    cur.execute("""INSERT INTO players (full_name, national_id, age_group,
                     nationality_status, bahrain_residency_start_date,
                     is_active, created_by)
                   VALUES (%s,%s,'senior','foreign_residency','2018-01-01',TRUE,%s) RETURNING id""",
                (RESIDENT, f'SNR{PID%100000}', scout_eval_uid))
    INSERTED_PLAYER_IDS.append(cur.fetchone()['id'])

    def mk_eval(evaluator_uid, role):
        cur.execute("""INSERT INTO evaluations
                         (player_id, evaluator_id, position_group_id, status,
                          created_by_role, submitted_at)
                       VALUES (%s,%s,%s,'submitted',%s,NOW()) RETURNING id""",
                    (ids['player'], evaluator_uid, pos['position_group_id'], role))
        return cur.fetchone()['id']

    ids['scout_eval'] = mk_eval(scout_eval_uid, 'scout')
    ids['nt_eval']    = mk_eval(nt_eval_uid, 'nt_staff')
    conn.commit()
print(f"  player={ids['player']} scout_eval={ids['scout_eval']} nt_eval={ids['nt_eval']}")


try:
    scout  = login(*USERS['scout'][:2])
    td     = login(*USERS['td'][:2])
    nt     = login(*USERS['nt'][:2])
    viewer = login(*USERS['viewer'][:2])
    admin  = login(os.environ["INITIAL_ADMIN_EMAIL"], os.environ["INITIAL_ADMIN_PASSWORD"])

    # ── Part A: invisibility to scout ────────────────────────────
    print("\n=== Part A: NT eval hidden from scout ===")
    _, sprof, _ = http(scout, "GET", f"/players/{ids['player']}")
    chk("A1 scout profile shows the scout eval (evaluator visible)", SCOUT_EVALUATOR in sprof)
    chk("A2 scout profile does NOT show the NT eval (evaluator hidden)", NT_EVALUATOR not in sprof)
    chk("A3 scout history count = 1 ('1 on record')", "1 on record" in sprof,
        f"has '2 on record'={'2 on record' in sprof}")

    s, _, _ = http(scout, "GET", f"/evaluations/{ids['nt_eval']}")
    chk("A4 scout direct GET of NT eval → 404 (not 403, not 200)", s == 404, f"got {s}")
    s, _, _ = http(scout, "GET", f"/evaluations/{ids['scout_eval']}")
    chk("A5 scout direct GET of own scout eval → 200", s == 200, f"got {s}")

    # viewer also hidden
    s, _, _ = http(viewer, "GET", f"/evaluations/{ids['nt_eval']}")
    chk("A6 viewer direct GET of NT eval → 404", s == 404, f"got {s}")

    # ── admin / TD / nt_staff unchanged (both visible) ───────────
    print("\n=== admin/TD/nt_staff unchanged (both evals visible) ===")
    _, aprof, _ = http(admin, "GET", f"/players/{ids['player']}")
    chk("A7 admin profile shows BOTH evaluators", SCOUT_EVALUATOR in aprof and NT_EVALUATOR in aprof)
    chk("A8 admin history count = 2 ('2 on record')", "2 on record" in aprof)
    s, _, _ = http(admin, "GET", f"/evaluations/{ids['nt_eval']}")
    chk("A9 admin direct GET of NT eval → 200", s == 200, f"got {s}")
    s, _, _ = http(nt, "GET", f"/evaluations/{ids['nt_eval']}")
    chk("A10 nt_staff direct GET of NT eval → 200", s == 200, f"got {s}")
    _, tdprof, _ = http(td, "GET", f"/players/{ids['player']}")
    chk("A11 TD profile shows BOTH evaluators", SCOUT_EVALUATOR in tdprof and NT_EVALUATOR in tdprof)

    # ── Part B: residents access ─────────────────────────────────
    print("\n=== Part B: scout residents access (not senior /nt) ===")
    s, res_html, _ = http(scout, "GET", "/nt/residents")
    chk("B1 scout GET /nt/residents → 200", s == 200, f"got {s}")
    chk("B2 residents page renders eligibility content", RESIDENT in res_html or "Eligible" in res_html)
    s, _, _ = http(scout, "GET", "/nt")
    chk("B3 scout GET senior /nt → still 403 (not newly opened)", s == 403, f"got {s}")
    s, _, _ = http(viewer, "GET", "/nt/residents")
    chk("B4 viewer GET /nt/residents → 403 (not granted)", s == 403, f"got {s}")
    for name, op in [('admin', admin), ('td', td), ('nt_staff', nt)]:
        s, _, _ = http(op, "GET", "/nt/residents")
        chk(f"B5 {name} GET /nt/residents → 200 (unchanged)", s == 200, f"got {s}")

    # nav: scout sees Residents link, NOT National Team link
    _, home, _ = http(scout, "GET", "/")
    chk("B6 scout nav shows Residents link", "/nt/residents" in home)
    chk("B7 scout nav does NOT show senior National Team link",
        ">National Team<" not in home)

finally:
    print("\n(cleanup)")
    cleanup()
    print("  done")

print("\n" + "=" * 60)
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"Scout-NT-eval-hidden E2E summary: {n_pass} pass / {n_fail} fail (of {len(results)})")
print("SECURITY GATE: " + ("PASS" if n_fail == 0 else f"FAIL — {n_fail}"))
sys.exit(0 if n_fail == 0 else 2)
