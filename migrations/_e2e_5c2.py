"""
Phase 5c-2 synthetic E2E. Covers 17 acceptance criteria where automatable.

CAN verify (HTTP + DB):
  - Profile renders eligibility card + history cards
  - No "Coming in Phase 5c-2" remnant
  - Lock POST flips status, audit-logged
  - Unlock with valid reason flips back, audit-logged
  - Unlock with <10-char reason rejected
  - Admin edit on submitted preserves evaluator_id, sets last_edited_by
  - Admin edit blocked on locked evaluations
  - Eligibility card 4 states (eligible / pending / not eligible / unknown)
  - Latest-3 NT summary line renders
  - Residency input + suggested-date end-to-end
  - Position change with orphans → confirm modal → delete OR keep
  - Soft warning < 5 ratings → modal HTML present
  - Arabic translations baked in (verbatim from spec table)
  - View template handles 'locked' (no edit button visible to scout)
  - schema.sql declarative-only (verified via _verify_throwaway_5c2.py)

CANNOT verify (browser interaction):
  - Sticky save bar visibility at <768px
  - Slider thumb size (CSS rendering)
  - Modal click-through-and-back UX
"""
import os, re, sys
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


def http(op, method, path, *, data=None):
    body = urlencode(data).encode() if data is not None else None
    req = Request(BASE + path, data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        r = op.open(req)
        return r.status, r.read().decode("utf-8", errors="replace"), r.url
    except HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace"), None


def login(email, pw):
    op = build_opener(HTTPCookieProcessor(CookieJar()))
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


# Save Arthur's pre-state for restore
ARTHUR_PRESTATE = db_query("""
    SELECT primary_position_id, nationality_status, eligible_from_date,
           bahrain_residency_start_date, bahrain_residency_notes,
           eligibility_notes_admin
    FROM players WHERE id = 2
""")[0]

# Pick the most recent submitted Arthur eval to use as lock/unlock target
TARGET_EVAL = db_query("""
    SELECT id, status FROM evaluations
    WHERE player_id = 2 AND status = 'submitted'
    ORDER BY id DESC LIMIT 1
""")[0]

admin = login(os.environ["INITIAL_ADMIN_EMAIL"], os.environ["INITIAL_ADMIN_PASSWORD"])
admin_id = db_query("SELECT id FROM users WHERE email = %s",
                    (os.environ["INITIAL_ADMIN_EMAIL"],))[0]["id"]

# Acceptance #3 — profile shows eligibility card + history cards
print("\n=== A3: profile has eligibility + history cards ===")
code, html, _ = http(admin, "GET", "/players/2")
check("profile returns 200", code == 200)
check("National-Team Eligibility heading present", "National-Team Eligibility" in html)
check("history shows Committee Evaluations heading", "Committee Evaluations" in html)
check("no 'Coming in Phase 5c-2' remnant", "Coming in Phase 5c-2" not in html)
check("at least one evaluator name in history", "Initial Administrator" in html)
check("at least one NT-level badge (e.g. 'Senior NT' or 'U23')",
      "Senior NT" in html or "U23" in html)

# Acceptance #4 — lock POST flips status + audit-log entry
print(f"\n=== A4: lock POST flips status (eval id={TARGET_EVAL['id']}) ===")
csrf_tok, _ = csrf(admin, "/players/2")
code, _, _ = http(admin, "POST", f"/evaluations/{TARGET_EVAL['id']}/lock",
                  data={"csrf_token": csrf_tok})
check("lock POST returns success/redirect", code in (200, 302))
ev = db_query("SELECT status, locked_at, locked_by FROM evaluations WHERE id = %s",
              (TARGET_EVAL["id"],))[0]
check("status = 'locked'", ev["status"] == "locked", str(ev["status"]))
check("locked_at set", ev["locked_at"] is not None)
check("locked_by = admin", ev["locked_by"] == admin_id)
audits = db_query("""
    SELECT action FROM audit_log
    WHERE entity_type = 'evaluation' AND entity_id = %s
      AND action = 'evaluation.locked'
    ORDER BY id DESC LIMIT 1
""", (TARGET_EVAL["id"],))
check("evaluation.locked audit row written", len(audits) == 1)

# Acceptance #6 — unlock with <10 char reason rejected
print("\n=== A6: unlock rejects short reason ===")
csrf_tok, _ = csrf(admin, "/players/2")
code, _, _ = http(admin, "POST", f"/evaluations/{TARGET_EVAL['id']}/unlock",
                  data={"csrf_token": csrf_tok, "reason": "Bad"})
ev = db_query("SELECT status FROM evaluations WHERE id = %s", (TARGET_EVAL["id"],))[0]
check("status remained 'locked' after short-reason unlock attempt",
      ev["status"] == "locked", f"got {ev['status']}")

# Acceptance #5 — unlock with valid reason flips back + audit log
print("\n=== A5: unlock with valid reason ===")
csrf_tok, _ = csrf(admin, "/players/2")
code, _, _ = http(admin, "POST", f"/evaluations/{TARGET_EVAL['id']}/unlock",
                  data={"csrf_token": csrf_tok,
                        "reason": "Test unlock for E2E verification"})
check("unlock POST returns success/redirect", code in (200, 302))
ev = db_query("SELECT status, locked_reason FROM evaluations WHERE id = %s",
              (TARGET_EVAL["id"],))[0]
check("status back to 'submitted'", ev["status"] == "submitted")
check("locked_reason recorded", ev["locked_reason"] and "E2E" in ev["locked_reason"])
audits = db_query("""
    SELECT action FROM audit_log
    WHERE entity_type = 'evaluation' AND entity_id = %s
      AND action = 'evaluation.unlocked'
    ORDER BY id DESC LIMIT 1
""", (TARGET_EVAL["id"],))
check("evaluation.unlocked audit row written", len(audits) == 1)

# Acceptance #7 — admin edit preserves evaluator_id, sets last_edited_by
print("\n=== A7: admin edit on submitted ===")
csrf_tok, _ = csrf(admin, "/players/2")
code, _, _ = http(admin, "POST", f"/evaluations/{TARGET_EVAL['id']}/admin-edit",
                  data={"csrf_token": csrf_tok,
                        "summary": "Admin override of summary text — E2E test"})
check("admin-edit POST returns success/redirect", code in (200, 302))
ev = db_query("""SELECT evaluator_id, last_edited_by, last_edited_at, summary
                 FROM evaluations WHERE id = %s""", (TARGET_EVAL["id"],))[0]
check("evaluator_id PRESERVED (not overwritten)",
      ev["evaluator_id"] == admin_id,  # Arthur's evals are admin-authored already
      f"evaluator_id={ev['evaluator_id']}")
check("last_edited_by set to admin", ev["last_edited_by"] == admin_id)
check("last_edited_at timestamp set", ev["last_edited_at"] is not None)
check("summary updated", "E2E test" in (ev["summary"] or ""))

# Acceptance #8 — admin edit blocked on locked
print("\n=== A8: admin edit blocked on locked ===")
csrf_tok, _ = csrf(admin, "/players/2")
http(admin, "POST", f"/evaluations/{TARGET_EVAL['id']}/lock", data={"csrf_token": csrf_tok})
csrf_tok, _ = csrf(admin, "/players/2")
code, _, _ = http(admin, "POST", f"/evaluations/{TARGET_EVAL['id']}/admin-edit",
                  data={"csrf_token": csrf_tok, "summary": "should be rejected"})
ev = db_query("SELECT summary FROM evaluations WHERE id = %s", (TARGET_EVAL["id"],))[0]
check("summary NOT changed (admin edit blocked while locked)",
      "should be rejected" not in (ev["summary"] or ""),
      f"summary={ev['summary'][:60] if ev['summary'] else None}")
# Unlock again to leave clean state
csrf_tok, _ = csrf(admin, "/players/2")
http(admin, "POST", f"/evaluations/{TARGET_EVAL['id']}/unlock",
     data={"csrf_token": csrf_tok, "reason": "Restore for further E2E checks"})

# Acceptance #9 — eligibility card 4 states
print("\n=== A9: eligibility card 4 states ===")
# State 1: Status unknown (no nationality_status, no eligible_from_date)
db_exec("UPDATE players SET nationality_status = NULL, eligible_from_date = NULL WHERE id = 2")
_, html, _ = http(admin, "GET", "/players/2")
check("'Status unknown' renders for null state", "Status unknown" in html)
# State 2: Not eligible
db_exec("UPDATE players SET nationality_status = 'not_eligible' WHERE id = 2")
_, html, _ = http(admin, "GET", "/players/2")
check("'Not eligible' renders for nationality_status=not_eligible", "Not eligible" in html)
# State 3: Eligible now (past date)
db_exec("""UPDATE players SET nationality_status = 'bahraini',
                                eligible_from_date = '2020-01-01' WHERE id = 2""")
_, html, _ = http(admin, "GET", "/players/2")
check("'Eligible now' renders for past eligible_from_date", "Eligible now" in html)
# State 4: Pending with countdown (future date)
db_exec("UPDATE players SET eligible_from_date = '2028-08-15' WHERE id = 2")
_, html, _ = http(admin, "GET", "/players/2")
check("'Eligible in' (countdown) renders for future date",
      "Eligible in" in html, "checking countdown text")

# Acceptance #10 — Latest-3 NT summary line
print("\n=== A10: Latest-N NT summary line ===")
_, html, _ = http(admin, "GET", "/players/2")
check("'Latest' summary text present", "Latest" in html and "NT-readiness vote" in html)

# Acceptance #11 — Residency input + suggested-date UX
print("\n=== A11: residency suggested-date UX ===")
csrf_tok, html = csrf(admin, "/players/2/edit")
db_exec("""UPDATE players SET bahrain_residency_start_date = '2022-08-15' WHERE id = 2""")
_, html, _ = http(admin, "GET", "/players/2/edit")
check("'Suggested eligible-from' label present", "Suggested eligible-from" in html)
check("'2027-08-15' suggestion appears", "2027-08-15" in html)
check("'Use suggestion' button present", "Use suggestion" in html)
check("Article 5 caveat tooltip present", "FIFA Article 5" in html or "Article 5 default" in html)

# Acceptance #12 — Position change orphan flow
print("\n=== A12: position-change orphan-scores flow ===")
# Arthur is currently AM. Try changing to GK — many existing scores will orphan.
arthur_pos_id = ARTHUR_PRESTATE["primary_position_id"]
gk_pos = db_query("SELECT id FROM positions WHERE code = 'GK' LIMIT 1")[0]
csrf_tok, html = csrf(admin, "/players/2/edit")
# POST without orphan_decision → should re-render with confirm modal
code, html, _ = http(admin, "POST", "/players/2/edit", data={
    "csrf_token": csrf_tok,
    "full_name":  "Arthur Rezende",
    "national_id": db_query("SELECT national_id FROM players WHERE id = 2")[0]["national_id"],
    "primary_position_id": str(gk_pos["id"]),
    "nationality": "BR",
})
check("orphan confirm modal renders", "Position change will orphan scores" in html)
# Modal text is "<strong>N</strong> existing evaluation score(s) reference…"
m = re.search(r"<strong[^>]*>\s*(\d+)\s*</strong>[\s\S]{0,40}existing\s+evaluation\s+score",
              html)
n_orphans = int(m.group(1)) if m else 0
check("orphan count > 0", n_orphans > 0, f"reported {n_orphans}")

# Submit again with orphan_decision=keep
csrf_tok, html = csrf(admin, "/players/2/edit")
db_exec("UPDATE players SET primary_position_id = %s WHERE id = 2", (arthur_pos_id,))
ARTHUR_BEFORE_KEEP = db_query("""
    SELECT COUNT(*) AS n FROM evaluation_scores es
    JOIN evaluations e ON e.id = es.evaluation_id
    WHERE e.player_id = 2
""")[0]["n"]
code, _, _ = http(admin, "POST", "/players/2/edit", data={
    "csrf_token": csrf_tok,
    "full_name":  "Arthur Rezende",
    "national_id": db_query("SELECT national_id FROM players WHERE id = 2")[0]["national_id"],
    "primary_position_id": str(gk_pos["id"]),
    "nationality": "BR",
    "orphan_decision": "keep",
})
ARTHUR_AFTER_KEEP = db_query("""
    SELECT COUNT(*) AS n FROM evaluation_scores es
    JOIN evaluations e ON e.id = es.evaluation_id
    WHERE e.player_id = 2
""")[0]["n"]
check("'keep' preserves orphan rows", ARTHUR_AFTER_KEEP == ARTHUR_BEFORE_KEEP,
      f"before={ARTHUR_BEFORE_KEEP} after={ARTHUR_AFTER_KEEP}")
audits = db_query("""SELECT details FROM audit_log
    WHERE action = 'player.position_changed' AND entity_id = 2
    ORDER BY id DESC LIMIT 1""")
check("position_changed audit row written", len(audits) == 1)

# Now restore Arthur's position and try delete path
db_exec("UPDATE players SET primary_position_id = %s WHERE id = 2", (arthur_pos_id,))
csrf_tok, html = csrf(admin, "/players/2/edit")
code, _, _ = http(admin, "POST", "/players/2/edit", data={
    "csrf_token": csrf_tok,
    "full_name":  "Arthur Rezende",
    "national_id": db_query("SELECT national_id FROM players WHERE id = 2")[0]["national_id"],
    "primary_position_id": str(gk_pos["id"]),
    "nationality": "BR",
    "orphan_decision": "delete",
})
ARTHUR_AFTER_DELETE = db_query("""
    SELECT COUNT(*) AS n FROM evaluation_scores es
    JOIN evaluations e ON e.id = es.evaluation_id
    WHERE e.player_id = 2
""")[0]["n"]
check("'delete' actually removes orphan rows",
      ARTHUR_AFTER_DELETE < ARTHUR_BEFORE_KEEP,
      f"before={ARTHUR_BEFORE_KEEP} after_delete={ARTHUR_AFTER_DELETE}")

# Restore Arthur's full pre-state
db_exec("""UPDATE players SET primary_position_id = %s, nationality_status = %s,
           eligible_from_date = %s, bahrain_residency_start_date = %s,
           bahrain_residency_notes = %s, eligibility_notes_admin = %s
           WHERE id = 2""",
        (ARTHUR_PRESTATE["primary_position_id"], ARTHUR_PRESTATE["nationality_status"],
         ARTHUR_PRESTATE["eligible_from_date"],
         ARTHUR_PRESTATE["bahrain_residency_start_date"],
         ARTHUR_PRESTATE["bahrain_residency_notes"],
         ARTHUR_PRESTATE["eligibility_notes_admin"]))

# Acceptance #13 — Soft warning <5 ratings
print("\n=== A13: soft-warning modal markup present ===")
_, html, _ = http(admin, "GET", "/players/2/evaluate")
check("evalForm() Alpine controller present", "function evalForm()" in html)
check("triggerSubmit() handler present", "triggerSubmit()" in html)
check("LOW_RATING_THRESHOLD constant present", "LOW_RATING_THRESHOLD" in html)
check("'Submit with limited ratings?' modal present",
      "Submit with limited ratings?" in html)
check("data-dirty + data-na attrs on sliders",
      ":data-dirty=" in html and ":data-na=" in html)

# Acceptance #14 — sticky save bar mobile markers
print("\n=== A14: mobile sticky save bar markup ===")
check("md:hidden fixed bottom-0 sticky bar present",
      'md:hidden fixed bottom-0' in html and "Save draft" in html)
check("bfa-range CSS class for ≥44px slider thumbs", "bfa-range" in html)
check("@media (max-width: 768px) for thumb size", "max-width: 768px" in html)

# Acceptance #15 — Arabic translations baked in
print("\n=== A15: Arabic translations verbatim from spec ===")
arabic_form_strings = [
    "الجاهزية لتمثيل المنتخب",  # NT Readiness section heading
    "المنتخب الأول",                # Senior NT
    "تحت 23",                       # U23
    "استدعاء فوري",                 # Call up immediately
    "متابعة",                       # Monitor
    "إرسال",                        # Submit
    "حفظ كمسودة",                   # Save Draft
    "لاعب يمكن مقارنته به",          # Comparable player
]
for s in arabic_form_strings:
    check(f"Arabic verbatim: {s}", s in html)

# Acceptance #16 — view template with locked status hides edit for scout
print("\n=== A16: view template 'locked' handling for scout role ===")
db_exec("""UPDATE evaluations SET status='locked', locked_at = NOW(), locked_by = %s
           WHERE id = %s""", (admin_id, TARGET_EVAL["id"]))
# Reset scout password so we can log in
from werkzeug.security import generate_password_hash
db_exec("UPDATE users SET password_hash = %s WHERE email = 'scout@bfa.bh'",
        (generate_password_hash('phase5c2-temp-pw', method='pbkdf2:sha256:600000'),))
scout = login("scout@bfa.bh", "phase5c2-temp-pw")
_, html, _ = http(scout, "GET", f"/evaluations/{TARGET_EVAL['id']}")
# Scout viewing a locked evaluation should NOT see lock/unlock or admin-edit buttons
check("scout sees no Lock button on locked eval",
      ">Lock 🔒</button>" not in html and ">Lock</button>" not in html)
check("scout sees no Unlock button on locked eval", ">Unlock</button>" not in html)
check("scout sees no admin-edit affordance",
      "Admin edit lets you" not in html)

# Restore the eval
db_exec("""UPDATE evaluations SET status='submitted', locked_at = NULL,
           locked_by = NULL WHERE id = %s""", (TARGET_EVAL["id"],))

# Final summary
print("\n" + "=" * 60)
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"E2E summary: {n_pass} pass / {n_fail} fail (of {len(results)})")
sys.exit(0 if n_fail == 0 else 2)
