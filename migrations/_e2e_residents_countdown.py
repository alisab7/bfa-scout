"""
E2E — /nt/residents countdown ("Eligible in Xy Ym") on pending players.

Real Flask + real HTTP (NOT flask.test_client). Server on 127.0.0.1:5057.

  1  pending resident ~6 months out → "Eligible in 0y 6m" on residents table
  2  pending resident ~1y2m out     → "Eligible in 1y 2m"
  3  eligible-now resident          → NO countdown (unchanged)
  4  consistency: the residents countdown == the player profile's countdown
     for the SAME player
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
PREFIX = "E2E-RCD"


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


def row_block(html, name):
    """Return the <tr>…</tr> chunk containing `name` (so we test the right row)."""
    i = html.find(name)
    if i < 0:
        return ""
    start = html.rfind("<tr", 0, i)
    end = html.find("</tr>", i)
    return html[start:end] if start >= 0 and end >= 0 else ""


PID = os.getpid()
today = date.today()
D_6M = (today + timedelta(days=185)).isoformat()   # → 0y 6m
D_14M = (today + timedelta(days=425)).isoformat()  # → 1y 2m
D_PAST = (today - timedelta(days=30)).isoformat()  # eligible now

SIXM   = f"{PREFIX}-SixMonths"
FOURTM = f"{PREFIX}-FourteenMonths"
NOWP   = f"{PREFIX}-EligibleNow"
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

    def mk(name, elig_date):
        cur.execute("""INSERT INTO players
                         (full_name, national_id, age_group, nationality_status,
                          eligible_from_date, is_active, created_by)
                       VALUES (%s,%s,'senior','foreign_residency',%s,TRUE,%s) RETURNING id""",
                    (name, f'RCD{abs(hash(name))%1000000}', elig_date, admin_id))
        return cur.fetchone()['id']

    ids['six'] = mk(SIXM, D_6M)
    ids['fourteen'] = mk(FOURTM, D_14M)
    ids['now'] = mk(NOWP, D_PAST)
    conn.commit()
print(f"  players={ids}")


try:
    admin = login(os.environ["INITIAL_ADMIN_EMAIL"], os.environ["INITIAL_ADMIN_PASSWORD"])

    _, res_html, _ = http(admin, "GET", "/nt/residents")
    six_row = row_block(res_html, SIXM)
    fourteen_row = row_block(res_html, FOURTM)
    now_row = row_block(res_html, NOWP)

    print("\n=== countdown on pending rows ===")
    chk("1 ~6mo pending resident shows 'Eligible in 0y 6m'",
        "Eligible in 0y 6m" in six_row, f"row snippet has countdown={'Eligible in' in six_row}")
    chk("2 ~14mo pending resident shows 'Eligible in 1y 2m'",
        "Eligible in 1y 2m" in fourteen_row)
    chk("3 eligible-now resident shows NO countdown",
        NOWP in res_html and "Eligible in" not in now_row, f"now_row has 'Eligible in'={'Eligible in' in now_row}")

    print("\n=== consistency vs player profile ===")
    _, prof_six, _ = http(admin, "GET", f"/players/{ids['six']}")
    m = re.search(r"Eligible in \dy \d{1,2}m", prof_six)
    profile_countdown = m.group(0) if m else None
    chk("4 profile shows a countdown for the 6mo player", profile_countdown is not None,
        f"profile_countdown={profile_countdown}")
    chk("4b residents countdown == profile countdown (same player)",
        profile_countdown == "Eligible in 0y 6m" and "Eligible in 0y 6m" in six_row,
        f"profile={profile_countdown}")

finally:
    print("\n(cleanup)")
    cleanup()
    print("  done")

print("\n" + "=" * 60)
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"Residents-countdown E2E summary: {n_pass} pass / {n_fail} fail (of {len(results)})")
sys.exit(0 if n_fail == 0 else 2)
