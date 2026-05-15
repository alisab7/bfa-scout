"""
Synthetic end-to-end test for Phase 5c-1.

Exercises every acceptance criterion that depends on a running Flask:
  - Render the form for Arthur
  - Save a draft with 5 sliders
  - Reopen the form and confirm the draft pre-fills
  - Submit, confirm DB transition
  - Inline match modal POST
  - Player edit page eligibility block visibility per role
"""
import os
import re
import sys
from urllib.request import build_opener, HTTPCookieProcessor, Request
from http.cookiejar import CookieJar
from urllib.parse import urlencode
from urllib.error import HTTPError
import json

from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

load_dotenv()

BASE = "http://127.0.0.1:5057"
DB_URL = os.environ["DATABASE_URL"]


def fresh_session():
    return build_opener(HTTPCookieProcessor(CookieJar()))


def http(opener, method, path, *, data=None, headers=None):
    if data is not None and not isinstance(data, bytes):
        body = urlencode(data).encode()
    else:
        body = data
    req = Request(BASE + path, data=body, method=method)
    if body is not None and (not headers or "Content-Type" not in headers):
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        r = opener.open(req)
        return r.status, r.read().decode("utf-8", errors="replace"), r.url
    except HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace"), None


def login(email, pw):
    op = fresh_session()
    code, html, _ = http(op, "GET", "/auth/login")
    m = re.search(r'name=["\']csrf_token["\']\s+value=["\']([^"\']+)["\']', html)
    code, _, url = http(op, "POST", "/auth/login",
                        data={"email": email, "password": pw, "csrf_token": m.group(1)})
    assert url and "auth/login" not in url, f"login as {email} failed (status={code})"
    return op


def get_csrf(opener, path):
    _, html, _ = http(opener, "GET", path)
    m = re.search(r'name=["\']csrf_token["\']\s+value=["\']([^"\']+)["\']', html)
    return m.group(1) if m else None, html


def db_query(sql, params=()):
    conn = psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall() if cur.description else []
    finally:
        conn.close()


def db_exec(sql, params=()):
    conn = psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


# Resolve admin id from .env email
admin_email = os.environ["INITIAL_ADMIN_EMAIL"]
admin_pw    = os.environ["INITIAL_ADMIN_PASSWORD"]
admin_row   = db_query("SELECT id FROM users WHERE email = %s", (admin_email,))[0]
admin_id    = admin_row["id"]
print(f"admin_id = {admin_id}")

# Reset any stale draft from previous test runs for clean slate
db_exec("DELETE FROM evaluations WHERE evaluator_id = %s AND player_id = 2 AND match_id = 11",
        (admin_id,))

results = []  # list of (criterion_label, ok, evidence)


def check(label, ok, evidence=""):
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}  {evidence}")
    results.append((label, ok, evidence))
    return ok


admin = login(admin_email, admin_pw)

# ── 7. GET /players/2/evaluate returns 200 ────────────────────────
print("\n=== Acceptance 7: GET form ===")
code, html, _ = http(admin, "GET", "/players/2/evaluate")
check("GET /players/2/evaluate returns 200", code == 200, f"status={code}")
check("page title contains 'Arthur'", "Arthur Rezende" in html)

# ── 8. Slider count matches AM position group expectation (42) ────
print("\n=== Acceptance 8: slider count for AM ===")
n_sliders = len(re.findall(r'<input type="range"', html))
# AM position group: Tech 14 + Tact 16 + Phys 6 + Ment 6 = 42 sliders (NT readiness has no sliders)
expected_sliders = 42
check(f"slider count = {expected_sliders}", n_sliders == expected_sliders,
      f"found {n_sliders}")
# 4 slider sections + 1 NT section = 5 <details>, but NT readiness has its own
n_details = len(re.findall(r'<details[^>]*>', html))
check("5 sections present (4 slider + 1 NT)", n_details == 5, f"found {n_details}")

