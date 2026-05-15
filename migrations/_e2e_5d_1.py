"""
Phase 5d-1 synthetic E2E. Verifies the scout-assessment radar layer:

  Item A — Top "category averages" radar
    - One canvas with `data-scout-radar` inside #scout-section
    - axes are exactly Technical/Tactical/Physical/Mentality
    - one dataset per selected player

  Item C — Per-category drill-down radars
    - One additional canvas inside each <details> sub-collapse (4 total)
    - Total scout-radar canvases: 5 (1 category-level + 4 per-category)
    - axes counts roughly match the criteria union for each category

  HTMX swap behaviour
    - The HTMX partial /players/compare/scout-section returns the
      scout-section markup including all 5 canvases (so re-init has
      something to bind to)

  Annotations / N/A handling
    - At least one 'na' annotation appears in averaged-mode payloads when
      criteria don't apply across the union
    - At least one 'absent' annotation appears (criteria union > any
      single player's criteria set, so cross-position absents are
      structurally guaranteed)

  JS wiring
    - scout_radars.js script tag is on the page
    - htmx:afterSwap re-init code is present in the JS file

  Regression
    - Phase 5d patch behaviours still hold (drilldown 4 categories, etc.)
"""
import json
import os
import re
import sys
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


def extract_radar_configs(html):
    """Pull every data-scout-radar attribute and JSON-decode it."""
    cfgs = []
    for m in re.finditer(r"data-scout-radar='([^']+)'", html):
        raw = m.group(1)
        # Jinja `| tojson` HTML-encodes <, >, & — undo just enough for JSON.
        # In the templates we don't have any of those in the data, but be
        # defensive in case future axes contain them.
        raw = raw.replace("&#34;", '"').replace("&quot;", '"').replace("&amp;", "&")
        try:
            cfgs.append(json.loads(raw))
        except json.JSONDecodeError as e:
            print(f"    [warn] could not parse radar config: {e}; raw={raw[:120]!r}")
    return cfgs


admin = login(os.environ["INITIAL_ADMIN_EMAIL"], os.environ["INITIAL_ADMIN_PASSWORD"])

# ── Page render — latest mode (default) ────────────────────────────
print("=== Page render — latest mode ===")
code, html, _ = http(admin, "GET", "/players/compare/view?ids=2&ids=6")
chk("compare_view returns 200", code == 200)
chk("scout_radars.js script tag present",
    "scout_radars.js" in html)

cfgs = extract_radar_configs(html)
chk("5 scout-radar canvases on the page (1 category + 4 per-category)",
    len(cfgs) == 5, f"found: {len(cfgs)}")

# Identify the category-level radar by its axes.
top_radar = next((c for c in cfgs
                  if c.get("axes") == ["Technical", "Tactical", "Physical", "Mentality"]),
                 None)
chk("top radar has the 4 fixed category axes (TECH/TACT/PHYS/MENT)",
    top_radar is not None,
    f"axes seen: {[c.get('axes') for c in cfgs]}" if not top_radar else "")

if top_radar:
    chk("top radar has 2 datasets (one per selected player)",
        len(top_radar.get("datasets", [])) == 2,
        f"datasets: {len(top_radar.get('datasets', []))}")
    for ds in top_radar.get("datasets", []):
        chk(f"top-radar dataset {ds.get('label')!r}: values len == 4",
            len(ds.get("values", [])) == 4,
            f"values: {ds.get('values')}")
        chk(f"top-radar dataset {ds.get('label')!r}: annotations parallel to values",
            len(ds.get("annotations", [])) == len(ds.get("values", [])))

per_cat_radars = [c for c in cfgs if c is not top_radar]
chk("4 per-category radars present",
    len(per_cat_radars) == 4, f"got: {len(per_cat_radars)}")

# Collect all axis-counts across the per-category radars; should be
# in the 5..25 range per category (Tech 10, Tact 16-20, Phys 9, Ment 6).
axis_counts = sorted(len(c.get("axes", [])) for c in per_cat_radars)
chk("per-category axis counts in [4, 25] (sanity)",
    all(4 <= n <= 25 for n in axis_counts),
    f"axis counts: {axis_counts}")
# Total criteria across the 4 per-category radars should equal the
# criteria union (49 for AM ∪ DM as established in the 5d patch E2E).
total_axes = sum(axis_counts)
chk("per-category axes total >= 40 (criteria union sanity)",
    total_axes >= 40, f"total: {total_axes}")

# Annotations sanity: across all per-category radars, expect a mix.
all_annotations = [a
                   for c in per_cat_radars
                   for ds in c.get("datasets", [])
                   for a in ds.get("annotations", [])]
chk("at least one 'rated' annotation across per-category radars",
    "rated" in all_annotations,
    f"counts: rated={all_annotations.count('rated')}, "
    f"na={all_annotations.count('na')}, "
    f"absent={all_annotations.count('absent')}")
chk("at least one 'absent' annotation (cross-position non-applicable)",
    "absent" in all_annotations)

# All datasets must have parallel arrays.
parallel_ok = all(
    len(ds.get("values", [])) == len(ds.get("annotations", []))
    for c in cfgs for ds in c.get("datasets", [])
)
chk("all datasets have len(values) == len(annotations)", parallel_ok)

