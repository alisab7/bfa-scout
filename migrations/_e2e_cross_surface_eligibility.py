"""
E2E — cross-surface eligibility consistency guard (v1.8.2).

Takes ONE passport-holder (bahraini + origin, under 5y) and asserts the
IDENTICAL "Eligible in 0y 6m" label across every eligibility surface:

  S1a  players-list card badge
  S1b  player profile eligibility section
  S1c  passport PDF (pypdf text extraction — PDF wording is SAME label for
         bahraini+origin because _build_passport_eligibility delegates to
         compute_eligibility_status for that branch)
  S1d  comparison view badge (with the born citizen)
  S1e  /nt/residents still-counting — name + "(Eligible in 0y 6m)" present
  S1f  /players?elig=pending — card shows countdown, NOT "Citizen"
  S1g  NOT in /players?elig=eligible_now  (still counting)
  S1h  NOT in /nt squad  (WHERE clause excludes bahraini+origin with future clock)

Born citizen asserts "Citizen" on HTML surfaces, "Eligible now"/"Bahraini" on PDF,
appears in /nt squad with "Bahraini citizen", in eligible_now bucket.

Foreign resident (pending) asserts countdown on list + profile + /nt/residents.

Purpose: any future query that drops `origin_country` from its SELECT will
immediately fail S1a–S1d (passport holder rendered "Citizen" instead of countdown).
This is the permanent guard for the starved-query bug class.

Rules: real HTTP, NO flask.test_client. Server on 127.0.0.1:5057.
"""
from __future__ import annotations

import os
import re
import sys
from datetime import date, timedelta
from io import BytesIO
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
PREFIX = "E2E-XSURF"