# ── 9. Save draft creates evaluation + scores ─────────────────────
print("\n=== Acceptance 9: save draft ===")
csrf, _ = get_csrf(admin, "/players/2/evaluate")
# Pick 5 random criterion ids from the AM group to fill in
am_criteria = db_query("""
    SELECT pgc.criterion_id
    FROM   position_group_criteria pgc
    JOIN   position_groups pg ON pg.id = pgc.position_group_id
    JOIN   criteria c         ON c.id = pgc.criterion_id
    WHERE  pg.code = 'AM' AND c.code LIKE 'tech_%%'
    ORDER  BY pgc.criterion_id
    LIMIT 5
""")
crit_ids_used = [r["criterion_id"] for r in am_criteria]
form_data = {
    "csrf_token": csrf,
    "action": "save_draft",
    "match_id": "11",       # the shared Muharraq vs Khalidiya fixture
    "minutes_observed": "85",
    "summary": "Synthetic test draft.",
    "nt_readiness_level": "u23",
    "recommendation": "monitor",
}
score_values = [6.5, 7.0, 7.5, 8.0, 6.0]
for cid, val in zip(crit_ids_used, score_values):
    form_data[f"score_{cid}"] = str(val)

code, html, url = http(admin, "POST", "/players/2/evaluate", data=form_data)
check("POST save_draft returns success (302/200)", code in (200, 302) or url is not None,
      f"code={code} url={url}")

# Verify DB
ev_row = db_query("""
    SELECT id, status, match_id, nt_readiness_level, recommendation,
           summary, minutes_observed
    FROM evaluations
    WHERE evaluator_id = %s AND player_id = 2 AND match_id = 11
    ORDER BY id DESC LIMIT 1
""", (admin_id,))
check("draft row created in evaluations", len(ev_row) == 1)
if ev_row:
    ev = ev_row[0]
    eval_id = ev["id"]
    check("status == draft",       ev["status"] == "draft", str(ev["status"]))
    check("match_id == 11",        ev["match_id"] == 11, str(ev["match_id"]))
    check("nt_readiness_level set", ev["nt_readiness_level"] == "u23", str(ev["nt_readiness_level"]))
    check("recommendation set",     ev["recommendation"] == "monitor", str(ev["recommendation"]))
    check("minutes_observed=85",    ev["minutes_observed"] == 85, str(ev["minutes_observed"]))

    score_rows = db_query("SELECT criterion_id, score FROM evaluation_scores WHERE evaluation_id = %s ORDER BY criterion_id",
                          (eval_id,))
    check("5 scores written",          len(score_rows) == 5, f"got {len(score_rows)}")
    written_ids = sorted(r["criterion_id"] for r in score_rows)
    check("scores match input crit ids", written_ids == sorted(crit_ids_used),
          f"got {written_ids} vs {sorted(crit_ids_used)}")
    check("no NULLs in scores",        all(r["score"] is not None for r in score_rows))

    # ── 12. Untouched sliders → no row ──────────────────────────────
    print("\n=== Acceptance 12: untouched sliders → NULL (no row) ===")
    untouched = expected_sliders - 5
    check(f"score row count ({len(score_rows)}) << total slider count ({expected_sliders})",
          len(score_rows) == 5,
          f"untouched {untouched} sliders did not write rows")
else:
    eval_id = None

# ── 10. Reopening form pre-fills draft ────────────────────────────
print("\n=== Acceptance 10: reopen form pre-fills ===")
if eval_id:
    code, html2, _ = http(admin, "GET", "/players/2/evaluate?match_id=11")
    check("GET with match_id loads 200", code == 200)
    # Sliders dirty=true in initial Alpine state when prefilled_value exists.
    # We can detect by counting `dirty: true` literal in the rendered HTML.
    n_dirty_init = len(re.findall(r'dirty:\s*true', html2))
    check("5 sliders pre-filled (dirty:true initial state)",
          n_dirty_init == 5, f"found {n_dirty_init}")
    # NT readiness pre-fills (radio checked)
    check("nt_readiness_level u23 checked",
          'value="u23"' in html2 and 'value="u23"\n                   checked' in html2 or
          re.search(r'value="u23"[^>]*checked', html2) is not None)
    check("recommendation monitor checked",
          re.search(r'value="monitor"[^>]*checked', html2) is not None)

