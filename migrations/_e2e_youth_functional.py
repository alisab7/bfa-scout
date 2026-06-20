"""
Suite A — Youth NT functional E2E.

Real Flask + real HTTP (NOT flask.test_client). Snapshot/cleanup all
fixtures. Server must be running on 127.0.0.1:5057.

Cases (spec Suite A):
   1  age_group column exists + CHECK constraint enforced
   2  youth player appears in its correct /youth/<group> sub-view
   3  youth player does NOT appear in the general /players list
   4  admin / TD / nt_staff / scout can view the youth section;
      viewer is excluded (403); youth_nt can view it
   5  nt_staff can change a player's age_group (promotion); promoted-to-
      senior leaves the youth view AND appears on the general list;
      scout CANNOT change age_group (field ignored)
   6  youth_nt can CRUD + evaluate a youth player
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


def get_csrf(op, path) -> str | None:
    _, html, _ = http(op, "GET", path)
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
USERS = {
    'td':       (f"e2e-yf-td-{PID}@bfa.bh",     f"pw-td-{PID}",     'technical_director'),
    'scout':    (f"e2e-yf-scout-{PID}@bfa.bh",  f"pw-scout-{PID}",  'scout'),
    'nt':       (f"e2e-yf-nt-{PID}@bfa.bh",     f"pw-nt-{PID}",     'nt_staff'),
    'viewer':   (f"e2e-yf-viewer-{PID}@bfa.bh", f"pw-viewer-{PID}", 'viewer'),
    'youth':    (f"e2e-yf-youth-{PID}@bfa.bh",  f"pw-youth-{PID}",  'youth_nt'),
}
INSERTED_USER_IDS: list[int] = []
INSERTED_PLAYER_IDS: list[int] = []
INSERTED_MATCH_IDS: list[int] = []

P_U17    = f"E2EYF-{PID}-U17"
P_U20    = f"E2EYF-{PID}-U20"
P_U23    = f"E2EYF-{PID}-U23"
P_SENIOR = f"E2EYF-{PID}-SENIOR"
P_NEW    = f"E2EYF-{PID}-NEWBYYOUTH"

print("=== Setup fixtures ===")
with db() as conn, conn.cursor() as cur:
    for key, (email, pw, role) in USERS.items():
        cur.execute("""INSERT INTO users (email, password_hash, full_name, role, is_active)
                       VALUES (%s,%s,%s,%s,TRUE) RETURNING id""",
                    (email, generate_password_hash(pw, method='pbkdf2:sha256:600000'),
                     f"E2E YF {role}", role))
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

    pid_u17    = mk_player(P_U17,    'U17',    f"YF17{PID%100000}")
    pid_u20    = mk_player(P_U20,    'U20',    f"YF20{PID%100000}")
    pid_u23    = mk_player(P_U23,    'U23',    f"YF23{PID%100000}")
    pid_senior = mk_player(P_SENIOR, 'senior', f"YFSR{PID%100000}")
    INSERTED_PLAYER_IDS += [pid_u17, pid_u20, pid_u23, pid_senior]

    cur.execute("""INSERT INTO matches (match_date, home_team, away_team, source, created_by)
                   VALUES (%s,%s,%s,'manual',%s) RETURNING id""",
                (date.today().isoformat(), "E2E Home", "E2E Away", admin_id))
    match_id = cur.fetchone()['id']
    INSERTED_MATCH_IDS.append(match_id)
    conn.commit()
print(f"  users={INSERTED_USER_IDS}, players={INSERTED_PLAYER_IDS}, match={match_id}")


try:
    admin_op = login(os.environ["INITIAL_ADMIN_EMAIL"], os.environ["INITIAL_ADMIN_PASSWORD"])
    td_op    = login(*USERS['td'][:2])
    scout_op = login(*USERS['scout'][:2])
    nt_op    = login(*USERS['nt'][:2])
    view_op  = login(*USERS['viewer'][:2])
    youth_op = login(*USERS['youth'][:2])

    # ── Case 1: constraint enforced ───────────────────────────────
    print("\n=== Case 1: column + constraint ===")
    ok_reject = False
    try:
        with db() as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO players (full_name, national_id, age_group, is_active, created_by)
                           VALUES (%s,%s,%s,TRUE,%s)""",
                        (f"E2EYF-{PID}-BAD", f"YFBAD{PID%100000}", 'U99', admin_id))
            conn.commit()
    except psycopg2.errors.CheckViolation:
        ok_reject = True
    except Exception as exc:
        ok_reject = 'check' in str(exc).lower()
    chk("1 age_group CHECK rejects out-of-domain value", ok_reject)

    # ── Case 2: youth player in its sub-view ──────────────────────
    print("\n=== Case 2: youth sub-view membership ===")
    _, u17_html, _ = http(admin_op, "GET", "/youth/u17")
    chk("2a U17 player on /youth/u17", P_U17 in u17_html)
    chk("2b U20 player NOT on /youth/u17", P_U20 not in u17_html)
    chk("2c senior player NOT on /youth/u17", P_SENIOR not in u17_html)
    _, u20_html, _ = http(admin_op, "GET", "/youth/u20")
    chk("2d U20 player on /youth/u20", P_U20 in u20_html)

    # ── Case 3: youth excluded from general list ──────────────────
    print("\n=== Case 3: general list excludes youth ===")
    _, players_html, _ = http(admin_op, "GET", "/players/")
    chk("3a U17 NOT on /players", P_U17 not in players_html)
    chk("3b U20 NOT on /players", P_U20 not in players_html)
    chk("3c U23 NOT on /players", P_U23 not in players_html)
    chk("3d senior IS on /players", P_SENIOR in players_html)

    # ── Case 4: youth section access matrix ───────────────────────
    print("\n=== Case 4: youth section access ===")
    for name, op in [('admin', admin_op), ('td', td_op), ('scout', scout_op),
                     ('nt_staff', nt_op), ('youth_nt', youth_op)]:
        s, _, _ = http(op, "GET", "/youth/")
        chk(f"4 {name} GET /youth → 200", s == 200, f"got {s}")
    s, _, _ = http(view_op, "GET", "/youth/")
    chk("4 viewer GET /youth → 403", s == 403, f"got {s}")

    # ── Case 5: age_group management (promotion) ──────────────────
    print("\n=== Case 5: nt_staff promotion + scout cannot ===")
    # nt_staff promotes the U23 player to senior via the edit form.
    tok = get_csrf(nt_op, f"/players/{pid_u23}/edit")
    s, _, _ = http(nt_op, "POST", f"/players/{pid_u23}/edit",
                   data={"csrf_token": tok, "full_name": P_U23,
                         "national_id": f"YF23{PID%100000}",
                         "age_group": "senior"})
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT age_group FROM players WHERE id=%s", (pid_u23,))
        ag_after = cur.fetchone()['age_group']
    chk("5a nt_staff promoted U23 → senior (DB)", ag_after == 'senior', f"ag={ag_after}")
    _, u23_html, _ = http(admin_op, "GET", "/youth/u23")
    chk("5b promoted player left /youth/u23", P_U23 not in u23_html)
    _, players_html2, _ = http(admin_op, "GET", "/players/")
    chk("5c promoted player now on /players", P_U23 in players_html2)

    # scout attempts to change age_group on the senior player → ignored.
    tok = get_csrf(scout_op, f"/players/{pid_senior}/edit")
    http(scout_op, "POST", f"/players/{pid_senior}/edit",
         data={"csrf_token": tok, "full_name": P_SENIOR,
               "national_id": f"YFSR{PID%100000}", "age_group": "U17"})
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT age_group FROM players WHERE id=%s", (pid_senior,))
        ag_scout = cur.fetchone()['age_group']
    chk("5d scout CANNOT change age_group (stays senior)", ag_scout == 'senior', f"ag={ag_scout}")

    # ── Case 6: youth_nt CRUD + evaluate ──────────────────────────
    print("\n=== Case 6: youth_nt CRUD + evaluate ===")
    # CREATE
    tok = get_csrf(youth_op, "/youth/u17/new")
    s, _, _ = http(youth_op, "POST", "/youth/u17/new",
                   data={"csrf_token": tok, "full_name": P_NEW,
                         "national_id": f"YFNEW{PID%100000}",
                         "primary_position_id": "1"})
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, age_group FROM players WHERE national_id=%s",
                    (f"YFNEW{PID%100000}",))
        row = cur.fetchone()
    new_pid = row['id'] if row else None
    if new_pid:
        INSERTED_PLAYER_IDS.append(new_pid)
    chk("6a youth_nt created a player", new_pid is not None)
    chk("6b created player is age_group U17", row and row['age_group'] == 'U17',
        f"ag={row['age_group'] if row else None}")
    # READ
    _, u17_html2, _ = http(youth_op, "GET", "/youth/u17")
    chk("6c new player visible on /youth/u17 to youth_nt", P_NEW in u17_html2)
    s, _, _ = http(youth_op, "GET", f"/players/{new_pid}")
    chk("6d youth_nt GET youth player profile → 200", s == 200, f"got {s}")
    # UPDATE (name change; age_group must stay U17 — youth_nt can't promote)
    tok = get_csrf(youth_op, f"/players/{new_pid}/edit")
    http(youth_op, "POST", f"/players/{new_pid}/edit",
         data={"csrf_token": tok, "full_name": P_NEW + "-EDITED",
               "national_id": f"YFNEW{PID%100000}",
               "primary_position_id": "1", "age_group": "senior"})
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT full_name, age_group FROM players WHERE id=%s", (new_pid,))
        r2 = cur.fetchone()
    chk("6e youth_nt edited the player name", r2 and r2['full_name'] == P_NEW + "-EDITED")
    chk("6f youth_nt could NOT promote (age_group stays U17)", r2 and r2['age_group'] == 'U17',
        f"ag={r2['age_group'] if r2 else None}")
    # EVALUATE
    s, _, _ = http(youth_op, "GET", f"/players/{new_pid}/evaluate")
    chk("6g youth_nt GET evaluate form → 200", s == 200, f"got {s}")
    tok = get_csrf(youth_op, f"/players/{new_pid}/evaluate")
    s, _, final = http(youth_op, "POST", f"/players/{new_pid}/evaluate",
                       data={"csrf_token": tok, "match_id": str(match_id),
                             "position_played_id": "1",  # now required (defaults to primary)
                             "action": "save_draft"})
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM evaluations WHERE player_id=%s AND deleted_at IS NULL",
                    (new_pid,))
        n_eval = cur.fetchone()['n']
    chk("6h youth_nt saved an evaluation draft", n_eval >= 1, f"evals={n_eval}, status={s}")
    # DELETE (deactivate)
    tok = get_csrf(youth_op, f"/players/{new_pid}")
    if tok is None:
        tok = get_csrf(youth_op, f"/players/{new_pid}/edit")
    http(youth_op, "POST", f"/players/{new_pid}/deactivate",
         data={"csrf_token": tok})
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT is_active FROM players WHERE id=%s", (new_pid,))
        act = cur.fetchone()['is_active']
    chk("6i youth_nt deactivated the player", act is False, f"is_active={act}")

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
        # the rejected U99 row never committed; clean any stray bad-natid row anyway
        cur.execute("DELETE FROM players WHERE national_id = %s", (f"YFBAD{PID%100000}",))
        if INSERTED_USER_IDS:
            cur.execute("DELETE FROM users WHERE id = ANY(%s)", (INSERTED_USER_IDS,))
        conn.commit()
    print(f"  cleaned {len(INSERTED_PLAYER_IDS)} players + {len(INSERTED_USER_IDS)} users")


print("\n" + "=" * 60)
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"Suite A summary: {n_pass} pass / {n_fail} fail (of {len(results)})")
sys.exit(0 if n_fail == 0 else 2)
