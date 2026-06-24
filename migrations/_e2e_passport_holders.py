"""
E2E — Passport holders (naturalized Bahraini + origin country).

Real Flask + real HTTP (NOT flask.test_client). Server on 127.0.0.1:5057.

A passport holder = nationality_status='bahraini' AND origin_country set.
They run the SAME 5-year residency countdown as residents; only the label
changes (Bahraini + origin + "Passport holder").

  P1  passport holder, residency ~6mo from 5y → profile: Bahraini, Origin,
      "Passport holder", countdown "Eligible in 0y 6m"
  P2  passport holder, residency >5y ago → "Eligible now" (no countdown)
  P3  born citizen (bahraini, no origin) → "Citizen", no origin, no countdown
  P4  foreign_residency (no origin) → UNCHANGED: foreign nationality, countdown,
      NOT "passport holder", NOT relabeled Bahraini
  P5  origin on PROFILE but NOT on the players LIST
  P6  passport holder appears on /nt/residents with the passport-holder label
  P7  residents countdown == profile countdown (consistency)
  P8  filter: bahraini+origin returns exactly the passport holders (queryable)
  P9  edit form sets origin_country (persists, conn.commit)
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
PREFIX = "E2E-PPH"


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


def row_block(html, name):
    i = html.find(name)
    if i < 0:
        return ""
    start = html.rfind("<tr", 0, i); end = html.find("</tr>", i)
    return html[start:end] if start >= 0 and end >= 0 else ""


PID = os.getpid()
today = date.today()
R_6MO  = (today - timedelta(days=1640)).isoformat()   # +5y ≈ 6 months out
R_DONE = (today - timedelta(days=2190)).isoformat()   # +5y already passed

PH_PEND  = f"{PREFIX}-HolderPending"
PH_DONE  = f"{PREFIX}-HolderDone"
CITIZEN  = f"{PREFIX}-BornCitizen"
RESIDENT = f"{PREFIX}-ForeignResident"
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

    def mk(name, status, nat, nat_code, origin, origin_code, resi):
        cur.execute("""INSERT INTO players
                         (full_name, national_id, age_group, nationality_status,
                          nationality, nationality_code,
                          origin_country, origin_country_code,
                          bahrain_residency_start_date, is_active, created_by)
                       VALUES (%s,%s,'senior',%s,%s,%s,%s,%s,%s,TRUE,%s) RETURNING id""",
                    (name, f'PPH{abs(hash(name))%1000000}', status, nat, nat_code,
                     origin, origin_code, resi, admin_id))
        return cur.fetchone()['id']

    ids['ph_pend'] = mk(PH_PEND,  'bahraini', 'Bahrain', 'BHR', 'Brazil', 'BRA', R_6MO)
    ids['ph_done'] = mk(PH_DONE,  'bahraini', 'Bahrain', 'BHR', 'Brazil', 'BRA', R_DONE)
    ids['citizen'] = mk(CITIZEN,  'bahraini', 'Bahrain', 'BHR', None, None, None)
    ids['resident']= mk(RESIDENT, 'foreign_residency', 'Brazil', 'BRA', None, None, R_6MO)
    conn.commit()
print(f"  players={ids}")


try:
    admin = login(os.environ["INITIAL_ADMIN_EMAIL"], os.environ["INITIAL_ADMIN_PASSWORD"])

    def prof(pid):
        return http(admin, "GET", f"/players/{pid}")[1]

    print("\n=== P1: passport holder pending ===")
    p = prof(ids['ph_pend'])
    chk("P1a profile shows Origin", "Origin" in p and "Brazil" in p)
    chk("P1b profile shows 'Passport holder'", "Passport holder" in p)
    chk("P1c profile shows countdown 'Eligible in 0y 6m'", "Eligible in 0y 6m" in p, )
    chk("P1d nationality shown as Bahrain (not relabeled foreign)", "Bahrain" in p)

    print("\n=== P2: passport holder, 5y complete ===")
    p2 = prof(ids['ph_done'])
    chk("P2a eligible now (no countdown)", "Eligible now" in p2 and "Eligible in" not in p2)
    chk("P2b still flagged passport holder", "Passport holder" in p2)

    print("\n=== P3: born citizen unchanged ===")
    p3 = prof(ids['citizen'])
    chk("P3a shows 'Citizen'", "Citizen" in p3)
    chk("P3b no Origin / Passport holder", "Passport holder" not in p3 and ">Origin<" not in p3)
    chk("P3c no countdown", "Eligible in" not in p3)

    print("\n=== P4: foreign resident unchanged ===")
    p4 = prof(ids['resident'])
    chk("P4a NOT a passport holder", "Passport holder" not in p4)
    chk("P4b keeps foreign nationality (Brazil)", "Brazil" in p4)
    chk("P4c still has the residency countdown", "Eligible in 0y 6m" in p4)

    print("\n=== P5: origin on PROFILE only, NOT the list ===")
    _, lst, _ = http(admin, "GET", "/players/")
    chk("P5a passport holder appears on the list", PH_PEND in lst)
    chk("P5b list does NOT show 'Passport holder'", "Passport holder" not in lst)
    chk("P5c list does NOT show an Origin column", ">Origin<" not in lst and "Origin:" not in lst)

    print("\n=== P6/P7: residents view + consistency ===")
    _, res_html, _ = http(admin, "GET", "/nt/residents")
    ph_row = row_block(res_html, PH_PEND)
    chk("P6a passport holder appears on /nt/residents", PH_PEND in res_html)
    chk("P6b labelled 'Passport holder' on residents", "Passport holder" in ph_row)
    chk("P7 residents countdown matches profile (Eligible in 0y 6m)",
        "Eligible in 0y 6m" in ph_row)

    print("\n=== P8: filter / queryable ===")
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT full_name FROM players WHERE nationality_status='bahraini' "
                    "AND origin_country IS NOT NULL AND full_name LIKE %s ORDER BY full_name",
                    (f'{PREFIX}-%',))
        holders = [r['full_name'] for r in cur.fetchall()]
    chk("P8a filter returns exactly the 2 passport holders",
        holders == [PH_DONE, PH_PEND], f"got {holders}")
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM players WHERE origin_country='Brazil' "
                    "AND full_name LIKE %s", (f'{PREFIX}-%',))
        chk("P8b origin_country queryable ('Brazil' returns holders)", cur.fetchone()['n'] == 2)

    print("\n=== P9: edit form sets origin (persists) ===")
    # Make the born-citizen a passport holder via the edit form.
    tok = csrf_of(http(admin, "GET", f"/players/{ids['citizen']}/edit")[1])
    http(admin, "POST", f"/players/{ids['citizen']}/edit",
         data={"csrf_token": tok, "full_name": CITIZEN,
               "national_id": f"PPH{abs(hash(CITIZEN))%1000000}",
               "nationality_status": "bahraini",
               "origin_country_code": "BRA",
               "bahrain_residency_start_date": R_6MO})
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT origin_country, origin_country_code FROM players WHERE id=%s",
                    (ids['citizen'],))
        r = cur.fetchone()
    chk("P9a edit persisted origin_country_code=BRA", r['origin_country_code'] == 'BRA',
        f"got {r['origin_country_code']}")
    chk("P9b edit persisted origin_country name", bool(r['origin_country']),
        f"got {r['origin_country']!r}")
    # now the former citizen shows as passport holder
    p9 = prof(ids['citizen'])
    chk("P9c former citizen now shows 'Passport holder'", "Passport holder" in p9)

finally:
    print("\n(cleanup)")
    cleanup()
    print("  done")

print("\n" + "=" * 60)
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"Passport-holders E2E summary: {n_pass} pass / {n_fail} fail (of {len(results)})")
sys.exit(0 if n_fail == 0 else 2)