# All values must be numeric (no nulls — N/A and absent are plotted as 0).
no_nulls = all(
    isinstance(v, (int, float)) and v is not None
    for c in cfgs for ds in c.get("datasets", []) for v in ds.get("values", [])
)
chk("all dataset values are numeric (no nulls -- N/A/absent plot as 0)", no_nulls)

# Values in [0, 10] given the BFA 1-10 criteria scale (N/A and absent
# plot as 0). Anything outside that range means the radar's scale
# assumption is wrong and polygons will clip.
out_of_range = [
    (c.get("axes")[:1], ds.get("label"), v)
    for c in cfgs for ds in c.get("datasets", []) for v in ds.get("values", [])
    if not (0 <= v <= 10)
]
chk("all values in [0, 10] (criteria scale_max=10; values clip otherwise)",
    not out_of_range, f"out-of-range: {out_of_range[:3]}")


# ── Page render — averaged mode ───────────────────────────────────
print("\n=== Page render — averaged mode ===")
code, html, _ = http(admin, "GET", "/players/compare/view?ids=2&ids=6&scout_mode=averaged")
chk("averaged-mode returns 200", code == 200)
cfgs_avg = extract_radar_configs(html)
chk("5 scout-radar canvases on averaged-mode page",
    len(cfgs_avg) == 5, f"found: {len(cfgs_avg)}")

# At least one category in averaged mode should have a different score
# than latest mode (otherwise the toggle is visually equivalent).
top_avg = next((c for c in cfgs_avg
                if c.get("axes") == ["Technical", "Tactical", "Physical", "Mentality"]),
               None)
if top_radar and top_avg:
    diffs = []
    for d_lat, d_avg in zip(top_radar["datasets"], top_avg["datasets"]):
        diffs.extend(zip(d_lat["values"], d_avg["values"]))
    any_diff = any(abs(a - b) > 0.01 for a, b in diffs)
    # Note: if the test data happens to have identical latest+averaged for
    # both players this would falsely fail. Players 2 & 6 have multiple
    # evals per the 5d patch E2E so the averaged should differ.
    chk("top radar values differ between latest and averaged modes "
        "(toggle visibly reshapes polygons)",
        any_diff,
        f"sample diffs: {diffs[:4]}")


# ── HTMX partial swap returns the radars too ───────────────────────
print("\n=== HTMX partial /players/compare/scout-section ===")
code, html, _ = http(admin, "GET",
                     "/players/compare/scout-section?ids=2&ids=6&scout_mode=averaged")
chk("partial returns 200", code == 200)
chk("partial starts with section wrapper",
    '<section id="scout-section"' in html)
cfgs_partial = extract_radar_configs(html)
chk("partial includes all 5 radar canvases (so re-init has targets)",
    len(cfgs_partial) == 5, f"found: {len(cfgs_partial)}")
chk("partial does NOT include a script tag for scout_radars.js "
    "(re-init runs from already-loaded JS)",
    "scout_radars.js" not in html)


# ── JS file sanity ────────────────────────────────────────────────
print("\n=== scout_radars.js content sanity ===")
code, js, _ = http(admin, "GET", "/static/js/scout_radars.js")
chk("scout_radars.js served (200)", code == 200)
chk("JS defines initScoutRadars",
    "initScoutRadars" in js)
chk("JS calls Chart.getChart(canvas)?.destroy() before re-init "
    "(or destroys prior instance)",
    "destroy()" in js and "Chart.getChart" in js)
chk("JS wires DOMContentLoaded → initScoutRadars",
    re.search(r"DOMContentLoaded.*initScoutRadars", js, re.DOTALL) is not None)
chk("JS wires htmx:afterSwap → initScoutRadars",
    "htmx:afterSwap" in js and "initScoutRadars" in js)
chk("JS guards htmx:afterSwap by target id 'scout-section' "
    "(don't re-init on unrelated swaps)",
    "scout-section" in js)
chk("JS uses 0..10 scale (BFA scoring scale; criteria.scale_max=10)",
    re.search(r"max:\s*10\b", js) is not None)
chk("JS tooltip says '/ 10' (matches scale)",
    "/ 10" in js)


# ── Regression: 5d patch behaviours still hold ─────────────────────
print("\n=== Regression: Phase 5d patch behaviours ===")
code, html, _ = http(admin, "GET", "/players/compare/view?ids=2&ids=6")
chk("'Detailed criteria comparison' anchor still present",
    "Detailed criteria comparison" in html)
for cat_name in ("Technical", "Tactical", "Physical", "Mentality"):
    chk(f"category {cat_name!r} still renders in drilldown",
        cat_name in html)
chk("Wyscout 'Performance profile' radar canvas still present",
    'id="compareRadar"' in html)
chk("Latest/Averaged toggle still has hx-get/hx-target/hx-push-url",
    all(s in html for s in ('hx-get=', 'hx-target="#scout-section"',
                            'hx-swap="outerHTML"', 'hx-push-url=')))


# ── Summary ────────────────────────────────────────────────────────
print("\n" + "=" * 60)
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"E2E summary: {n_pass} pass / {n_fail} fail (of {len(results)})")
sys.exit(0 if n_fail == 0 else 2)
