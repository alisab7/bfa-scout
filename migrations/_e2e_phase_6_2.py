"""
Phase 6.2 synthetic E2E. Asserts the layout fix on top of 6.1.

Coverage:
  Item 1 — decorative wave removed:
    - No `wavy` text-decoration anywhere in CSS or HTML output
    - No `<hr>` element in the rendered HTML
    - No `border-bottom` on h3 in the served CSS (the fragile 1pt rule
      that rendered as wavy/dithered in Edge/Chrome PDF viewers)
    - The h3 elements in the template have no `border` rule applied

  Item 2 — side-by-side stats + radar layout on page 1:
    - .wyscout-grid uses `display: flex` (not block)
    - The h3 heading and stats-subtitle appear in DOM order BEFORE
      the .wyscout-grid div (i.e. span full width, not inside the
      flex row)
    - .stats-table is `flex: 0 0 55%` (55% column)
    - .radar is `flex: 0 0 45%` (45% column)
    - .wyscout-grid has `page-break-inside: avoid`

  Visual page-count contract:
    - Page count is EXACTLY 2 (not 3)
    - Page 1 contains the Wyscout header + subtitle + stats fields +
      at least one radar axis label (proves radar sits on page 1)
    - Page 2 contains scout assessment

Per hard rule: real Flask + real HTTP. No flask.test_client.
"""
import os
import re
import sys
import pathlib
from io import BytesIO
from urllib.request import build_opener, HTTPCookieProcessor, Request
from http.cookiejar import CookieJar
from urllib.parse import urlencode

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

load_dotenv()
BASE = "http://127.0.0.1:5057"


def http(op, method, path, *, data=None, raw=False):
    body = urlencode(data).encode() if data is not None else None
    req = Request(BASE + path, data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    r = op.open(req)
    content = r.read()
    if not raw:
        content = content.decode('utf-8', errors='replace')
    return r.status, content, r.url, dict(r.headers)


def login(email, pw):
    op = build_opener(HTTPCookieProcessor(CookieJar()))
    _, html, _, _ = http(op, "GET", "/auth/login")
    m = re.search(r'name=["\']csrf_token["\']\s+value=["\']([^"\']+)["\']', html)
    http(op, "POST", "/auth/login",
         data={"email": email, "password": pw, "csrf_token": m.group(1)})
    return op


def db():
    return psycopg2.connect(os.environ["DATABASE_URL"],
                            cursor_factory=psycopg2.extras.RealDictCursor)


def extract_pdf_text(pdf_bytes):
    from pypdf import PdfReader
    r = PdfReader(BytesIO(pdf_bytes))
    return [(p.extract_text() or "") for p in r.pages]


results = []
def chk(label, ok, ev=""):
    results.append((label, ok, ev))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}  {ev}")


# ── Fixtures ─────────────────────────────────────────────────────
admin = login(os.environ["INITIAL_ADMIN_EMAIL"], os.environ["INITIAL_ADMIN_PASSWORD"])

with db() as conn, conn.cursor() as cur:
    cur.execute(
        "SELECT id, full_name FROM players WHERE is_active=TRUE "
        "AND full_name ILIKE 'Arthur%' LIMIT 1"
    )
    arthur = cur.fetchone()
    cur.execute(
        "SELECT id, full_name FROM players WHERE is_active=TRUE "
        "AND (full_name ILIKE 'Saifaldeen%' OR full_name ILIKE '%Bouhra%') LIMIT 1"
    )
    bouhra = cur.fetchone()


# ── Generate Arthur's PDF ────────────────────────────────────────
print("=== Generate Arthur's PDF ===")
_, pdf_arthur, _, _ = http(admin, "GET",
    f"/players/{arthur['id']}/passport.pdf", raw=True)
pages_arthur = extract_pdf_text(pdf_arthur)
print(f"  Arthur: {len(pdf_arthur)} bytes, {len(pages_arthur)} pages")
chk("Arthur PDF is exactly 2 pages (no overflow to page 3)",
    len(pages_arthur) == 2, f"got {len(pages_arthur)}")


