"""
E2E for /nt/residents — the coaching-team naturalization-pathway view.

Real Flask + real HTTP (NOT flask.test_client). Snapshot+restore for
all test users and players.

Cases (spec table, with the /nt-unchanged correction noted inline):
   1  nt_staff GET /nt/residents          → 200
   2  admin    GET /nt/residents          → 200
   3  technical_director GET              → 200
   4  scout    GET                        → 403
   5  viewer   GET                        → 403
   6  anonymous GET                       → 302 to /auth/login
   7  foreign_residency, eligible date in past  → "Eligible Now"
   8  foreign_residency, eligible date in future → "Still Counting" + date
   9  foreign_residency, no date          → "Still Counting" + "date not set"
  10  bahraini player                     → NOT on /nt/residents
  11  /nt UNCHANGED — still 200, still shows the bahraini citizen AND
      still EXCLUDES non-eligible residents (proves the /nt filter was
      not modified). NOTE: the spec called /nt "citizen-only", but the
      real /nt shows eligible players of any route (incl. completed-
      residency residents); the hard rule forbids changing that filter,
      so this asserts "unchanged", not "bahraini-only".
  12  Nav: /nt/residents link present for nt_staff, absent for scout
"""
from __future__ import annotations

import os
import re
import sys
from datetime import date, timedelta
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


def section_of(html: str, needle: str) -> str | None:
    """Which section does `needle` fall in on the residents page?
    Returns 'eligible' | 'still' | None. The page renders 'Eligible Now'
    first, then 'Still Counting'."""
    if needle not in html:
        return None
    split = html.find("Still Counting")
    idx = html.find(needle)
    if split < 0:
        return 'eligible'           # only one section rendered
    return 'eligible' if idx < split else 'still'


# ───────── Fixtures ────────────────────────────────────────────────
PID = os.getpid()
USERS = {
    'nt':     (f"e2e-res-nt-{PID}@bfa.bh",     f"pw-nt-{PID}",     'nt_staff'),
    'td':     (f"e2e-res-td-{PID}@bfa.bh",     f"pw-td-{PID}",     'technical_director'),
    'scout':  (f"e2e-res-scout-{PID}@bfa.bh",  f"pw-scout-{PID}",  'scout'),
    'viewer': (f"e2e-res-viewer-{PID}@bfa.bh", f"pw-viewer-{PID}", 'viewer'),
}
INSERTED_USER_IDS: list[int] = []
INSERTED_PLAYER_IDS: list[int] = []

today = date.today()
PAST   = (today - timedelta(days=1)).isoformat()
FUTURE = (today + timedelta(days=400)).isoformat()

P_PAST    = f"E2ERES-{PID}-Past"
P_FUTURE  = f"E2ERES-{PID}-Future"
P_NODATE  = f"E2ERES-{PID}-NoDate"
P_CITIZEN = f"E2ERES-{PID}-Citizen"

print("=== Setup fixtures ===")
with db() as conn, conn.cursor() as cur:
    for key, (email, pw, role) in USERS.items():
        cur.execute("""INSERT INTO users (email, password_hash, full_name, role, is_active)
                       VALUES (%s,%s,%s,%s,TRUE) RETURNING id""",
                    (email, generate_password_hash(pw, method='pbkdf2:sha256:600000'),
                     f"E2E Res {role}", role))
        INSERTED_USER_IDS.append(cur.fetchone()['id'])
    cur.execute("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1")
    admin_id = cur.fetchone()['id']

    def mk_player(name, nat_status, elig_from, resid_start, natid):
        cur.execute("""
            INSERT INTO players (full_name, national_id, nationality_status,
                                 eligible_from_date, bahrain_residency_start_date,
                                 is_active, created_by)
            VALUES (%s,%s,%s,%s,%s,TRUE,%s) RETURNING id
        """, (name, natid, nat_status, elig_from, resid_start, admin_id))
        return cur.fetchone()['id']

    INSERTED_PLAYER_IDS += [
        mk_player(P_PAST,    'foreign_residency', PAST,   None, f"RESP{PID%100000}"),
        mk_player(P_FUTURE,  'foreign_residency', FUTURE, None, f"RESF{PID%100000}"),
        mk_player(P_NODATE,  'foreign_residency', None,   None, f"RESN{PID%100000}"),
        mk_player(P_CITIZEN, 'bahraini',          None,   None, f"RESC{PID%100000}"),
    ]
    conn.commit()
print(f"  users={INSERTED_USER_IDS}, players={INSERTED_PLAYER_IDS}")


