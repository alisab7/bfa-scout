"""
E2E — Eligibility badge label mapping.

Real Flask + real HTTP (NOT flask.test_client). Asserts on the RENDERED
profile card + list-grid badge, not just the helper return. Server on
127.0.0.1:5057.

The fix: a born citizen (bahraini) / ancestry-eligible player must read
"Citizen" — NOT "Eligible now". "Eligible now" is reserved for
foreign_residency players whose eligible date is in the past.

Cases:
  1  bahraini            → profile shows "Citizen", NOT "Eligible now"
  2  foreign_ancestry    → "Citizen"
  3  foreign_residency, eligible_from_date in PAST   → "Eligible now"
  4  foreign_residency, eligible_from_date in FUTURE → "Eligible in" (not now)
  5  foreign_residency, no date / no residency start → "residency start not set"
  6  not_eligible        → "Not eligible"
  7  NULL/unknown        → "Status unknown"
  8  list grid badge emits data-status="citizen" for the citizen
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
        return r.status, r.read().decode("utf-8", "replace"), r.url
    except HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), None


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


PID = os.getpid()
PREFIX = "E2E-ELIG"
today = date.today()
PAST = (today - timedelta(days=30)).isoformat()
FUTURE = (today + timedelta(days=800)).isoformat()

# name, nationality_status, eligible_from_date, residency_start
PLAYERS = [
    ('Citizen',   'bahraini',          None,   None),
    ('Ancestry',  'foreign_ancestry',  None,   None),
    ('ResNow',    'foreign_residency', PAST,   None),
    ('ResFuture', 'foreign_residency', FUTURE, None),
    ('ResNoDate', 'foreign_residency', None,   None),
    ('NotElig',   'not_eligible',      None,   None),
    ('Unknown',   None,                None,   None),
]
ids = {}


def cleanup():
    with db() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM players WHERE full_name LIKE %s", (f'{PREFIX}-%',))
        conn.commit()


print("=== Setup ===")
cleanup()
with db() as conn, conn.cursor() as cur:
    cur.execute("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1")
    admin_id = cur.fetchone()['id']
    for i, (name, status, elig, resid) in enumerate(PLAYERS):
        cur.execute(
            """INSERT INTO players
                 (full_name, national_id, age_group, nationality_status,
                  eligible_from_date, bahrain_residency_start_date,
                  nationality_code, is_active, created_by)
               VALUES (%s,%s,'senior',%s,%s,%s,'BHR',TRUE,%s) RETURNING id""",
            (f'{PREFIX}-{name}', f'ELIG{PID%10000}{i}', status, elig, resid, admin_id))
        ids[name] = cur.fetchone()['id']
    conn.commit()
print(f"  players={ids}")


try:
    admin = login(os.environ["INITIAL_ADMIN_EMAIL"], os.environ["INITIAL_ADMIN_PASSWORD"])

    def profile(name):
        _, html, _ = http(admin, "GET", f"/players/{ids[name]}")
        return html

    print("\n=== Badge labels (profile card) ===")
    h = profile('Citizen')
    chk("1a bahraini profile shows 'Citizen'", "Citizen" in h)
    chk("1b bahraini profile does NOT show 'Eligible now'", "Eligible now" not in h)

    h = profile('Ancestry')
    chk("2a foreign_ancestry shows 'Citizen'", "Citizen" in h)
    chk("2b foreign_ancestry does NOT show 'Eligible now'", "Eligible now" not in h)

    h = profile('ResNow')
    chk("3 foreign_residency past-date shows 'Eligible now'", "Eligible now" in h)

    h = profile('ResFuture')
    chk("4a foreign_residency future shows 'Eligible in' (still counting)", "Eligible in" in h)
    chk("4b foreign_residency future does NOT show 'Eligible now'", "Eligible now" not in h)

    h = profile('ResNoDate')
    chk("5 foreign_residency no-date shows 'residency start not set'",
        "residency start not set" in h)

    h = profile('NotElig')
    chk("6a not_eligible shows 'Not eligible'", "Not eligible" in h)
    chk("6b not_eligible does NOT show 'Eligible now'", "Eligible now" not in h)

    h = profile('Unknown')
    chk("7 NULL status shows 'Status unknown'", "Status unknown" in h)

    print("\n=== Badge macro (list grid data-status) ===")
    _, list_html, _ = http(admin, "GET", "/players/")
    chk("8a list grid emits data-status=\"citizen\" (new status for citizens)",
        'data-status="citizen"' in list_html)
    chk("8b 'eligible_now' status still emitted (reserved for residency past-date)",
        'data-status="eligible_now"' in list_html)

finally:
    print("\n(cleanup)")
    cleanup()
    print("  done")


print("\n" + "=" * 60)
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"Eligibility-badge E2E summary: {n_pass} pass / {n_fail} fail (of {len(results)})")
sys.exit(0 if n_fail == 0 else 2)
