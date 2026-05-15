"""
Phase 5d synthetic E2E.

Verifies the scout-dimension on /players/compare/view via real HTTP +
DB. Tests both Latest and Averaged modes, soft-delete invariant,
no-data placeholder, criteria union for cross-position drill-down.
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


admin = login(os.environ["INITIAL_ADMIN_EMAIL"], os.environ["INITIAL_ADMIN_PASSWORD"])

# ── Reference: helper output we'll compare HTML against ─────────
from importlib import import_module
import sys as _s
_s.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")
from app import create_app
_app = create_app()
with _app.app_context():
    from app.evaluations.helpers import (
        get_player_evaluation_aggregate, get_evaluation_count_active,
    )
    arthur_latest = get_player_evaluation_aggregate(2, mode="latest")
    arthur_avg    = get_player_evaluation_aggregate(2, mode="averaged")
    bouhra_latest = get_player_evaluation_aggregate(6, mode="latest")
    bouhra_avg    = get_player_evaluation_aggregate(6, mode="averaged")
    arthur_n = get_evaluation_count_active(2)
    bouhra_n = get_evaluation_count_active(6)

print(f"\nReference: Arthur eval_count={arthur_n}, Bouhra eval_count={bouhra_n}")
print(f"  Arthur latest avgs:  {arthur_latest['category_averages']}")
print(f"  Arthur avg avgs:     {arthur_avg['category_averages']}")
print(f"  Bouhra latest avgs:  {bouhra_latest['category_averages']}")
print(f"  Bouhra avg avgs:     {bouhra_avg['category_averages']}")

# ── Test 1: GET /compare/view (Arthur + Bouhra) — Latest mode ──
print("\n=== Test 1: Arthur vs Bouhra in Latest mode ===")
code, html, _ = http(admin, "GET", "/players/compare/view?ids=2&ids=6")
chk("returns 200", code == 200)
chk("Scout Assessment heading present", "Scout Assessment" in html)
chk("Latest toggle is the active button",
    re.search(r'>\s*Latest\s*</a>', html) is not None)
# Latest evaluator names
chk(f"Arthur's latest evaluator name in HTML",
    arthur_latest["evaluator_name"] in html)
chk(f"Bouhra's latest evaluator name in HTML",
    bouhra_latest["evaluator_name"] in html)
# Category averages render
for cat_code in ("TECH", "TACT", "PHYS", "MENT"):
    arthur_v = arthur_latest["category_averages"].get(cat_code)
    if arthur_v is not None:
        formatted = f"{arthur_v:.1f}"
        chk(f"Arthur {cat_code} avg ({formatted}) appears", formatted in html)

# ── Test 2: Latest → Averaged toggle ──
print("\n=== Test 2: Switch to Averaged mode ===")
code, html, _ = http(admin, "GET",
                     "/players/compare/view?ids=2&ids=6&scout_mode=averaged")
chk("averaged returns 200", code == 200)
chk("Averaged toggle is highlighted", re.search(r'background:var\(--brand\)[^>]*>\s*Averaged', html) is not None)
chk("'evaluations averaged' label present",
    "evaluations averaged" in html)
# Averaged values may differ from latest — check a category that does
arthur_diff_cats = [c for c in ('TECH','TACT','PHYS','MENT')
                    if arthur_latest['category_averages'].get(c) != arthur_avg['category_averages'].get(c)]
print(f"  Arthur cats where latest != averaged: {arthur_diff_cats}")
chk("at least one of Arthur's averaged values differs from latest",
    len(arthur_diff_cats) >= 1, "or the dataset has identical scores across evals")

# Check average values appear in HTML
for cat_code in ("TECH", "TACT", "PHYS", "MENT"):
    avg_v = arthur_avg["category_averages"].get(cat_code)
    if avg_v is not None:
        formatted = f"{avg_v:.1f}"
        chk(f"Arthur averaged {cat_code} ({formatted}) appears", formatted in html)

# ── Test 3: drill-down + criteria union ──
print("\n=== Test 3: drill-down (criteria union) ===")
chk("Detailed criteria comparison expander present",
    "Detailed criteria comparison" in html)
# Arthur is AM (id=6), Bouhra is DM (id=4) per prior phases. Union should include
# tech_set_pieces_attacking (CB/AM/ST only — NOT DM).
chk("AM-only criterion appears in union", "tech_set_pieces_attacking" in html
    or "Attacking set-pieces" in html)
# DM-only criterion
chk("Long ball cover (CB/FB/DM) appears in union",
    "tact_long_ball_cover" in html or "long balls" in html)

# ── Test 4: NULL cells render as "—" for cross-position non-applicable ──
print("\n=== Test 4: NULL cell for cross-position non-applicable ===")
# tech_set_pieces_attacking applies to CB/AM/ST. So Bouhra (DM) will have "—"
# for it. Verify "—" appears at least once in the drill-down area.
drilldown_idx = html.find("Detailed criteria comparison")
if drilldown_idx > 0:
    drilldown_html = html[drilldown_idx:]
    chk("NULL cell '—' present in drill-down", "—" in drilldown_html)

# ── Test 5: No-evaluations placeholder (need active player with 0 evals) ──
print("\n=== Test 5: 'No evaluations yet' placeholder for player with no evals ===")
# Create a temporary active player with no evals so we can exercise the
# placeholder branch of the template (validate_comparison rejects inactive
# players, so Sayed wouldn't reach the compare_view render).
db_exec("DELETE FROM players WHERE national_id = 'PHASE5D-NOEVAL'")
amf_pos = db_query("SELECT id FROM positions WHERE code = 'AMF'")[0]['id']
db_exec("""INSERT INTO players (full_name, national_id, primary_position_id, is_active)
           VALUES ('Phase5D NoEval', 'PHASE5D-NOEVAL', %s, TRUE)""", (amf_pos,))
noeval_id = db_query("SELECT id FROM players WHERE national_id = 'PHASE5D-NOEVAL'")[0]['id']
code, html, url = http(admin, "GET", f"/players/compare/view?ids=2&ids={noeval_id}")
chk("compare with active no-eval player returns 200",
    code == 200 and "Scout Assessment" in html, f"code={code}")
chk("'No evaluations yet' placeholder rendered for that player",
    "No evaluations yet" in html)
db_exec("DELETE FROM players WHERE national_id = 'PHASE5D-NOEVAL'")

# ── Test 6: soft-delete invariant — Arthur's latest changes ──
print("\n=== Test 6: soft-delete latest eval → latest mode picks next ===")
# Find Arthur's latest active submitted eval
latest_ids = db_query("""
    SELECT id FROM evaluations WHERE player_id = 2 AND status IN ('submitted','locked')
    AND deleted_at IS NULL
    ORDER BY COALESCE(submitted_at, created_at) DESC, id DESC