def http(op, method, path, *, data=None, raw=False):
    body = urlencode(data, doseq=True).encode() if data is not None else None
    req = Request(BASE + path, data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        r = op.open(req)
        content = r.read()
        return r.status, (content if raw else content.decode("utf-8", "replace")), r.url
    except HTTPError as e:
        content = e.read()
        return e.code, (content if raw else content.decode("utf-8", "replace")), e.url


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


def pdf_text(op, path):
    """GET a passport PDF over real HTTP and extract its text layer."""
    from pypdf import PdfReader
    _, raw, _ = http(op, "GET", path, raw=True)
    return "\n".join((p.extract_text() or "") for p in PdfReader(BytesIO(raw)).pages)


def card_of(html, name):
    """Return the player-card <a>…</a> block containing `name`."""
    i = html.find(name)
    if i < 0:
        return ""
    start = html.rfind('<a ', 0, i)
    end = html.find('</a>', i)
    return html[start:end] if start >= 0 and end >= 0 else ""


def cmp_card_of(html, name):
    """Extract the compare-view player card div that contains `name`.

    The compare template wraps each player in:
      <div class="rounded-xl p-4 flex items-center gap-3" ...>
        ... <a ...>name</a> ... eligibility_badge ...
      </div>

    We find the *last* opening of that class before `name` and the *first*
    closing `</div>` after the badge div ("mt-2"), so we stay within that
    player's card even when two cards are adjacent.
    """
    i = html.find(name)
    if i < 0:
        return ""
    # Start: last card div opener before the name
    marker = 'rounded-xl p-4 flex items-center gap-3'
    start = html.rfind(marker, 0, i)
    if start < 0:
        return ""
    start = html.rfind('<div', 0, start)
    if start < 0:
        return ""
    # End: the "mt-2" eligibility badge wrapper closes shortly after the name;
    # we grab up to the closing of that div (badge div is the last nested div).
    badge_div = html.find('mt-2', i)
    if badge_div < 0:
        return html[start: i + 800]
    end = html.find('</div>', badge_div)
    return html[start: end] if end > 0 else html[start: i + 800]


def row_of(html, name):
    """Return the nearest <tr>…</tr> block containing `name`."""
    i = html.find(name)
    if i < 0:
        return ""
    start = html.rfind("<tr", 0, i)
    end = html.find("</tr>", i)
    return html[start:end] if start >= 0 and end >= 0 else ""


results = []


def chk(label, ok, ev=""):
    results.append((label, ok, ev))
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {label}  {ev if not ok else ''}")


# ── Dates ──────────────────────────────────────────────────────────────────────
today = date.today()
# residency start 4.5y ago → target (start + 5y) = today + ~185 days
# humanize_time_until(target): 185 // 365 = 0y, 185 // 30 = 6m → "Eligible in 0y 6m"
R_PEND = (today - timedelta(days=1640)).isoformat()

PH_PEND = f"{PREFIX}-PHpending"   # passport holder, still counting
CITIZEN = f"{PREFIX}-BornCitizen"  # bahraini born (no origin)
FR_PEND = f"{PREFIX}-ForeignRes"   # foreign_residency, still counting

ids: dict[str, int] = {}


def cleanup():
    with db() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM players WHERE full_name LIKE %s", (f"{PREFIX}-%",))
        conn.commit()


# ── Setup ───────────────────────────────────────────────────────────────────
print("=== Setup ===")
cleanup()

with db() as conn, conn.cursor() as cur:
    cur.execute("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1")
    admin_id = cur.fetchone()["id"]

    def mk(name, status, origin, resi):
        cur.execute(
            """INSERT INTO players
                 (full_name, national_id, age_group,
                  nationality_status, nationality_code,
                  origin_country, origin_country_code,
                  bahrain_residency_start_date, is_active, created_by)
               VALUES (%s,%s,'senior',%s,%s,%s,%s,%s,TRUE,%s) RETURNING id""",
            (name, "XS" + name[-6:], status,
             "BHR" if status in ("bahraini", "foreign_ancestry") else "BRA",
             origin, ("BRA" if origin else None), resi, admin_id),
        )
        return cur.fetchone()["id"]

    ids["ph_pend"]  = mk(PH_PEND, "bahraini",         "Brazil", R_PEND)
    ids["citizen"]  = mk(CITIZEN, "bahraini",          None,     None)
    ids["fr_pend"]  = mk(FR_PEND, "foreign_residency", None,     R_PEND)
    conn.commit()

print(f"  players={ids}")

try:
    admin = login(os.environ["INITIAL_ADMIN_EMAIL"], os.environ["INITIAL_ADMIN_PASSWORD"])

    # ── Fetch pages used in multiple sections ──────────────────────────────
    _, lst, _  = http(admin, "GET", "/players/")
    _, pend, _ = http(admin, "GET", "/players/?elig=pending")
    _, enow, _ = http(admin, "GET", "/players/?elig=eligible_now")
    cmp_ids    = f"{ids['ph_pend']},{ids['citizen']}"
    _, cmp, _  = http(admin, "GET", f"/players/compare/view?ids={cmp_ids}")
    _, nt, _   = http(admin, "GET", "/nt/")
    _, res, _  = http(admin, "GET", "/nt/residents")

    _, prof_ph, _  = http(admin, "GET", f"/players/{ids['ph_pend']}")
    _, prof_cit, _ = http(admin, "GET", f"/players/{ids['citizen']}")
    _, prof_fr, _  = http(admin, "GET", f"/players/{ids['fr_pend']}")

    try:
        pdf_ph  = pdf_text(admin, f"/players/{ids['ph_pend']}/passport.pdf")
        pdf_cit = pdf_text(admin, f"/players/{ids['citizen']}/passport.pdf")
        have_pypdf = True
    except ImportError:
        print("  [SKIP] pypdf not installed — PDF assertions skipped")
        pdf_ph = pdf_cit = ""
        have_pypdf = False

    # ──────────────────────────────────────────────────────────────────────
    # S1: Passport holder (bahraini + origin, still counting)
    # Expected label everywhere: "Eligible in 0y 6m"  (NOT "Citizen")
    # ──────────────────────────────────────────────────────────────────────
    print(f"\n=== S1: Passport holder ({PH_PEND}) — every surface ===")

    c_ph = card_of(lst, PH_PEND)
    chk("S1a-i  list card: shows 'Eligible in 0y 6m'",
        "Eligible in 0y 6m" in c_ph, repr(c_ph[-200:]) if "Eligible in 0y 6m" not in c_ph else "")
    chk("S1a-ii list card: NOT 'Citizen'",
        "Citizen" not in c_ph)

    chk("S1b    profile: shows 'Eligible in 0y 6m'",
        "Eligible in 0y 6m" in prof_ph)

    if have_pypdf:
        chk("S1c-i  PDF: shows 'Eligible in 0y 6m'",
            "Eligible in 0y 6m" in pdf_ph, repr(pdf_ph[:300]) if "Eligible in 0y 6m" not in pdf_ph else "")
        chk("S1c-ii PDF: NOT 'Citizen'",
            "Citizen" not in pdf_ph)
    else:
        print("  [SKIP] S1c PDF assertions (pypdf not installed)")

    # Compare: extract each player's card div (avoids spillover into adjacent card)
    cmp_ph  = cmp_card_of(cmp, PH_PEND)
    chk("S1d-i  compare: shows 'Eligible in 0y 6m'",
        "Eligible in 0y 6m" in cmp_ph,
        repr(cmp_ph[-400:]) if "Eligible in 0y 6m" not in cmp_ph else "")
    chk("S1d-ii compare: NOT 'Citizen' in PH card",
        "Citizen" not in cmp_ph)

    # /nt/residents: player should appear in still_counting (player name present)
    # and the countdown "(Eligible in 0y 6m)" should be on the page
    chk("S1e-i  /nt/residents: player name present",
        PH_PEND in res)
    chk("S1e-ii /nt/residents: countdown in parens",
        "(Eligible in 0y 6m)" in res)

    c_ph_pend = card_of(pend, PH_PEND)
    chk("S1f-i  pending filter: player appears",
        PH_PEND in pend)
    chk("S1f-ii pending filter: card shows countdown",
        "Eligible in 0y 6m" in c_ph_pend,
        repr(c_ph_pend[-200:]) if "Eligible in 0y 6m" not in c_ph_pend else "")
    chk("S1f-iii pending filter: NOT 'Citizen' on card",
        "Citizen" not in c_ph_pend)

    chk("S1g    NOT in eligible_now filter",
        PH_PEND not in enow)

    chk("S1h    NOT in /nt squad (still counting)",
        PH_PEND not in nt)

    # ──────────────────────────────────────────────────────────────────────
    # S2: Born citizen — "Citizen" on HTML surfaces, "Eligible now"/"Bahraini" on PDF
    # ──────────────────────────────────────────────────────────────────────
    print(f"\n=== S2: Born citizen ({CITIZEN}) — every surface ===")

    c_cit = card_of(lst, CITIZEN)
    chk("S2a    list card: shows 'Citizen'",
        "Citizen" in c_cit, repr(c_cit[-200:]) if "Citizen" not in c_cit else "")

    chk("S2b    profile: shows 'Citizen'",
        "Citizen" in prof_cit)

    # Compare: extract born-citizen's card specifically
    cmp_cit = cmp_card_of(cmp, CITIZEN)
    chk("S2c    compare: shows 'Citizen' in citizen card",
        "Citizen" in cmp_cit)

    if have_pypdf:
        # PDF for bahraini born citizen: _build_passport_eligibility returns
        # label "Eligible now" (not "Citizen") with note "Bahraini citizen"
        chk("S2d-i  PDF: not a raw countdown for citizen",
            "Eligible in" not in pdf_cit)
        chk("S2d-ii PDF: 'Eligible now' or 'Bahraini' present",
            "Eligible now" in pdf_cit or "Bahraini" in pdf_cit)
    else:
        print("  [SKIP] S2d PDF assertions (pypdf not installed)")

    chk("S2e    in eligible_now filter",
        CITIZEN in enow)

    r_cit = row_of(nt, CITIZEN)
    chk("S2f-i  /nt squad: citizen appears",
        CITIZEN in nt)
    chk("S2f-ii /nt squad: 'Bahraini citizen' in row",
        "Bahraini citizen" in r_cit,
        repr(r_cit[-300:]) if "Bahraini citizen" not in r_cit else "")

    # ──────────────────────────────────────────────────────────────────────
    # S3: Foreign resident (pending) — countdown on list + profile + residents
    # ──────────────────────────────────────────────────────────────────────
    print(f"\n=== S3: Foreign resident ({FR_PEND}) — key surfaces ===")

    c_fr = card_of(lst, FR_PEND)
    chk("S3a    list card: shows 'Eligible in 0y 6m'",
        "Eligible in 0y 6m" in c_fr)
    chk("S3b    list card: NOT 'Citizen'",
        "Citizen" not in c_fr)

    chk("S3c    profile: shows 'Eligible in 0y 6m'",
        "Eligible in 0y 6m" in prof_fr)

    chk("S3d    /nt/residents: player name present",
        FR_PEND in res)

    # ──────────────────────────────────────────────────────────────────────
    # S4: Cross-surface consistency — same status_code / label invariants
    # ──────────────────────────────────────────────────────────────────────
    print("\n=== S4: Cross-surface consistency (label agreement) ===")

    # PH_PEND: list card label == profile label (both from compute_eligibility_status)
    ph_list_ok  = "Eligible in 0y 6m" in c_ph
    ph_prof_ok  = "Eligible in 0y 6m" in prof_ph
    chk("S4a    PH: list label == profile label (both 'Eligible in 0y 6m')",
        ph_list_ok and ph_prof_ok)

    # PH_PEND: list + compare also agree
    ph_cmp_ok = "Eligible in 0y 6m" in cmp_ph
    chk("S4b    PH: compare label == list label",
        ph_list_ok and ph_cmp_ok)

    # CITIZEN: list + profile + compare all say "Citizen" (not countdown)
    cit_list_ok = "Citizen" in c_cit
    cit_prof_ok = "Citizen" in prof_cit
    cit_cmp_ok  = "Citizen" in cmp_cit
    chk("S4c    Citizen: list == profile == compare (all 'Citizen')",
        cit_list_ok and cit_prof_ok and cit_cmp_ok)

    # FR: list label == profile label
    fr_list_ok = "Eligible in 0y 6m" in c_fr
    fr_prof_ok = "Eligible in 0y 6m" in prof_fr
    chk("S4d    FR: list label == profile label",
        fr_list_ok and fr_prof_ok)

finally:
    print("\n(cleanup)")
    cleanup()
    print("  done")

print("\n" + "=" * 60)
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"Cross-surface eligibility E2E: {n_pass} pass / {n_fail} fail (of {len(results)})")
sys.exit(0 if n_fail == 0 else 2)
