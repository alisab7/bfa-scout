"""
E2E — /nt senior-only filter + live name-search markup.

Real Flask + real HTTP (NOT flask.test_client). Server on 127.0.0.1:5057.

  1  senior eligible player        → appears on /nt
  2  youth (U20) eligible player   → NOT on /nt, but IS on /youth/u20
  3  senior NULL-age_group player  → still on /nt (NULL-safe: no 1st-teamer hidden)
  4  /nt/residents unaffected      → foreign_residency player still listed
  5  nt_staff still accesses /youth (200) and /nt (200, sees senior)
  6  search box present in /nt HTML (type=search, x-model, placeholder EN+AR)
  7  each /nt row carries data-name with lowercased English + Arabic

Live keystroke filtering is client-side Alpine — Ali verifies in-browser.
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
PREFIX = "E2E-NTS"


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
    http(op, "POST", "/auth/login", data={"email": email, "password": pw, "csrf_token": m.group(1)})
    return op


def db():
    return psycopg2.connect(os.environ["DATABASE_URL"], cursor_factory=psycopg2.extras.RealDictCursor)


results = []
def chk(label, ok, ev=""):
    results.append((label, ok, ev))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}  {ev}")


PID = os.getpid()
NT = (f"e2e-nts-nt-{PID}@bfa.bh", f"pw-{PID}", 'nt_staff')
INSERTED_USER_IDS = []

SENIOR    = f"{PREFIX}-SeniorCitizen"
SENIOR_AR = "لاعب أول"
YOUTH     = f"{PREFIX}-YouthCitizen"
NULLAGE   = f"{PREFIX}-NullAgeSenior"
RESIDENT  = f"{PREFIX}-Resident"


def cleanup():
    with db() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM players WHERE full_name LIKE %s", (f'{PREFIX}-%',))
        if INSERTED_USER_IDS:
            cur.execute("DELETE FROM users WHERE id = ANY(%s)", (INSERTED_USER_IDS,))
        conn.commit()


print("=== Setup ===")
cleanup()
with db() as conn, conn.cursor() as cur:
    cur.execute("""INSERT INTO users (email,password_hash,full_name,role,is_active)
                   VALUES (%s,%s,%s,%s,TRUE) RETURNING id""",
                (NT[0], generate_password_hash(NT[1], method='pbkdf2:sha256:600000'),
                 'E2E NTS nt_staff', NT[2]))
    INSERTED_USER_IDS.append(cur.fetchone()['id'])
    cur.execute("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1")
    admin_id = cur.fetchone()['id']

    def mk(name, age_group, status, natid, name_ar=None, resid_start=None):
        cur.execute(
            """INSERT INTO players
                 (full_name, full_name_ar, national_id, age_group,
                  nationality_status, bahrain_residency_start_date,
                  nationality_code, is_active, created_by)
               VALUES (%s,%s,%s,%s,%s,%s,'BHR',TRUE,%s) RETURNING id""",
            (name, name_ar, natid, age_group, status, resid_start, admin_id))
        return cur.fetchone()['id']

    mk(SENIOR,   'senior', 'bahraini',          f'NTS{PID%10000}1', SENIOR_AR)
    mk(YOUTH,    'U20',    'bahraini',           f'NTS{PID%10000}2')
    mk(NULLAGE,  None,     'bahraini',           f'NTS{PID%10000}3')
    mk(RESIDENT, 'senior', 'foreign_residency',  f'NTS{PID%10000}4')
    conn.commit()
print("  fixtures created")


try:
    admin = login(os.environ["INITIAL_ADMIN_EMAIL"], os.environ["INITIAL_ADMIN_PASSWORD"])
    nt = login(NT[0], NT[1])

    print("\n=== /nt senior filter ===")
    _, nt_html, _ = http(admin, "GET", "/nt")
    chk("1 senior eligible player appears on /nt", SENIOR in nt_html)
    chk("2a youth (U20) eligible player NOT on /nt", YOUTH not in nt_html)
    chk("3 senior NULL-age_group player still on /nt (NULL-safe)", NULLAGE in nt_html)

    _, youth_html, _ = http(admin, "GET", "/youth/u20")
    chk("2b youth player IS on /youth/u20", YOUTH in youth_html)

    print("\n=== independence ===")
    _, res_html, _ = http(admin, "GET", "/nt/residents")
    chk("4 /nt/residents still lists the foreign_residency player", RESIDENT in res_html)

    s, _, _ = http(nt, "GET", "/youth")
    chk("5a nt_staff still accesses /youth (200)", s == 200, f"got {s}")
    s, nt_html2, _ = http(nt, "GET", "/nt")
    chk("5b nt_staff accesses /nt (200) and sees senior", s == 200 and SENIOR in nt_html2, f"got {s}")

    print("\n=== search markup ===")
    chk("6a /nt has a search input (type=search)", 'type="search"' in nt_html)
    chk("6b search input is Alpine-bound (x-model=\"q\")", 'x-model="q"' in nt_html)
    chk("6c search placeholder has EN + AR", "Search by name" in nt_html and "بحث بالاسم" in nt_html)
    expected_dataname = f'data-name="{SENIOR.lower()} {SENIOR_AR}"'
    chk("7 senior row carries data-name with lowercased EN + AR",
        expected_dataname in nt_html, f"looking for {expected_dataname!r}")

finally:
    print("\n(cleanup)")
    cleanup()
    print("  done")

print("\n" + "=" * 60)
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"/nt senior+search E2E summary: {n_pass} pass / {n_fail} fail (of {len(results)})")
sys.exit(0 if n_fail == 0 else 2)
