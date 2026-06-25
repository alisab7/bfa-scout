"""
E2E — Bulk club-assignment admin screen (/admin/assign-clubs).

Real Flask + real HTTP (NOT flask.test_client). Server on 127.0.0.1:5057.

  C1  GET lists active club-less players (club_id IS NULL); a player WITH a
      club is NOT listed.
  C2  POST assigns 2 selected players to club A → DB shows club_id + current_club
      = A's name (round-trip); page reload drops them from the list.
  C3  Assigning to a DIFFERENT club B also works (not just one example).
  C4  Stale-form guard: a player who already has a club isn't re-assigned.
  C5  Auth: a scout (non-admin/TD) is denied (redirect/403).
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
from dotenv import load_dotenv

sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent))
load_dotenv()
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = "http://127.0.0.1:5057"
PREFIX = "E2E-CLUB"


def http(op, method, path, *, data=None, allow_redirects=True):
    body = urlencode(data, doseq=True).encode() if data is not None else None
    req = Request(BASE + path, data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        r = op.open(req)
        return r.status, r.read().decode("utf-8", "replace"), r.url
    except HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), e.url


def csrf_of(html):
    m = re.search(r'name=["\']csrf_token["\']\s+value=["\']([^"\']+)["\']', html)
    return m.group(1) if m else None


def login(email, pw):
    op = build_opener(HTTPCookieProcessor(CookieJar()))
    _, html, _ = http(op, "GET", "/auth/login")
    http(op, "POST", "/auth/login",
         data={"email": email, "password": pw, "csrf_token": csrf_of(html)})
    return op


def db():
    return psycopg2.connect(os.environ["DATABASE_URL"],
                            cursor_factory=psycopg2.extras.RealDictCursor)


results = []
def chk(label, ok, ev=""):
    results.append((label, ok, ev))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}  {ev}")


ids = {}
clubA = clubB = None
SCOUT_EMAIL = f"e2e-club-scout@bfa.test"
SCOUT_PW = "ScoutClubPass!234"


def cleanup():
    with db() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM players WHERE full_name LIKE %s", (f'{PREFIX}-%',))
        cur.execute("DELETE FROM users WHERE email = %s", (SCOUT_EMAIL,))
        conn.commit()


print("=== Setup ===")
cleanup()
with db() as conn, conn.cursor() as cur:
    cur.execute("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1")
    admin_id = cur.fetchone()['id']
    # two real clubs to assign to
    cur.execute("SELECT id, name FROM clubs WHERE is_active ORDER BY id LIMIT 2")
    rows = cur.fetchall()
    clubA, clubB = rows[0], rows[1]

    def mk(name, club_id=None):
        cur.execute("""INSERT INTO players (full_name, national_id, age_group,
                           nationality_status, club_id, is_active, created_by)
                       VALUES (%s,%s,'senior','bahraini',%s,TRUE,%s) RETURNING id""",
                    (name, 'CLB' + name[-4:], club_id, admin_id))
        return cur.fetchone()['id']

    ids['a'] = mk(f"{PREFIX}-Needs-0001")          # club-less
    ids['b'] = mk(f"{PREFIX}-Needs-0002")          # club-less
    ids['c'] = mk(f"{PREFIX}-Needs-0003")          # club-less (for club B)
    ids['has'] = mk(f"{PREFIX}-Hasclub-09", clubA['id'])  # already has a club

    # a scout user for the auth check (password hashed via the app's hasher)
    sys.path  # ensure app importable
    from werkzeug.security import generate_password_hash
    cur.execute("""INSERT INTO users (email, password_hash, full_name, role, is_active)
                   VALUES (%s,%s,'E2E Club Scout','scout',TRUE)""",
                (SCOUT_EMAIL, generate_password_hash(SCOUT_PW)))
    conn.commit()
print(f"  clubA={clubA['name']} clubB={clubB['name']}  players={ids}")


try:
    admin = login(os.environ["INITIAL_ADMIN_EMAIL"], os.environ["INITIAL_ADMIN_PASSWORD"])

    print("\n=== C1: GET lists club-less players ===")
    status, html, _ = http(admin, "GET", "/admin/assign-clubs")
    chk("C1a page loads (200)", status == 200, f"status={status}")
    chk("C1b club-less player #1 listed", f"{PREFIX}-Needs-0001" in html)
    chk("C1c club-less player #2 listed", f"{PREFIX}-Needs-0002" in html)
    chk("C1d player WITH a club NOT listed", f"{PREFIX}-Hasclub-09" not in html)
    chk("C1e club dropdown present (clubA name)", clubA['name'] in html)

    print("\n=== C2: assign 2 players to club A (round-trip) ===")
    tok = csrf_of(http(admin, "GET", "/admin/assign-clubs")[1])
    http(admin, "POST", "/admin/assign-clubs",
         data={"csrf_token": tok, "club_id": clubA['id'],
               "player_ids": [ids['a'], ids['b']]})
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, club_id, current_club FROM players WHERE id = ANY(%s) ORDER BY id",
                    ([ids['a'], ids['b']],))
        r = {row['id']: row for row in cur.fetchall()}
    chk("C2a player A: club_id set to A", r[ids['a']]['club_id'] == clubA['id'])
    chk("C2b player A: current_club = A's name", r[ids['a']]['current_club'] == clubA['name'],
        f"got {r[ids['a']]['current_club']!r}")
    chk("C2c player B: club_id set to A", r[ids['b']]['club_id'] == clubA['id'])
    chk("C2d player B: current_club = A's name", r[ids['b']]['current_club'] == clubA['name'])
    # reload → they drop off the needs-club list
    _, html2, _ = http(admin, "GET", "/admin/assign-clubs")
    chk("C2e assigned players removed from list on reload",
        f"{PREFIX}-Needs-0001" not in html2 and f"{PREFIX}-Needs-0002" not in html2)
    chk("C2f still-club-less player #3 remains", f"{PREFIX}-Needs-0003" in html2)

    print("\n=== C3: assign player #3 to a DIFFERENT club B ===")
    tok = csrf_of(http(admin, "GET", "/admin/assign-clubs")[1])
    http(admin, "POST", "/admin/assign-clubs",
         data={"csrf_token": tok, "club_id": clubB['id'], "player_ids": [ids['c']]})
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT club_id, current_club FROM players WHERE id=%s", (ids['c'],))
        r3 = cur.fetchone()
    chk("C3a player #3: club_id = B", r3['club_id'] == clubB['id'])
    chk("C3b player #3: current_club = B's name", r3['current_club'] == clubB['name'],
        f"got {r3['current_club']!r}")

    print("\n=== C4: stale-form guard (already-clubbed player not re-assigned) ===")
    tok = csrf_of(http(admin, "GET", "/admin/assign-clubs")[1])
    http(admin, "POST", "/admin/assign-clubs",
         data={"csrf_token": tok, "club_id": clubB['id'], "player_ids": [ids['has']]})
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT club_id FROM players WHERE id=%s", (ids['has'],))
        chk("C4 already-clubbed player keeps its original club (A, not B)",
            cur.fetchone()['club_id'] == clubA['id'])

    print("\n=== C5: auth — scout is denied ===")
    scout = login(SCOUT_EMAIL, SCOUT_PW)
    s_status, _, s_url = http(scout, "GET", "/admin/assign-clubs", allow_redirects=True)
    chk("C5 scout denied (403 or redirected away from the screen)",
        s_status == 403 or (s_url is not None and "/admin/assign-clubs" not in s_url),
        f"status={s_status} url={s_url}")

finally:
    print("\n(cleanup)")
    cleanup()
    print("  done")

print("\n" + "=" * 60)
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"Assign-clubs E2E summary: {n_pass} pass / {n_fail} fail (of {len(results)})")
sys.exit(0 if n_fail == 0 else 2)