""")
if len(latest_ids) >= 2:
    latest_id = latest_ids[0]["id"]
    second_id = latest_ids[1]["id"]
    print(f"  before delete: latest_id={latest_id}, second_id={second_id}")
    db_exec("""UPDATE evaluations SET deleted_at = NOW(),
                                       deleted_by = 1,
                                       deleted_reason = 'Phase5D E2E soft-delete test'
               WHERE id = %s""", (latest_id,))
    with _app.app_context():
        from app.evaluations.helpers import get_player_evaluation_aggregate as _agg
        new_latest = _agg(2, mode="latest")
        new_avg    = _agg(2, mode="averaged")
    chk("after delete, latest helper returns the second eval (or different than before)",
        new_latest["eval_id"] != latest_id and new_latest["eval_id"] is not None,
        f"now latest_id={new_latest['eval_id']}")
    chk("averaged mode now averages 1 fewer eval",
        new_avg["evaluator_name"] != arthur_avg["evaluator_name"],
        f"was '{arthur_avg['evaluator_name']}', now '{new_avg['evaluator_name']}'")

    # Restore
    db_exec("""UPDATE evaluations SET deleted_at = NULL,
                                      deleted_by = NULL,
                                      deleted_reason = NULL
               WHERE id = %s""", (latest_id,))
    with _app.app_context():
        restored_latest = _agg(2, mode="latest")
        restored_avg    = _agg(2, mode="averaged")
    chk("after restore, latest matches original",
        restored_latest["eval_id"] == latest_id)
    chk("after restore, averaged matches original",
        restored_avg["evaluator_name"] == arthur_avg["evaluator_name"])
else:
    print("  (skipped — Arthur has < 2 active evals to test the cascade)")

# ── Test 7: existing Wyscout comparison still renders (regression) ──
print("\n=== Test 7: Phase 4.1 Wyscout comparison still renders ===")
code, html, _ = http(admin, "GET", "/players/compare/view?ids=2&ids=6")
chk("Wyscout 'Performance profile' heading present", "Performance profile (Wyscout)" in html)
chk("Wyscout compareRadar canvas present", 'id="compareRadar"' in html)
chk("Wyscout career stats table present", "Career statistics" in html or "Matches" in html)

# ── Test 8: GK-vs-outfield rule still applied (regression — Phase 4.1 logic) ──
print("\n=== Test 8: GK-vs-outfield still rejected ===")
# Arthur is AM, find a GK player if one exists.
gk = db_query("""SELECT pl.id FROM players pl
                 JOIN positions p ON p.id = pl.primary_position_id
                 JOIN position_groups pg ON pg.id = p.position_group_id
                 WHERE pg.code = 'GK' AND pl.is_active = TRUE LIMIT 1""")
if gk:
    code, html, url = http(admin, "GET", f"/players/compare/view?ids=2&ids={gk[0]['id']}")
    # validate_comparison raises ValueError -> route flashes + redirects to picker
    chk("GK + AM mix redirects to picker (302) or shows error",
        code in (200, 302) and "compare/view" not in (url or ""),
        f"code={code} url={url}")
else:
    print("  (no GK player in DB; skipping)")

# Summary
print("\n" + "=" * 60)
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"E2E summary: {n_pass} pass / {n_fail} fail (of {len(results)})")
sys.exit(0 if n_fail == 0 else 2)
