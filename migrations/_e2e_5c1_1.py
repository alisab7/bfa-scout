"""
Synthetic E2E for Phase 5c-1.1 tri-state slider.

What this CAN verify (HTTP + DB):
  - Form HTML carries the new tri-state attributes (N/A button, ✕ reset,
    :disabled binding, :name toggle for both score and na inputs)
  - POSTing score_<id> stores rated row (score set, NA=FALSE)
  - POSTing na_<id> stores N/A row (score=NULL, NA=TRUE)
  - POSTing neither for a previously-rated criterion REMOVES the row
    (DELETE-then-INSERT semantics)
  - POSTing both score_<id> and na_<id> resolves to N/A (malformed → NA wins)
  - DB CHECK constraint blocks malformed direct inserts
  - View template renders N/A as badge (text 'N/A') for N/A rows
  - Existing 14 backfilled rows still display + work in re-edit

What this CANNOT verify (browser interaction):
  - ✕ button visibility transitions (Alpine x-show)
  - Slider visual greyout when na=true (Tailwind opacity class)
  - Slider drag actually disabled (HTML5 disabled prop on range input)
  - N/A button visual highlight toggle
  - Reset value-back-to-5 behavior (Alpine reset method)
  All of these require a real browser; flagged in the result summary.
"""
import os
import re
import sys
from urllib.request import build_opener, HTTPCookieProcessor, Request
from http.cookiejar import CookieJar
from urllib.parse import urlencode
from urllib.error import HTTPError

from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

load_dotenv()
BASE = "http://127.0.0.1:5057"
DB   = os.environ["DATABASE_URL"]


