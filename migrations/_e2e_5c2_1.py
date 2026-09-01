"""
Phase 5c-2.1 synthetic E2E.

Verifies the four patch items via cookied stdlib HTTP + DB:
  1. Eligibility card moved up on profile (above Wyscout dashboard)
  2. compute_eligibility_status priority order (test players A–G)
  3. Section-grouped expanded scores in history cards
  4. Players list eligibility column + filter dropdown + SQL filter

Sets up 7 ephemeral test players for case A–G plus one seeded
evaluation (with scores) on player A, runs assertions, and removes every
fixture in a `finally:`. The suite owns all of its fixtures — it never
reads a player id out of ambient DB state.
"""
import os, re, sys
from datetime import date, timedelta
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


admin = login(os.environ["INITIAL_ADMIN_EMAIL"], os.environ["INITIAL_ADMIN_PASSWORD"])

# ── Set up 7 ephemeral test players (A–G) for the priority order matrix ──
print("\n=== Setup: 7 ephemeral test players ===")
# Pick any active position id for them (use AMF=20 — same as Arthur)
_pos_row = db_query("SELECT id, position_group_id FROM positions WHERE code = 'AMF'")[0]
POS_ID       = _pos_row["id"]
POS_GROUP_ID = _pos_row["position_group_id"]
TODAY = date.today()
FUTURE = TODAY + timedelta(days=400)   # ~1y future
PAST   = TODAY - timedelta(days=400)
RES_OLD = date(2018, 1, 1)             # 5y elapsed, suggested in past → Eligible now
RES_RECENT = TODAY - timedelta(days=int(365*3))  # ~3y ago, suggested ~2y future

CASES = [
    ("A_BAH",  "Test A Bahraini",            "TEST5C21A", {"nationality_status": "bahraini"}),
    ("B_ANC",  "Test B Foreign-ancestry",    "TEST5C21B", {"nationality_status": "foreign_ancestry"}),
    ("C_RES",  "Test C Residency-derived",   "TEST5C21C", {"nationality_status": "foreign_residency",
                                                            "bahrain_residency_start_date": RES_RECENT}),
    ("D_DATE", "Test D Explicit-date wins",  "TEST5C21D", {"nationality_status": "foreign_residency",
                                                            "eligible_from_date": FUTURE,
                                                            "bahrain_residency_start_date": RES_OLD}),
    ("E_PEND", "Test E Pending-no-start",    "TEST5C21E", {"nationality_status": "foreign_residency"}),
    ("F_NOT",  "Test F Not eligible",        "TEST5C21F", {"nationality_status": "not_eligible"}),
    ("G_UNK",  "Test G Unknown",             "TEST5C21G", {}),
]

# Clean up any stale test players from previous runs, then insert fresh (committed!).
# Use a single autocommit connection so RETURNING ids actually persist.
test_player_ids = {}
INSERTED_EVAL_IDS = []


def cleanup():
    """Remove every fixture this suite creates. Safe to call twice."""
    if INSERTED_EVAL_IDS:
        db_exec("DELETE FROM evaluation_scores WHERE evaluation_id = ANY(%s)",
                (INSERTED_EVAL_IDS,))
        db_exec("DELETE FROM evaluations WHERE id = ANY(%s)", (INSERTED_EVAL_IDS,))
    # evaluations/evaluation_scores cascade off players, but delete explicitly
    # so a partially-set-up run still leaves nothing behind.
    db_exec("DELETE FROM evaluations WHERE player_id IN "
            "(SELECT id FROM players WHERE national_id LIKE %s)", ('TEST5C21%',))
    db_exec("DELETE FROM players WHERE national_id LIKE %s", ('TEST5C21%',))