# ── Item 1: decorative wave removed ──────────────────────────────
print("\n=== Item 1: decorative wave / h3 underline gone ===")
# The passport CSS is loaded by WeasyPrint at PDF-render time, not
# served via Flask — read it directly from the filesystem.
css_path = pathlib.Path("D:/BFA-Scout/app/templates/passport/_passport.css")
css = css_path.read_text(encoding='utf-8')

# Find the h3 rule block.
m = re.search(r'(?m)^h3\s*\{[^}]+\}', css, re.DOTALL)
chk("h3 rule found in passport CSS", m is not None)
if m:
    # Strip CSS comments (/* ... */) from the rule block before
    # checking for property syntax — our removal-explanation comment
    # quotes `border-bottom:` inside backticks and would otherwise
    # false-positive the assertion.
    h3_block_raw = m.group(0)
    h3_block = re.sub(r'/\*.*?\*/', '', h3_block_raw, flags=re.DOTALL)
    chk("h3 rule has NO border-bottom: property (the wave-prone 1pt rule)",
        not re.search(r'border-bottom\s*:', h3_block),
        f"non-comment h3 body: {h3_block!r}" if re.search(r'border-bottom\s*:', h3_block) else "")
    chk("h3 rule has NO border: property (general)",
        not re.search(r'\bborder\s*:', h3_block))

# Sanity: no `wavy` text-decoration anywhere in passport assets.
# The word 'wavy' may legitimately appear in CHANGELOG-style comments;
# match it as a CSS value (text-decoration-{,style}: ... wavy).
template_path = pathlib.Path("D:/BFA-Scout/app/templates/passport/passport.html")
template_html = template_path.read_text(encoding='utf-8')
def has_wavy_decoration(text):
    return re.search(
        r'text-decoration(?:-style)?\s*:\s*[^;\}]*\bwavy\b',
        text, re.IGNORECASE
    ) is not None
chk("no `text-decoration: wavy` rule in passport CSS",
    not has_wavy_decoration(css))
chk("no `text-decoration: wavy` style in passport HTML",
    not has_wavy_decoration(template_html))
chk("no <hr> element in passport.html",
    '<hr' not in template_html.lower())

# Header's 2pt red rule should be KEPT (it's robust at 2pt).
chk(".passport-header still has 2pt red border-bottom (robust landmark)",
    re.search(r'\.passport-header\s*\{[^}]*border-bottom:\s*2pt\s+solid\s+#C8102E',
              css, re.DOTALL) is not None)


# ── Item 2: side-by-side layout ─────────────────────────────────
print("\n=== Item 2: side-by-side stats + radar ===")
# CSS structure checks.
wg = re.search(r'\.wyscout-grid\s*\{([^}]+)\}', css, re.DOTALL)
chk(".wyscout-grid rule found", wg is not None)
if wg:
    body = wg.group(1)
    chk(".wyscout-grid uses display: flex",
        re.search(r'display:\s*flex\b', body) is not None,
        f"body: {body!r}" if 'display:' not in body else "")
    chk(".wyscout-grid has page-break-inside: avoid (keeps stats+radar together)",
        'page-break-inside: avoid' in body or 'break-inside: avoid' in body)

# Stats column at 55%, radar at 45%.
st = re.search(r'\.stats-table\s*\{([^}]+)\}', css, re.DOTALL)
rd = re.search(r'\.radar\s*\{([^}]+)\}', css, re.DOTALL)
chk(".stats-table uses flex-basis 55%",
    bool(st and re.search(r'flex:\s*0\s+0\s+55%', st.group(1))),
    f"stats-table body: {st.group(1)!r}" if st else "")
chk(".radar uses flex-basis 45%",
    bool(rd and re.search(r'flex:\s*0\s+0\s+45%', rd.group(1))))

# Template structure: h3 + subtitle outside .wyscout-grid (full-width).
tmpl = template_path.read_text(encoding='utf-8')
# The h3 should appear before <div class="wyscout-grid">.
idx_h3       = tmpl.find('<h3>Wyscout Career Statistics</h3>')
idx_subtitle = tmpl.find('class="stats-subtitle"')
idx_grid     = tmpl.find('class="wyscout-grid"')
chk("h3 'Wyscout Career Statistics' appears before .wyscout-grid in template",
    0 <= idx_h3 < idx_grid,
    f"h3@{idx_h3}, grid@{idx_grid}")
