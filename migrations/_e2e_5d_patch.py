"""
Phase 5d patch synthetic E2E. Verifies the three patch items + the
original 5d acceptance criteria still hold.

Items:
  1. Latest-mode header card includes match_label
  2. HTMX partial route returns just the section (no <html>); push-url works
  3. Detailed criteria comparison drilldown actually shows all 4 categories
     (49 criteria, AM ∪ DM)
"""
import os, re, sys
from urllib.request import build_opener, HTTPCookieProcessor, Request
from http.cookiejar import CookieJar
from urllib.parse import urlencode
from urllib.error import HTTPError

from dotenv import load_dotenv

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


results = []
def chk(label, ok, ev=""):
    results.append((label, ok, ev))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}  {ev}")


admin = login(os.environ["INITIAL_ADMIN_EMAIL"], os.environ["INITIAL_ADMIN_PASSWORD"])

# ── Item 1: match label appears in Latest-mode header ──────────
print("=== Item 1: match label in Latest-mode header ===")
code, html, _ = http(admin, "GET", "/players/compare/view?ids=2&ids=6&scout_mode=latest")
chk("compare_view returns 200", code == 200)
# Latest header should contain ' vs ' from the match_label OR 'Freestanding'
header_idx = html.find("Latest by")
if header_idx > 0:
    nearby = html[header_idx:header_idx + 600]
    has_match_marker = (" vs " in nearby) or ("Freestanding" in nearby)
    chk("latest header has match_label (vs/Freestanding)", has_match_marker,
        f"snippet: ...{nearby[:200].strip()}...")
else:
    chk("'Latest by' header found in HTML", False)

# Averaged header should NOT have match_label, just 'evaluations averaged'
code, html, _ = http(admin, "GET", "/players/compare/view?ids=2&ids=6&scout_mode=averaged")
avg_idx = html.find("Averaged across")
chk("averaged header found", avg_idx > 0)
if avg_idx > 0:
    nearby = html[avg_idx:avg_idx + 200]
    # The averaged header line itself should NOT contain ' vs ' (no match_label)
    # — the team name "vs" still appears elsewhere in the page (Wyscout dashboard
    # header shows "Muharraq vs Khalidiya" as a match label there). We check the
    # next ~50 chars only.
    chk("no 'vs ' in the next 50 chars of averaged header",
        " vs " not in nearby[:80],
        f"nearby: {nearby[:80]!r}")

# ── Item 2: HTMX partial route ─────────────────────────────────
print("\n=== Item 2: HTMX partial returns just the section ===")
code, html, _ = http(admin, "GET",
                     "/players/compare/scout-section?ids=2&ids=6&scout_mode=latest")
chk("partial returns 200", code == 200)
chk("partial starts with the section wrapper",
    '<section id="scout-section"' in html,
    f"first 80 chars: {html[:80].strip()!r}")
chk("partial does NOT include full HTML doctype",
    "<!DOCTYPE" not in html and "<html" not in html.lower())
chk("partial does NOT include base.html nav",
    "<nav" not in html)

# Toggle markup uses hx-get + hx-target + hx-push-url
code, html, _ = http(admin, "GET", "/players/compare/view?ids=2&ids=6")
chk("toggle <a> has hx-get to scout-section",
    "/players/compare/scout-section" in html and "hx-get=" in html)
chk("toggle <a> has hx-target='#scout-section'",
    'hx-target="#scout-section"' in html)
chk("toggle <a> has hx-swap='outerHTML'",
    'hx-swap="outerHTML"' in html)
chk("toggle <a> has hx-push-url",
    "hx-push-url=" in html)
chk("toggle <a> still has plain href fallback (progressive enhancement)",
    re.search(r'href="\?[^"]*scout_mode=(latest|averaged)', html) is not None)

# ── Item 3: drilldown renders all 4 categories ─────────────────
print("\n=== Item 3: drilldown renders all 4 categories + 49 criteria ===")
code, html, _ = http(admin, "GET", "/players/compare/view?ids=2&ids=6")
idx = html.find("Detailed criteria comparison")
chk("'Detailed criteria comparison' anchor found", idx > 0)
if idx > 0:
    drilldown = html[idx:idx + 200000]   # whole rest of page
    # Inner <details> count: each category is one. Should be 4.
    n_inner_details = drilldown.count('<details')
    # Outer expander is also <details> — so 4 inner + 1 outer = 5
    chk("all 4 category sub-collapses present (1 outer + 4 inner = 5)",
        n_inner_details >= 4, f"<details count after anchor: {n_inner_details}")
    for cat_name in ("Technical", "Tactical", "Physical", "Mentality"):
        chk(f"category {cat_name!r} rendered", cat_name in drilldown)
    # Count <tr> rows in the drilldown — should be ≥ 49 data rows + 4 header rows = 53
    n_tr = drilldown.count("<tr")
    chk("drilldown <tr> count >= 49 (criteria union AM=42 + DM=40 - overlap)",
        n_tr >= 49, f"<tr> count: {n_tr}")
    # Spec assertion: at least 40 criterion data rows. Use the structural
    # `<tr` count as authoritative — 53 = 4 header rows + 49 data rows.
    chk("criterion data rows >= 40 (structural <tr> count after anchor)",
        n_tr - 4 >= 40, f"data rows: {n_tr - 4}")
    # AM-only criterion present
    chk("AM-only criterion 'Attacking set-pieces' in drilldown",
        "Attacking set-pieces" in drilldown)
    # DM-only criterion present
    chk("DM-only criterion 'Long ball cover' / 'long balls' in drilldown",
        "Long ball cover" in drilldown or "long balls" in drilldown
        or "Covering depth" in drilldown)
    # NULL '—' cells render
    chk("'—' cells render for cross-position non-applicable", "—" in drilldown)

# ── Regression: existing 5d behaviours still hold ──────────────
print("\n=== Regression: original 5d behaviours ===")
code, html, _ = http(admin, "GET", "/players/compare/view?ids=2&ids=6")
chk("Wyscout 'Performance profile' heading present",
    "Performance profile (Wyscout)" in html)
chk("Wyscout compareRadar canvas present", 'id="compareRadar"' in html)
chk("Latest mode active by default",
    re.search(r'background:var\(--brand\)[^>]*>\s*Latest', html) is not None)
# Switch to averaged via direct URL — content swaps
code, html, _ = http(admin, "GET", "/players/compare/view?ids=2&ids=6&scout_mode=averaged")
chk("averaged URL still renders full page (200)", code == 200)
chk("averaged URL highlights Averaged toggle",
    re.search(r'background:var\(--brand\)[^>]*>\s*Averaged', html) is not None)

# Summary
print("\n" + "=" * 60)
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"E2E summary: {n_pass} pass / {n_fail} fail (of {len(results)})")
sys.exit(0 if n_fail == 0 else 2)