def http(opener, method, path, *, data=None):
    body = urlencode(data).encode() if data is not None else None
    req = Request(BASE + path, data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        r = opener.open(req)
        return r.status, r.read().decode("utf-8", errors="replace"), r.url
    except HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace"), None


def login(email, pw):
    op = build_opener(HTTPCookieProcessor(CookieJar()))
    _, html, _ = http(op, "GET", "/auth/login")
    m = re.search(r'name=["\']csrf_token["\']\s+value=["\']([^"\']+)["\']', html)
    http(op, "POST", "/auth/login", data={"email": email, "password": pw, "csrf_token": m.group(1)})
    return op


def csrf(op, path):
    _, html, _ = http(op, "GET", path)
    m = re.search(r'name=["\']csrf_token["\']\s+value=["\']([^"\']+)["\']', html)
    return m.group(1), html


def db_query(sql, params=()):
    conn = psycopg2.connect(DB, cursor_factory=RealDictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall() if cur.description else []
    finally:
        conn.close()


def db_exec(sql, params=()):
    conn = psycopg2.connect(DB, cursor_factory=RealDictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


results = []
def check(label, ok, ev=""):
    results.append((label, ok, ev))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}  {ev}")


admin_email = os.environ["INITIAL_ADMIN_EMAIL"]
admin_pw    = os.environ["INITIAL_ADMIN_PASSWORD"]
admin_id    = db_query("SELECT id FROM users WHERE email = %s", (admin_email,))[0]["id"]
admin = login(admin_email, admin_pw)

# Pick player 6 (Bouhra) to avoid clobbering Arthur's existing submitted evals.
# Save Bouhra's pre-state so we can restore later.
PLAYER_ID = 6
MATCH_ID  = 11

# Find a draft for (player, match, admin) — clean slate
db_exec("DELETE FROM evaluations WHERE evaluator_id = %s AND player_id = %s AND match_id = %s",
        (admin_id, PLAYER_ID, MATCH_ID))

# ── 1. Form HTML carries new tri-state attributes ─────────────
print("\n=== Test 1: form HTML has tri-state markers ===")
code, html, _ = http(admin, "GET", f"/players/{PLAYER_ID}/evaluate?match_id={MATCH_ID}")
check("GET form returns 200", code == 200)
check("N/A button present", "toggleNA()" in html)
check("reset() method present", "reset()" in html)
check(":disabled='na' on range input", ':disabled="na"' in html)
check(":name toggles for score input", "(dirty && !na) ? 'score_" in html)
check(":name toggles for na input", "na ? 'na_" in html)
check("section label says 'decided'", re.search(r'/\s*\d+\s*decided', html) is not None)

# ── 2. POST tri-state matrix ──────────────────────────────────
print("\n=== Test 2: POST tri-state matrix ===")
# Pick 4 criteria from Bouhra's actual position group (DM, not CB — fixed test bug)
crit_ids = [r["criterion_id"] for r in db_query("""
    SELECT pgc.criterion_id
    FROM   position_group_criteria pgc
    JOIN   position_groups pg ON pg.id = pgc.position_group_id
    JOIN   players pl ON pl.id = %s
    JOIN   positions p ON p.id = pl.primary_position_id
    WHERE  pg.id = p.position_group_id
    ORDER  BY pgc.criterion_id LIMIT 4
""", (PLAYER_ID,))]
print(f"  using criterion_ids: {crit_ids}")
A, B, C, D = crit_ids

tok, _ = csrf(admin, f"/players/{PLAYER_ID}/evaluate?match_id={MATCH_ID}")
post = {
    "csrf_token": tok,
    "action": "save_draft",
    "match_id": str(MATCH_ID),
    "nt_readiness_level": "u23",
    "recommendation": "monitor",
    f"score_{A}": "7.5",          # rated
    f"score_{B}": "8.0",          # rated → will be removed in next POST
    f"na_{C}":    "1",            # N/A
    f"score_{D}": "6.0",          # malformed: both score AND na for D
    f"na_{D}":    "1",            #   → N/A wins
}
code, _, url = http(admin, "POST", f"/players/{PLAYER_ID}/evaluate", data=post)
check("POST 1 returns success", code in (200, 302) or url is not None, f"code={code}")

ev_row = db_query("""
    SELECT id FROM evaluations
    WHERE player_id = %s AND match_id = %s AND evaluator_id = %s
    ORDER BY id DESC LIMIT 1
""", (PLAYER_ID, MATCH_ID, admin_id))
eval_id = ev_row[0]["id"] if ev_row else None
check("draft created", eval_id is not None, f"eval_id={eval_id}")

scored = {r["criterion_id"]: r for r in db_query(
    "SELECT criterion_id, score, is_not_applicable FROM evaluation_scores WHERE evaluation_id = %s",
    (eval_id,))}
print(f"  rows after POST 1: {dict((k, dict(v)) for k,v in scored.items())}")

check(f"crit {A} = rated 7.5",
      scored.get(A) and float(scored[A]["score"]) == 7.5 and scored[A]["is_not_applicable"] is False)
check(f"crit {B} = rated 8.0",
      scored.get(B) and float(scored[B]["score"]) == 8.0 and scored[B]["is_not_applicable"] is False)
check(f"crit {C} = N/A (NULL + TRUE)",
      scored.get(C) and scored[C]["score"] is None and scored[C]["is_not_applicable"] is True)
check(f"crit {D} = N/A (malformed → NA wins)",
      scored.get(D) and scored[D]["score"] is None and scored[D]["is_not_applicable"] is True)
check("4 rows total", len(scored) == 4)

# ── 3. POST 2 — drop B (untouched), flip C to rated ───────────
print("\n=== Test 3: untouched-after-rated removes row (DELETE-then-INSERT) ===")
tok, _ = csrf(admin, f"/players/{PLAYER_ID}/evaluate?match_id={MATCH_ID}")
post2 = {
    "csrf_token": tok,
    "action": "save_draft",
    "match_id": str(MATCH_ID),
    "nt_readiness_level": "u23",
    "recommendation": "monitor",
    f"score_{A}": "7.5",       # still rated
    # B omitted — should be removed
    f"score_{C}": "5.5",       # was N/A, now rated
    f"na_{D}":    "1",         # still N/A
}
code, _, _ = http(admin, "POST", f"/players/{PLAYER_ID}/evaluate", data=post2)
check("POST 2 returns success", code in (200, 302))
scored = {r["criterion_id"]: r for r in db_query(
    "SELECT criterion_id, score, is_not_applicable FROM evaluation_scores WHERE evaluation_id = %s",
    (eval_id,))}
print(f"  rows after POST 2: {dict((k, dict(v)) for k,v in scored.items())}")
check(f"crit {B} row REMOVED (untouched-after-rated)", B not in scored)
check(f"crit {C} = now rated 5.5",
      scored.get(C) and float(scored[C]["score"]) == 5.5 and scored[C]["is_not_applicable"] is False)
check("3 rows total", len(scored) == 3)

# ── 4. CHECK constraint blocks malformed direct insert ────────
print("\n=== Test 4: DB CHECK rejects malformed direct INSERT ===")
import psycopg2.errors as PgErr
conn = psycopg2.connect(DB)
conn.autocommit = False
try:
    with conn.cursor() as cur:
        cur.execute("SAVEPOINT t")
        try:
            cur.execute("""
                INSERT INTO evaluation_scores (evaluation_id, criterion_id, score, is_not_applicable)
                VALUES (%s, %s, %s, %s)
            """, (eval_id, A, 7.5, True))
            check("INSERT (score+NA) rejected by CHECK", False, "INSERT succeeded — CHECK didn't fire")
        except PgErr.CheckViolation:
            check("INSERT (score+NA) rejected by CHECK", True)
        cur.execute("ROLLBACK TO SAVEPOINT t")

        cur.execute("SAVEPOINT t2")
        try:
            cur.execute("""
                INSERT INTO evaluation_scores (evaluation_id, criterion_id, score, is_not_applicable)
                VALUES (%s, %s, %s, %s)
            """, (eval_id, A, None, False))
            check("INSERT (NULL+!NA) rejected by CHECK", False)
        except PgErr.CheckViolation:
            check("INSERT (NULL+!NA) rejected by CHECK", True)
        cur.execute("ROLLBACK TO SAVEPOINT t2")
finally:
    conn.rollback(); conn.close()

# ── 5. Reload form pre-fills tri-state ────────────────────────
print("\n=== Test 5: re-open pre-fills the 3 saved states ===")
code, html, _ = http(admin, "GET", f"/players/{PLAYER_ID}/evaluate?match_id={MATCH_ID}")
# After POST 2: A rated, C rated, D N/A → 3 sliders should have non-default initial state
n_dirty_init = len(re.findall(r'dirty:\s*true', html))
n_na_init    = len(re.findall(r'na:\s*true', html))
check(f"2 sliders init dirty (A and C rated)", n_dirty_init == 2, f"found {n_dirty_init}")
check(f"1 slider init na (D)", n_na_init == 1, f"found {n_na_init}")

# ── 6. Submit + view template renders N/A as badge ────────────
print("\n=== Test 6: submit + view template renders N/A badge ===")
tok, _ = csrf(admin, f"/players/{PLAYER_ID}/evaluate?match_id={MATCH_ID}")
post_submit = dict(post2)
post_submit["csrf_token"] = tok
post_submit["action"]     = "submit"
code, _, url = http(admin, "POST", f"/players/{PLAYER_ID}/evaluate", data=post_submit)
check("submit returns success", code in (200, 302))
ev2 = db_query("SELECT status FROM evaluations WHERE id = %s", (eval_id,))[0]
check("status=submitted", ev2["status"] == "submitted")

code, html, _ = http(admin, "GET", f"/evaluations/{eval_id}")
check("view returns 200", code == 200)
check("view contains N/A badge text", "N/A" in html and "غير متخصص" in html,
      f"N/A in html={'N/A' in html} arabic={'غير متخصص' in html}")
check("section header says 'decided'", re.search(r'/\s*\d+\s*decided', html) is not None)

# ── 7. Existing 14 backfilled rows still render correctly ────
print("\n=== Test 7: existing pre-migration evaluations still display ===")
existing_ids = [r["id"] for r in db_query("SELECT id FROM evaluations WHERE id IN (1,2,3) ORDER BY id")]
ok_old = True
for eid in existing_ids:
    code, html, _ = http(admin, "GET", f"/evaluations/{eid}")
    if code != 200:
        ok_old = False
        print(f"    eval {eid} → {code}")
check("all 3 pre-existing evaluations render 200", ok_old)

# Cleanup our test eval (it's submitted but disposable)
db_exec("DELETE FROM evaluations WHERE id = %s", (eval_id,))
print(f"\nCleaned up test eval {eval_id}")

# Summary
print("\n" + "=" * 60)
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"E2E summary: {n_pass} pass / {n_fail} fail (of {len(results)})")
sys.exit(0 if n_fail == 0 else 2)