try:
    admin_op = login(os.environ["INITIAL_ADMIN_EMAIL"], os.environ["INITIAL_ADMIN_PASSWORD"])
    nt_op    = login(*USERS['nt'][:2])
    td_op    = login(*USERS['td'][:2])
    scout_op = login(*USERS['scout'][:2])
    view_op  = login(*USERS['viewer'][:2])

    # ── Cases 1-5: permission matrix ──────────────────────────────
    print("\n=== Cases 1-5: permission matrix ===")
    s, _, _ = http(nt_op,    "GET", "/nt/residents"); chk("1 nt_staff → 200", s == 200, f"got {s}")
    s, _, _ = http(admin_op, "GET", "/nt/residents"); chk("2 admin → 200",    s == 200, f"got {s}")
    s, _, _ = http(td_op,    "GET", "/nt/residents"); chk("3 TD → 200",       s == 200, f"got {s}")
    # Scout (committee) was GRANTED residents access — they read eligibility
    # but still cannot reach the senior /nt squad page (asserted below).
    s, _, _ = http(scout_op, "GET", "/nt/residents"); chk("4 scout → 200 (committee access)", s == 200, f"got {s}")
    s, _, _ = http(view_op,  "GET", "/nt/residents"); chk("5 viewer → 403",   s == 403, f"got {s}")
    # Boundary: scout still cannot SEE the senior /nt squad — they're looped
    # to /players (friendly redirect from the 'Citizens' tab), not shown it.
    s, sc_nt_body, final = http(scout_op, "GET", "/nt")
    chk("4b scout senior /nt → redirected to /players (no squad shown)",
        final is not None and final.rstrip('/').endswith('/players')
        and "National Team Workspace" not in sc_nt_body,
        f"final={final}")

    # ── Case 6: anonymous → login ─────────────────────────────────
    print("\n=== Case 6: anonymous ===")
    anon = build_opener(HTTPCookieProcessor(CookieJar()))
    s, _, final = http(anon, "GET", "/nt/residents")
    chk("6 anonymous bounces to /auth/login", "/auth/login" in (final or ""),
        f"final={final}")

    # ── Cases 7-10: section membership ────────────────────────────
    print("\n=== Cases 7-10: section split ===")
    _, html, _ = http(admin_op, "GET", "/nt/residents")
    chk(f"7 past-date resident in 'Eligible Now'",
        section_of(html, P_PAST) == 'eligible',
        f"section={section_of(html, P_PAST)}")
    chk(f"8 future-date resident in 'Still Counting' (with date {FUTURE})",
        section_of(html, P_FUTURE) == 'still' and FUTURE in html,
        f"section={section_of(html, P_FUTURE)}, date_present={FUTURE in html}")
    # NoDate must be in Still Counting AND show 'date not set'
    nodate_sec = section_of(html, P_NODATE)
    chk("9 no-date resident in 'Still Counting' with 'date not set'",
        nodate_sec == 'still' and 'date not set' in html,
        f"section={nodate_sec}, marker={'date not set' in html}")
    chk("10 bahraini player NOT on /nt/residents",
        P_CITIZEN not in html)

    # ── Case 11: /nt unchanged ────────────────────────────────────
    print("\n=== Case 11: /nt unchanged (additive feature) ===")
    s, nt_html, _ = http(admin_op, "GET", "/nt")
    chk("11a /nt still returns 200", s == 200, f"got {s}")
    chk("11b /nt shows the bahraini citizen (eligible squad)",
        P_CITIZEN in nt_html)
    chk("11c /nt still EXCLUDES non-eligible residents "
        "(filter unchanged — Future/NoDate not present)",
        P_FUTURE not in nt_html and P_NODATE not in nt_html,
        f"future_in={P_FUTURE in nt_html}, nodate_in={P_NODATE in nt_html}")

    # ── Case 12: nav link gating ──────────────────────────────────
    print("\n=== Case 12: nav link gating ===")
    _, nt_home, _ = http(nt_op, "GET", "/")
    chk("12a nt_staff sees /nt/residents nav link",
        "/nt/residents" in nt_home)
    _, scout_home, _ = http(scout_op, "GET", "/")
    chk("12b scout NOW sees /nt/residents nav link (committee access)",
        "/nt/residents" in scout_home)
    chk("12c scout does NOT see the senior National Team nav link",
        ">National Team<" not in scout_home)

finally:
    print("\n(cleanup)")
    with db() as conn, conn.cursor() as cur:
        if INSERTED_PLAYER_IDS:
            cur.execute("DELETE FROM players WHERE id = ANY(%s)", (INSERTED_PLAYER_IDS,))
        if INSERTED_USER_IDS:
            cur.execute("DELETE FROM users WHERE id = ANY(%s)", (INSERTED_USER_IDS,))
        conn.commit()
    print(f"  deleted {len(INSERTED_PLAYER_IDS)} players + {len(INSERTED_USER_IDS)} users")


print("\n" + "=" * 60)
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"E2E summary: {n_pass} pass / {n_fail} fail (of {len(results)})")
sys.exit(0 if n_fail == 0 else 2)