# The `try:` opens BEFORE the first mutation, so a failure during setup still
# hits the cleanup in `finally:` instead of leaking fixture rows.
try:
    _setup_conn = psycopg2.connect(DB, cursor_factory=RealDictCursor)
    _setup_conn.autocommit = True
    try:
        with _setup_conn.cursor() as _cur:
            _cur.execute("DELETE FROM players WHERE national_id LIKE 'TEST5C21%%'")
            for code, name, nat_id, extras in CASES:
                fields = ["full_name", "national_id", "primary_position_id", "is_active"]
                values = [name, nat_id, POS_ID, True]
                for k, v in extras.items():
                    fields.append(k); values.append(v)
                placeholders = ",".join(["%s"] * len(values))
                cols = ",".join(fields)
                _cur.execute(f"INSERT INTO players ({cols}) VALUES ({placeholders}) RETURNING id",
                             tuple(values))
                test_player_ids[code] = _cur.fetchone()["id"]
                print(f"  {code}: id={test_player_ids[code]} ({name})")

            # ── Profile fixture: a submitted evaluation WITH scores on A ──
            # Items 1 and 3 render a real profile page (eligibility card,
            # Wyscout dashboard, section-grouped history card). Seed that
            # evaluation here rather than pointing at whatever player happens
            # to sit at a hardcoded id.
            PROFILE_PID = test_player_ids["A_BAH"]
            _cur.execute("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1")
            _admin_user_id = _cur.fetchone()["id"]
            _cur.execute("""INSERT INTO evaluations
                              (player_id, evaluator_id, position_group_id, status,
                               created_by_role, summary, nt_readiness_level,
                               recommendation, submitted_at)
                            VALUES (%s, %s, %s, 'submitted', 'admin',
                                    'E2E 5c-2.1 fixture evaluation', 'senior',
                                    'monitor', NOW())
                            RETURNING id""",
                         (PROFILE_PID, _admin_user_id, POS_GROUP_ID))
            _eval_id = _cur.fetchone()["id"]
            INSERTED_EVAL_IDS.append(_eval_id)

            # Score a handful of the position group's criteria: three rated
            # (so the category shows an 'avg') and one N/A.
            _cur.execute("""SELECT c.id FROM position_group_criteria pgc
                            JOIN   criteria c ON c.id = pgc.criterion_id
                            WHERE  pgc.position_group_id = %s AND c.is_active
                            ORDER  BY pgc.sort_order, c.id LIMIT 4""",
                         (POS_GROUP_ID,))
            _crit_ids = [r["id"] for r in _cur.fetchall()]
            if not _crit_ids:   # fall back to any active criteria
                _cur.execute("SELECT id FROM criteria WHERE is_active ORDER BY id LIMIT 4")
                _crit_ids = [r["id"] for r in _cur.fetchall()]
            for _i, _cid in enumerate(_crit_ids):
                _na = (_i == len(_crit_ids) - 1 and len(_crit_ids) > 1)
                _cur.execute("""INSERT INTO evaluation_scores
                                  (evaluation_id, criterion_id, score, is_not_applicable)
                                VALUES (%s, %s, %s, %s)""",
                             (_eval_id, _cid, None if _na else 7 + _i, _na))
            print(f"  profile fixture: player={PROFILE_PID} eval={_eval_id} "
                  f"scores={len(_crit_ids)}")
    finally:
        _setup_conn.close()

    # Item 1 — eligibility card position on profile
    print("\n=== Item 1: eligibility card moved above Wyscout dashboard ===")
    _, html, _ = http(admin, "GET", f"/players/{PROFILE_PID}")
    elig_idx = html.find("National-Team Eligibility")
    wyscout_idx = html.find("Wyscout Statistics")
    check("eligibility card present", elig_idx > 0)
    check("Wyscout dashboard present", wyscout_idx > 0)
    check("eligibility card appears BEFORE Wyscout dashboard",
          elig_idx > 0 and wyscout_idx > 0 and elig_idx < wyscout_idx,
          f"elig@{elig_idx} vs wyscout@{wyscout_idx}")
    # Make sure there's only one eligibility card on the page (not duplicated)
    n_elig = html.count("National-Team Eligibility")
    check("eligibility card appears exactly once", n_elig == 1, f"count={n_elig}")

    # Item 2 — priority cases A–G
    print("\n=== Item 2: priority order via profile rendering ===")
    EXPECTED = {
        # Badge fix: citizens read "Citizen", NOT "Eligible now" (the latter is
        # reserved for foreign_residency players past their eligible date).
        "A_BAH":  ("✅", "Citizen",                       "Bahraini citizen"),
        "B_ANC":  ("✅", "Citizen",                       "Foreign-eligible (ancestry)"),
        "C_RES":  ("⏳", "Eligible in",                   "Article 5"),
        "D_DATE": ("⏳", "Eligible in",                   FUTURE.strftime("%Y-%m-%d")),
        "E_PEND": ("⏳", "Pending — residency start",     "set Bahrain residency"),
        "F_NOT":  ("❌", "Not eligible",                  None),
        "G_UNK":  ("?",  "Status unknown",                None),
    }
    for code, (icon_expected, label_expected, note_substring) in EXPECTED.items():
        pid = test_player_ids[code]
        _, html, _ = http(admin, "GET", f"/players/{pid}")
        has_icon  = icon_expected in html
        has_label = label_expected in html
        has_note  = (note_substring is None) or (note_substring in html)
        check(f"{code}: icon={icon_expected}, label='{label_expected}'",
              has_icon and has_label,
              f"icon={has_icon} label={has_label}")
        if note_substring:
            check(f"{code}: note contains '{note_substring}'", has_note)

    # Item 2 cleanup — confirm "Status:" line is gone, "Route:" line is present
    print("\n=== Item 2: redundant 'Status:' line removed; 'Route:' line present ===")
    _, html, _ = http(admin, "GET", f"/players/{test_player_ids['A_BAH']}")
    # Old line was 'Status:\n      <span style="color:var(--text);">' rendering
    check("no redundant 'Status:' label in eligibility card",
          "Status:\n      <span" not in html and "Status:\n        <span" not in html and ">Status:</p>" not in html)
    check("'Route:' label present for A (bahraini)", "Route:" in html)
    # Player G (no nationality_status) should NOT show a Route line
    _, html, _ = http(admin, "GET", f"/players/{test_player_ids['G_UNK']}")
    check("'Route:' line absent for G (status null)", "Route:" not in html)

    # Item 3 — section-grouped expanded scores
    print("\n=== Item 3: section-grouped expanded scores on history card ===")
    _, html, _ = http(admin, "GET", f"/players/{PROFILE_PID}")
    # The fixture player has one submitted eval. Its card should have
    # <details> blocks per category WITHIN the expanded body. Look for telltale markers.
    check("group_scores_by_category wired (any category sub-collapse rendered)",
          html.count("<details") >= 1,
          f"<details count={html.count('<details')}")
    check("'avg' label visible in section header", "avg" in html)
    check("'rated' count text visible", " rated" in html)
    # N/A counts only show for evals with N/A — the fixture eval seeds one N/A row,
    # so the conditional is exercised; no strict assertion needed.

    # Item 4 — players list eligibility column + filter
    print("\n=== Item 4: players list eligibility column + filter ===")
    _, html, _ = http(admin, "GET", "/players/")
    check("eligibility filter dropdown present",
          'name="elig"' in html and "All eligibility statuses" in html)
    check("filter has all 5 options",
          all(opt in html for opt in
              ["All eligibility", "Eligible now", "Pending", "Not eligible", "Unknown"]))
    check("test player A (bahraini) appears in the list",
          "Test A Bahraini" in html and html.find("Test A Bahraini") > 0)
    check("test player F appears with ❌ Not eligible",
          "Test F Not eligible" in html)

    # Apply each filter and check it returns a sensible subset
    for filter_value, expected_codes, not_expected in [
        # D_DATE has eligible_from_date in the FUTURE → belongs to 'pending', not 'eligible_now'
        ("eligible_now",  ["A_BAH", "B_ANC"],           ["D_DATE", "E_PEND", "F_NOT", "G_UNK"]),
        ("pending",       ["C_RES", "D_DATE", "E_PEND"], ["A_BAH", "B_ANC", "F_NOT", "G_UNK"]),
        ("not_eligible",  ["F_NOT"],                     ["A_BAH", "B_ANC", "D_DATE", "G_UNK"]),
        ("unknown",       ["G_UNK"],                     ["A_BAH", "B_ANC", "F_NOT"]),
    ]:
        _, html, _ = http(admin, "GET", f"/players/?elig={filter_value}")
        test_names_seen = {code: db_query("SELECT full_name FROM players WHERE id = %s",
                                          (test_player_ids[code],))[0]["full_name"]
                          for code in expected_codes + not_expected}
        for code in expected_codes:
            check(f"filter={filter_value} INCLUDES {code}",
                  test_names_seen[code] in html, f"player='{test_names_seen[code]}'")
        for code in not_expected:
            check(f"filter={filter_value} EXCLUDES {code}",
                  test_names_seen[code] not in html, f"player='{test_names_seen[code]}'")

finally:
    # ── Cleanup: every fixture this suite created ──
    print("\n=== Cleanup ===")
    cleanup()
    print(f"  removed {len(CASES)} ephemeral test players + "
          f"{len(INSERTED_EVAL_IDS)} seeded evaluation(s)")

# Final summary
print("\n" + "=" * 60)
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"E2E summary: {n_pass} pass / {n_fail} fail (of {len(results)})")
sys.exit(0 if n_fail == 0 else 2)