chk("stats-subtitle appears before .wyscout-grid (full-width)",
    0 <= idx_subtitle < idx_grid,
    f"subtitle@{idx_subtitle}, grid@{idx_grid}")


# ── Page-content contract ───────────────────────────────────────
print("\n=== Page-content contract ===")
p1, p2 = pages_arthur
chk("page 1 contains 'Wyscout Career Statistics'",
    'Wyscout Career Statistics' in p1)
chk("page 1 contains '2025-26 season' (subtitle)",
    '2025-26 season' in p1)
chk("page 1 contains stat fields (e.g. 'Matches', 'Pass %')",
    'Matches' in p1 and 'Pass %' in p1)
# At least one radar axis label must be on page 1 (proves the radar
# sits on page 1, not banished to its own).
radar_axes_on_p1 = sum(
    1 for axis in ('Scoring', 'Passing', 'Dribbling', 'Defending', 'Aerial', 'Work Rate')
    if axis in p1
)
chk("page 1 contains all 6 radar axis labels (radar IS on page 1)",
    radar_axes_on_p1 == 6,
    f"axes on p1: {radar_axes_on_p1}/6")

chk("page 2 contains 'Scout Assessment'",
    'Scout Assessment' in p2 or 'No scout evaluations' in p2)
# Radar axes should NOT also appear on page 2 (radar shouldn't be there).
radar_axes_on_p2 = sum(
    1 for axis in ('Scoring', 'Passing', 'Dribbling', 'Defending', 'Aerial', 'Work Rate')
    if axis in p2
)
chk("page 2 does NOT contain the radar axes (radar belongs on page 1)",
    radar_axes_on_p2 == 0,
    f"axes leaked to p2: {radar_axes_on_p2}")


# ── Bouhra (different player, different stats) ──────────────────
print("\n=== Bouhra PDF (different data, same layout contract) ===")
if bouhra:
    _, pdf_bouhra, _, _ = http(admin, "GET",
        f"/players/{bouhra['id']}/passport.pdf", raw=True)
    pages_b = extract_pdf_text(pdf_bouhra)
    chk("Bouhra PDF is exactly 2 pages",
        len(pages_b) == 2, f"got {len(pages_b)}")
    if len(pages_b) == 2:
        p1b = pages_b[0]
        chk("Bouhra page 1 has Wyscout heading",
            'Wyscout Career Statistics' in p1b)
        chk("Bouhra page 1 has all 6 radar axes",
            sum(1 for a in ('Scoring','Passing','Dribbling','Defending','Aerial','Work Rate')
                if a in p1b) == 6,
            f"axes seen: {[a for a in ('Scoring','Passing','Dribbling','Defending','Aerial','Work Rate') if a in p1b]}")


# ── Public mode ──────────────────────────────────────────────────
print("\n=== Public mode ===")
_, pdf_pub, _, _ = http(admin, "GET",
    f"/players/{arthur['id']}/passport.pdf?public=1", raw=True)
pages_pub = extract_pdf_text(pdf_pub)
chk("public-mode PDF is exactly 2 pages",
    len(pages_pub) == 2, f"got {len(pages_pub)}")
chk("public-mode page 1 still has all 6 radar axes",
    sum(1 for a in ('Scoring','Passing','Dribbling','Defending','Aerial','Work Rate')
        if a in pages_pub[0]) == 6 if len(pages_pub) >= 1 else False)


# ── Save artefacts for visual review (best-effort) ──────────────
print("\n=== Saving 6.2 artefacts (best-effort) ===")
out_dir = pathlib.Path('/tmp')
for name, blob in [('passport_6_2_arthur.pdf',         pdf_arthur),
                   ('passport_6_2_arthur_public.pdf',  pdf_pub),
                   ('passport_6_2_bouhra.pdf',         pdf_bouhra if bouhra else b'')]:
    if not blob:
        continue
    try:
        (out_dir / name).write_bytes(blob)
        print(f"  saved: {name} ({len(blob)} bytes)")
    except OSError as e:
        print(f"  (skip {name}: {e})")


# ── Summary ─────────────────────────────────────────────────────
print("\n" + "=" * 60)
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"E2E summary: {n_pass} pass / {n_fail} fail (of {len(results)})")
sys.exit(0 if n_fail == 0 else 2)
