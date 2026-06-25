"""
E2E — players-list card badge for passport holders (bahraini + origin).

Real Flask + real HTTP (NOT flask.test_client). Server on 127.0.0.1:5057.

The card badge (eligibility_badge macro → compute_eligibility_status) was
rendering "Citizen" for bahraini+origin players because the list query didn't
SELECT origin_country. Every category, asserted on the RENDERED list HTML:

  B1  bahraini + origin, under 5y  → card "Eligible in Xy Ym"  (NOT "Citizen")
  B2  bahraini + origin, past 5y   → card "Eligible now"
  B3  bahraini + NO origin (born)  → card "Citizen"            (unchanged)
  B4  foreign_residency, under 5y  → card "Eligible in Xy Ym"  (Elliot, unchanged)
  B5  consistency: card label == profile eligibility label
  B6  "Pending (future)" filter still contains the bahraini+origin under-5y player
  B7  comparison view (other starved query) also fixed: bahraini+origin → countdown
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
PREFIX = "E2E-LBADGE"


def http(op, method, path, *, data=None):
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


def card_of(html, name):
    """Return the single player-card <a>…</a> block containing `name`."""
    i = html.find(name)
    if i < 0:
        return ""
    start = html.rfind('<a ', 0, i)
    end = html.find('</a>', i)
    return html[start:end] if start >= 0 and end >= 0 else ""


results = []
def chk(label, ok, ev=""):
    results.append((label, ok, ev))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}  {ev}")


today = date.today()
R_6MO = (today - timedelta(days=1640)).isoformat()   # +5y ≈ 6 months out
R_DONE = (today - timedelta(days=2190)).isoformat()   # +5y already passed

PH_PEND = f"{PREFIX}-PHpending"
PH_DONE = f"{PREFIX}-PHdone"
CITIZEN = f"{PREFIX}-BornCitizen"
FR_PEND = f"{PREFIX}-ForeignResident"
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

    def mk(name, status, origin, resi):
        cur.execute("""INSERT INTO players
                         (full_name, national_id, age_group, nationality_status,
                          nationality_code, origin_country, origin_country_code,
                          bahrain_residency_start_date, is_active, created_by)
                       VALUES (%s,%s,'senior',%s,%s,%s,%s,%s,TRUE,%s) RETURNING id""",
                    (name, 'LB' + name[-7:], status, 'BHR' if status == 'bahraini' else 'BRA',
                     origin, ('BRA' if origin else None), resi, admin_id))
        return cur.fetchone()['id']

    ids['ph_pend'] = mk(PH_PEND, 'bahraini', 'Brazil', R_6MO)
    ids['ph_done'] = mk(PH_DONE, 'bahraini', 'Brazil', R_DONE)
    ids['citizen'] = mk(CITIZEN, 'bahraini', None, None)
    ids['fr_pend'] = mk(FR_PEND, 'foreign_residency', None, R_6MO)
    conn.commit()
print(f"  players={ids}")


try:
    admin = login(os.environ["INITIAL_ADMIN_EMAIL"], os.environ["INITIAL_ADMIN_PASSWORD"])
    _, lst, _ = http(admin, "GET", "/players/")

    print("\n=== B1: bahraini+origin, under 5y → countdown, NOT 'Citizen' ===")
    c = card_of(lst, PH_PEND)
    chk("B1a card shows 'Eligible in 0y 6m'", "Eligible in 0y 6m" in c, repr(c[-200:]) if "Eligible in 0y 6m" not in c else "")
    chk("B1b card does NOT show 'Citizen'", "Citizen" not in c)

    print("\n=== B2: bahraini+origin, past 5y → eligible now ===")
    c2 = card_of(lst, PH_DONE)
    chk("B2a card shows 'Eligible now'", "Eligible now" in c2)
    chk("B2b card not 'Citizen', not future countdown",
        "Citizen" not in c2 and "Eligible in" not in c2)

    print("\n=== B3: born citizen (bahraini, no origin) → 'Citizen' ===")
    c3 = card_of(lst, CITIZEN)
    chk("B3a card shows 'Citizen'", "Citizen" in c3)
    chk("B3b card has no countdown", "Eligible in" not in c3)

    print("\n=== B4: foreign resident, under 5y → countdown (Elliot, unchanged) ===")
    c4 = card_of(lst, FR_PEND)
    chk("B4a card shows 'Eligible in 0y 6m'", "Eligible in 0y 6m" in c4)
    chk("B4b card not 'Citizen'", "Citizen" not in c4)

    print("\n=== B5: consistency — card label == profile label ===")
    _, prof, _ = http(admin, "GET", f"/players/{ids['ph_pend']}")
    chk("B5 same countdown on card AND profile",
        ("Eligible in 0y 6m" in c) and ("Eligible in 0y 6m" in prof))

    print("\n=== B6: Pending filter still contains the bahraini+origin under-5y ===")
    _, pend, _ = http(admin, "GET", "/players/?elig=pending")
    chk("B6a pending filter includes the passport holder", PH_PEND in pend)
    chk("B6b pending filter includes the foreign resident", FR_PEND in pend)
    chk("B6c pending card also shows countdown (not Citizen)",
        "Eligible in 0y 6m" in card_of(pend, PH_PEND)
        and "Citizen" not in card_of(pend, PH_PEND))

    print("\n=== B7: comparison view (other starved query) also fixed ===")
    cmp_ids = f"{ids['ph_pend']},{ids['citizen']},{ids['ph_done']}"
    _, cmp, _ = http(admin, "GET", f"/players/compare/view?ids={cmp_ids}")
    chk("B7a compare: passport holder shows countdown",
        "Eligible in 0y 6m" in card_of(cmp, PH_PEND) or "Eligible in 0y 6m" in cmp)
    chk("B7b compare: born citizen still 'Citizen'",
        "Citizen" in cmp)

finally:
    print("\n(cleanup)")
    cleanup()
    print("  done")

print("\n" + "=" * 60)
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"List-badge passport E2E summary: {n_pass} pass / {n_fail} fail (of {len(results)})")
sys.exit(0 if n_fail == 0 else 2)
