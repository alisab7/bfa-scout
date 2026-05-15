"""
Phase 5c-3 follow-up E2E: full new-player workflow.

Confirms /players/new now mirrors all the structured pickers + admin
eligibility/residency block that Phase 5c-1, 5c-2, and 5c-3 added to
/players/<id>/edit. Plus role-gating: scout creating a player must
have admin-only fields silently dropped.
"""
import os, re, sys
from urllib.request import build_opener, HTTPCookieProcessor, Request
from http.cookiejar import CookieJar
from urllib.parse import urlencode

from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor
from werkzeug.security import generate_password_hash

load_dotenv()
BASE = "http://127.0.0.1:5057"


def make_session():
    return build_opener(HTTPCookieProcessor(CookieJar()))


def http(op, method, path, *, data=None):
    body = urlencode(data).encode() if data is not None else None
    req = Request(BASE + path, data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    r = op.open(req)
    return r.status, r.read().decode("utf-8", errors="replace"), r.url


def login(email, pw):
    op = make_session()
    _, html, _ = http(op, "GET", "/auth/login")
    m = re.search(r'name=["\']csrf_token["\']\s+value=["\']([^"\']+)["\']', html)
    http(op, "POST", "/auth/login",
         data={"email": email, "password": pw, "csrf_token": m.group(1)})
    return op


def csrf(op, path):
    _, html, _ = http(op, "GET", path)
    m = re.search(r'name=["\']csrf_token["\']\s+value=["\']([^"\']+)["\']', html)
    return m.group(1), html


def db_query(sql, params=()):
    conn = psycopg2.connect(os.environ["DATABASE_URL"], cursor_factory=RealDictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall() if cur.description else []
    finally:
        conn.close()


def db_exec(sql, params=()):
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
    finally:
        conn.close()


results = []
def chk(label, ok, ev=""):
    results.append((label, ok, ev))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}  {ev}")


# Look up reference ids
hidd_id = db_query("SELECT id FROM clubs WHERE name = 'Al-Hidd'")[0]["id"]
lcmf_id = db_query("SELECT id FROM positions WHERE code = 'LCMF'")[0]["id"]
NID_ADMIN = "TESTNEW-ADMIN-001"
NID_SCOUT = "TESTNEW-SCOUT-001"

# Cleanup any prior runs
db_exec("DELETE FROM players WHERE national_id IN (%s, %s)", (NID_ADMIN, NID_SCOUT))

# ── Admin path ───────────────────────────────────────────
admin = login(os.environ["INITIAL_ADMIN_EMAIL"], os.environ["INITIAL_ADMIN_PASSWORD"])

print("=== GET /players/new (admin) — structured pickers + admin block ===")
code, html, _ = http(admin, "GET", "/players/new")
chk("GET returns 200", code == 200)
chk("nationality_code dropdown",          'name="nationality_code"' in html and "— Select nationality —" in html)
chk(">= 250 nationality options",         html.count('<option value="') > 250)
chk("Bahrain pinned before AFG",          html.find('value="BHR"') < html.find('value="AFG"'))
chk("club_id dropdown w/ optgroups",      'name="club_id"' in html and "Premier League" in html and "First Division" in html)
chk("'Other (free text)' option",         "Other (free text)" in html)
chk("Al-Muharraq option present",         ">Al-Muharraq</option>" in html)
chk("admin eligibility fieldset visible", "National-Team Eligibility (admin)" in html)
chk("residency-start input",              'name="bahrain_residency_start_date"' in html)
chk("eligible_from_date input",           'name="eligible_from_date"' in html)
chk("residency notes textarea",           'name="bahrain_residency_notes"' in html)
chk("eligibility_notes_admin textarea",   'name="eligibility_notes_admin"' in html)

print("\n=== POST /players/new (admin) — full workflow ===")
csrf_tok, _ = csrf(admin, "/players/new")
code, _, url = http(admin, "POST", "/players/new", data={
    "csrf_token": csrf_tok,
    "full_name":          "Phase5C3 NewPlayer",
    "full_name_ar":       "لاعب جديد",
    "national_id":        NID_ADMIN,
    "dob":                "2002-06-15",
    "primary_position_id": str(lcmf_id),
    "nationality":        "BR",
    "nationality_code":   "BRA",
    "club_id":            str(hidd_id),
    "height_cm":          "178",
    "weight_kg":          "74",
    "notes":              "Full-workflow E2E test player",
    "nationality_status": "foreign_residency",
    "bahrain_residency_start_date": "2022-08-15",
    "eligible_from_date": "2027-08-15",
    "bahrain_residency_notes":   "Continuous residency since 2022",
    "eligibility_notes_admin":   "Pending FA paperwork",
})
chk("admin POST returns success", code in (200, 302) or url is not None,
    f"code={code} url={url}")

p_rows = db_query("""
    SELECT id, full_name, full_name_ar, dob, primary_position_id,
           nationality_code, club_id, current_club,
           nationality_status, eligible_from_date,
           bahrain_residency_start_date, bahrain_residency_notes,
           eligibility_notes_admin
    FROM   players WHERE national_id = %s
""", (NID_ADMIN,))
chk("player row created", len(p_rows) == 1)
if p_rows:
    p = p_rows[0]
    chk("full_name persisted",                 p["full_name"] == "Phase5C3 NewPlayer")
    chk("full_name_ar persisted",              p["full_name_ar"] == "لاعب جديد")
    chk("dob persisted",                       str(p["dob"]) == "2002-06-15")
    chk("primary_position_id (LCMF)",          p["primary_position_id"] == lcmf_id)
    chk("nationality_code = BRA",              p["nationality_code"] == "BRA")
    chk("club_id = Al-Hidd",                   p["club_id"] == hidd_id)
    chk("current_club denorm cache = Al-Hidd", p["current_club"] == "Al-Hidd")
    chk("nationality_status = foreign_residency", p["nationality_status"] == "foreign_residency")
    chk("bahrain_residency_start_date",        str(p["bahrain_residency_start_date"]) == "2022-08-15")
    chk("eligible_from_date",                  str(p["eligible_from_date"]) == "2027-08-15")
    chk("bahrain_residency_notes",             p["bahrain_residency_notes"] == "Continuous residency since 2022")
    chk("eligibility_notes_admin",             p["eligibility_notes_admin"] == "Pending FA paperwork")

    print("\n=== GET new player profile — verify cards ===")
    _, html, _ = http(admin, "GET", f"/players/{p['id']}")
    chk("profile returns 200",                 "BFA Scout" in html)
    chk("flag emoji 🇧🇷 (BRA)",                "🇧🇷" in html)
    chk("eligibility ⏳ + 'Eligible in'",      "⏳" in html and "Eligible in" in html)
    chk("Route line shows 'residency'",        "Route:" in html and "residency" in html.lower())
    chk("bio counts strip rendered",           "Wyscout match" in html and "evaluation" in html)
    chk("Al-Hidd visible in header",           "Al-Hidd" in html)

# ── Scout path: admin fields silently dropped ────────────
print("\n=== Scout POST — admin-only fields silently dropped ===")
db_exec("UPDATE users SET password_hash = %s WHERE email = 'scout@bfa.bh'",
        (generate_password_hash("e2e-scout-tmp-pw", method="pbkdf2:sha256:600000"),))
scout = login("scout@bfa.bh", "e2e-scout-tmp-pw")

code, html, _ = http(scout, "GET", "/players/new")
chk("scout GET returns 200", code == 200)
chk("scout DOES NOT see eligibility fieldset",
    "National-Team Eligibility (admin)" not in html)

csrf_tok, _ = csrf(scout, "/players/new")
code, _, url = http(scout, "POST", "/players/new", data={
    "csrf_token": csrf_tok,
    "full_name":  "Scout NewPlayer",
    "national_id": NID_SCOUT,
    "primary_position_id": str(lcmf_id),
    "nationality_code": "EGY",
    "club_id": str(hidd_id),
    # Admin fields the scout shouldn't be able to set:
    "nationality_status": "bahraini",
    "bahrain_residency_start_date": "2020-01-01",
    "eligible_from_date": "2025-01-01",
    "eligibility_notes_admin": "scout sneaking in admin field",
})
chk("scout POST returns success", code in (200, 302) or url is not None)

p2_rows = db_query("""SELECT nationality_code, club_id, nationality_status,
                             bahrain_residency_start_date, eligible_from_date,
                             eligibility_notes_admin
                      FROM players WHERE national_id = %s""", (NID_SCOUT,))
chk("scout-created player exists", len(p2_rows) == 1)
if p2_rows:
    p2 = p2_rows[0]
    chk("scout writes nationality_code (EGY)", p2["nationality_code"] == "EGY")
    chk("scout writes club_id (Al-Hidd)",       p2["club_id"] == hidd_id)
    chk("nationality_status NOT written",       p2["nationality_status"] is None)
    chk("bahrain_residency_start_date NOT written", p2["bahrain_residency_start_date"] is None)
    chk("eligible_from_date NOT written",       p2["eligible_from_date"] is None)
    chk("eligibility_notes_admin NOT written",  p2["eligibility_notes_admin"] is None)

# Cleanup ephemerals + restore scout password
print("\n=== Cleanup ===")
db_exec("DELETE FROM players WHERE national_id IN (%s, %s)", (NID_ADMIN, NID_SCOUT))
db_exec("UPDATE users SET password_hash = %s WHERE email = 'scout@bfa.bh'",
        (generate_password_hash("phase5c3-temp-reset-2026-05-09",
                                method="pbkdf2:sha256:600000"),))
print("  removed 2 test players + restored scout password to documented temp")

print("\n" + "=" * 60)
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"E2E summary: {n_pass} pass / {n_fail} fail (of {len(results)})")
sys.exit(0 if n_fail == 0 else 2)