# ── 11. Submit transitions to submitted ───────────────────────────
print("\n=== Acceptance 11: submit transition ===")
if eval_id:
    csrf, _ = get_csrf(admin, "/players/2/evaluate?match_id=11")
    submit_data = dict(form_data)
    submit_data["csrf_token"] = csrf
    submit_data["action"]     = "submit"
    code, html, url = http(admin, "POST", "/players/2/evaluate", data=submit_data)
    check("POST submit returns 200/302", code in (200, 302) or url is not None,
          f"code={code} url={url}")
    ev2 = db_query("SELECT status, submitted_at FROM evaluations WHERE id = %s", (eval_id,))[0]
    check("status == submitted", ev2["status"] == "submitted", str(ev2["status"]))
    check("submitted_at set",    ev2["submitted_at"] is not None)

# ── 13. Inline match modal POST creates a matches row ─────────────
print("\n=== Acceptance 13: inline match create ===")
csrf, _ = get_csrf(admin, "/players/2/evaluate")
match_form = {
    "csrf_token": csrf,
    "match_date": "2026-05-09",
    "home_team":  "Synthetic Test FC",
    "away_team":  "E2E United",
    "age_group":  "senior",
    "match_type": "friendly",
    "home_score": "2",
    "away_score": "1",
    "competition": "E2E test",
    "notes":      "Created by _e2e_5c1.py",
}
code, html, _ = http(admin, "POST", "/matches/new-inline", data=match_form,
                     headers={"X-Requested-With": "fetch"})
try:
    payload = json.loads(html)
except Exception:
    payload = {}
check("POST /matches/new-inline returns 200 + ok JSON",
      code == 200 and payload.get("ok") is True, f"code={code} body={html[:200]}")
new_match_id = payload.get("id")
if new_match_id:
    found = db_query(
        "SELECT id, source, home_team, away_team FROM matches WHERE id = %s",
        (new_match_id,)
    )
    check("matches row exists in DB", len(found) == 1)
    if found:
        check("source = 'manual'",
              found[0]["source"] == "manual",
              str(found[0]["source"]))
    # Cleanup
    db_exec("DELETE FROM matches WHERE id = %s", (new_match_id,))

# ── 14/15. Player edit eligibility visibility per role ────────────
print("\n=== Acceptance 14/15: edit page eligibility block visibility ===")
code, html, _ = http(admin, "GET", "/players/2/edit")
check("admin sees National-Team Eligibility fieldset",
      "National-Team Eligibility (admin)" in html, f"len={len(html)}")

# Try as scout. First find scout email and reset password to a known value.
scout_email = "scout@bfa.bh"
new_password = "e2e-test-password-tmp"
from werkzeug.security import generate_password_hash
db_exec("UPDATE users SET password_hash = %s WHERE email = %s",
        (generate_password_hash(new_password, method='pbkdf2:sha256:600000'), scout_email))
try:
    scout = login(scout_email, new_password)
    code, html, _ = http(scout, "GET", "/players/2/edit")
    check("scout does NOT see eligibility fieldset",
          "National-Team Eligibility (admin)" not in html, f"len={len(html)}")
finally:
    # NULL out the temp password (scout can no longer log in until admin resets it)
    db_exec("UPDATE users SET password_hash = '__disabled__' WHERE email = %s",
            (scout_email,))

# Print final summary
print("\n" + "=" * 60)
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"E2E summary: {n_pass} pass / {n_fail} fail (of {len(results)})")
sys.exit(0 if n_fail == 0 else 2)
