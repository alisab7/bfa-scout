"""
Suite B — Youth NT SECURITY boundary E2E (the HARD GATE).

youth_nt is the first RESTRICTED role: it must see ONLY youth players,
enforced at the QUERY level + real 403s (never hidden-UI-only). This
suite must pass 100% before commit.

Real Flask + real HTTP (NOT flask.test_client). Server on 127.0.0.1:5057.

Probes:
   1  youth_nt GET /players                  → 403
   2  youth_nt GET non-youth profile         → 403  (direct-URL probe)
   3  youth_nt GET youth profile             → 200  (positive control)
   4  youth_nt GET /nt                       → 403
   5  youth_nt GET /nt/residents             → 403
   6  youth_nt POST evaluate non-youth       → 403
   7  youth_nt POST edit non-youth           → 403
   8  youth_nt POST deactivate non-youth     → 403
   9  youth_nt cannot change age_group (promote a YOUTH player → ignored)
  10  youth_nt GET /admin/users              → 403
  11  youth_nt GET /players/new              → 403  (senior create)
  12  youth_nt GET /players/compare          → 403
  13  youth_nt GET passport PDF (non-youth)  → 403
  14  youth_nt GET /wyscout/imports/<senior> → 403
  15  youth_nt GET /reports /api /ai         → 403
  16  youth_nt GET non-youth player's eval   → 403  (direct eval-id probe)
  17  youth_nt sees ONLY youth in lists they CAN access (no senior leak)
  18  Promotion test: U23 reachable as youth → promote to senior → now 403
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


def http(op, method, path, *, data=None):
    body = urlencode(data).encode() if data is not None else None
    req = Request(BASE + path, data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        r = op.open(req)
        return r.status, r.read().decode("utf-8", errors="replace"), r.url
    except HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace"), None


def csrf_of(html: str) -> str | None:
    m = re.search(r'name=["\']csrf_token["\']\s+value=["\']([^"\']+)["\']', html)
    return m.group(1) if m else None


def login(email, pw):
    op = build_opener(HTTPCookieProcessor(CookieJar()))
    _, html, _ = http(op, "GET", "/auth/login")
    http(op, "POST", "/auth/login",
         data={"email": email, "password": pw, "csrf_token": csrf_of(html)})
    return op


def session_csrf(op) -> str | None:
    """Grab the session CSRF token from any authenticated page (the base
    template's logout form carries it). Flask-WTF tokens are session-bound,
    so this token is valid for any POST in this session — letting us probe
    a 403 without it being masked by a 400 CSRF rejection."""
    _, html, _ = http(op, "GET", "/youth/")
    return csrf_of(html)


def db():
    return psycopg2.connect(os.environ["DATABASE_URL"],
                            cursor_factory=psycopg2.extras.RealDictCursor)


results = []
def chk(label, ok, ev=""):
    results.append((label, ok, ev))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}  {ev}")


# ───────── Fixtures ────────────────────────────────────────────────
PID = os.getpid()
YOUTH_USER  = (f"e2e-ys-youth-{PID}@bfa.bh",  f"pw-youth-{PID}",  'youth_nt')
SCOUT_USER  = (f"e2e-ys-scout-{PID}@bfa.bh",  f"pw-scout-{PID}",  'scout')
INSERTED_USER_IDS: list[int] = []
INSERTED_PLAYER_IDS: list[int] = []
INSERTED_MATCH_IDS: list[int] = []

P_YOUTH  = f"E2EYS-{PID}-U23YOUTH"
P_SENIOR = f"E2EYS-{PID}-SENIOR"
P_PROMO  = f"E2EYS-{PID}-PROMO"

print("=== Setup fixtures ===")
with db() as conn, conn.cursor() as cur:
    for (email, pw, role) in (YOUTH_USER, SCOUT_USER):
        cur.execute("""INSERT INTO users (email, password_hash, full_name, role, is_active)
                       VALUES (%s,%s,%s,%s,TRUE) RETURNING id""",
                    (email, generate_password_hash(pw, method='pbkdf2:sha256:600000'),
                     f"E2E YS {role}", role))
        INSERTED_USER_IDS.append(cur.fetchone()['id'])
    cur.execute("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1")
    admin_id = cur.fetchone()['id']

    def mk_player(name, age_group, natid, pos=1):
        cur.execute("""
            INSERT INTO players (full_name, national_id, age_group,
                                 primary_position_id, is_active, created_by)
            VALUES (%s,%s,%s,%s,TRUE,%s) RETURNING id
        """, (name, natid, age_group, pos, admin_id))
        return cur.fetchone()['id']

    pid_youth  = mk_player(P_YOUTH,  'U23',    f"YS23{PID%100000}")
    pid_senior = mk_player(P_SENIOR, 'senior', f"YSSR{PID%100000}")
    pid_promo  = mk_player(P_PROMO,  'U23',    f"YSPR{PID%100000}")
    INSERTED_PLAYER_IDS += [pid_youth, pid_senior, pid_promo]

    cur.execute("""INSERT INTO matches (match_date, home_team, away_team, source, created_by)
                   VALUES (%s,%s,%s,'manual',%s) RETURNING id""",
                (date.today().isoformat(), "E2E Home", "E2E Away", admin_id))
    match_id = cur.fetchone()['id']
    INSERTED_MATCH_IDS.append(match_id)

    # A submitted evaluation on the SENIOR player (for the eval-id probe).
    cur.execute("SELECT position_group_id FROM positions WHERE id=1")
    pos_group_id = cur.fetchone()['position_group_id']
    cur.execute("""INSERT INTO evaluations
                     (player_id, evaluator_id, position_group_id, match_id,
                      status, created_by_role)
                   VALUES (%s,%s,%s,%s,'submitted','scout') RETURNING id""",
                (pid_senior, admin_id, pos_group_id, match_id))
    senior_eval_id = cur.fetchone()['id']
    conn.commit()
print(f"  users={INSERTED_USER_IDS}, players={INSERTED_PLAYER_IDS}, "
      f"senior_eval={senior_eval_id}")


try:
    youth_op = login(*YOUTH_USER[:2])
    tok = session_csrf(youth_op)

    # ── 1: general list ───────────────────────────────────────────
    print("\n=== Probes ===")
    s, _, _ = http(youth_op, "GET", "/players/")
    chk("1 youth_nt GET /players → 403", s == 403, f"got {s}")

    # ── 2-3: profile direct-URL probe ─────────────────────────────
    s, _, _ = http(youth_op, "GET", f"/players/{pid_senior}")
    chk("2 youth_nt GET non-youth profile → 403", s == 403, f"got {s}")
    s, _, _ = http(youth_op, "GET", f"/players/{pid_youth}")
    chk("3 youth_nt GET youth profile → 200 (positive control)", s == 200, f"got {s}")

    # ── 4-5: NT workspaces ────────────────────────────────────────
    s, _, _ = http(youth_op, "GET", "/nt"); chk("4 youth_nt GET /nt → 403", s == 403, f"got {s}")
    s, _, _ = http(youth_op, "GET", "/nt/residents"); chk("5 youth_nt GET /nt/residents → 403", s == 403, f"got {s}")

    # ── 6: evaluate non-youth (POST) ──────────────────────────────
    s, _, _ = http(youth_op, "POST", f"/players/{pid_senior}/evaluate",
                   data={"csrf_token": tok, "match_id": str(match_id), "action": "save_draft"})
    chk("6 youth_nt POST evaluate non-youth → 403", s == 403, f"got {s}")

    # ── 7: edit non-youth (POST) ──────────────────────────────────
    s, _, _ = http(youth_op, "POST", f"/players/{pid_senior}/edit",
                   data={"csrf_token": tok, "full_name": "HACK", "national_id": f"YSSR{PID%100000}"})
    chk("7 youth_nt POST edit non-youth → 403", s == 403, f"got {s}")

    # ── 8: deactivate non-youth (POST) ────────────────────────────
    s, _, _ = http(youth_op, "POST", f"/players/{pid_senior}/deactivate",
                   data={"csrf_token": tok})
    chk("8 youth_nt POST deactivate non-youth → 403", s == 403, f"got {s}")
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT is_active FROM players WHERE id=%s", (pid_senior,))
        still_active = cur.fetchone()['is_active']
    chk("8b senior player still active (deactivate had no effect)", still_active is True)

    # ── 9: youth_nt cannot promote a YOUTH player (age_group ignored) ─
    tok_y = csrf_of(http(youth_op, "GET", f"/players/{pid_youth}/edit")[1])
    http(youth_op, "POST", f"/players/{pid_youth}/edit",
         data={"csrf_token": tok_y, "full_name": P_YOUTH,
               "national_id": f"YS23{PID%100000}",
               "primary_position_id": "1", "age_group": "senior"})
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT age_group FROM players WHERE id=%s", (pid_youth,))
        ag = cur.fetchone()['age_group']
    chk("9 youth_nt cannot change age_group (stays U23)", ag == 'U23', f"ag={ag}")

    # ── 10: admin users ───────────────────────────────────────────
    s, _, _ = http(youth_op, "GET", "/admin/users"); chk("10 youth_nt GET /admin/users → 403", s == 403, f"got {s}")

    # ── 11: senior create ─────────────────────────────────────────
    s, _, _ = http(youth_op, "GET", "/players/new"); chk("11 youth_nt GET /players/new → 403", s == 403, f"got {s}")

    # ── 12: compare ───────────────────────────────────────────────
    s, _, _ = http(youth_op, "GET", "/players/compare"); chk("12 youth_nt GET /players/compare → 403", s == 403, f"got {s}")

    # ── 13: passport PDF ──────────────────────────────────────────
    s, _, _ = http(youth_op, "GET", f"/players/{pid_senior}/passport.pdf")
    chk("13 youth_nt GET non-youth passport → 403", s == 403, f"got {s}")

    # ── 14: wyscout ───────────────────────────────────────────────
    s, _, _ = http(youth_op, "GET", f"/wyscout/imports/{pid_senior}")
    chk("14 youth_nt GET wyscout non-youth → 403", s == 403, f"got {s}")

    # ── 15: stub blueprints ───────────────────────────────────────
    for path in ("/reports/", "/api/", "/ai/"):
        s, _, _ = http(youth_op, "GET", path)
        chk(f"15 youth_nt GET {path} → 403", s == 403, f"got {s}")

    # ── 16: eval-id direct probe (senior player's eval) ───────────
    s, _, _ = http(youth_op, "GET", f"/evaluations/{senior_eval_id}")
    chk("16 youth_nt GET non-youth eval → 403", s == 403, f"got {s}")

    # ── 17: no senior leak in accessible lists ────────────────────
    _, u23_html, _ = http(youth_op, "GET", "/youth/u23")
    chk("17a /youth/u23 shows the youth player", P_YOUTH in u23_html)
    chk("17b /youth/u23 does NOT leak the senior player", P_SENIOR not in u23_html)
    _, land_html, _ = http(youth_op, "GET", "/youth/")
    chk("17c youth landing does NOT leak senior player", P_SENIOR not in land_html)

    # ── 18: promotion removes youth_nt reachability ───────────────
    s_before, _, _ = http(youth_op, "GET", f"/players/{pid_promo}")
    chk("18a U23 promo player reachable by youth_nt BEFORE promotion (200)",
        s_before == 200, f"got {s_before}")
    with db() as conn, conn.cursor() as cur:  # admin promotes via DB
        cur.execute("UPDATE players SET age_group='senior' WHERE id=%s", (pid_promo,))
        conn.commit()
    s_after, _, _ = http(youth_op, "GET", f"/players/{pid_promo}")
    chk("18b after promotion to senior, youth_nt GET profile → 403",
        s_after == 403, f"got {s_after}")

finally:
    print("\n(cleanup)")
    with db() as conn, conn.cursor() as cur:
        if INSERTED_PLAYER_IDS:
            cur.execute("DELETE FROM evaluation_scores WHERE evaluation_id IN "
                        "(SELECT id FROM evaluations WHERE player_id = ANY(%s))",
                        (INSERTED_PLAYER_IDS,))
            cur.execute("DELETE FROM evaluations WHERE player_id = ANY(%s)", (INSERTED_PLAYER_IDS,))
        if INSERTED_MATCH_IDS:
            cur.execute("DELETE FROM matches WHERE id = ANY(%s)", (INSERTED_MATCH_IDS,))
        if INSERTED_PLAYER_IDS:
            cur.execute("DELETE FROM players WHERE id = ANY(%s)", (INSERTED_PLAYER_IDS,))
        if INSERTED_USER_IDS:
            cur.execute("DELETE FROM users WHERE id = ANY(%s)", (INSERTED_USER_IDS,))
        conn.commit()
    print(f"  cleaned {len(INSERTED_PLAYER_IDS)} players + {len(INSERTED_USER_IDS)} users")


print("\n" + "=" * 60)
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"Suite B summary: {n_pass} pass / {n_fail} fail (of {len(results)})")
print("HARD GATE: " + ("PASS — boundary holds" if n_fail == 0 else f"FAIL — {n_fail} leak(s)"))
sys.exit(0 if n_fail == 0 else 2)
