"""
Phase 6.1 synthetic E2E. Asserts the polish-patch deltas on top of
Phase 6's behaviour. Run after `_e2e_phase_6.py` confirms the
underlying route still works (this script only checks 6.1 deltas).

Assertions:
  Item 1 (radar layout): all 6 axis labels appear unclipped in the
    extracted PDF text (full strings: 'Scoring', 'Passing', 'Dribbling',
    'Defending', 'Aerial', 'Work Rate')

  Item 2 (eligibility wording):
    - 'Eligible from' appears (foreign_residency player with date)
    - 'Bahrain residency since' appears for foreign_residency player
    - 'Article 5' and 'admin to confirm' do NOT appear in the passport
    - '1y ' (the old 'y/m' abbreviation) does NOT appear
    - Bahraini player still gets a sensible 'Eligible now' line

  Item 3 (flag SVG):
    - Inline <svg> markup with the flag-inline class makes it through
      the HTML render (checked via direct template render, not PDF
      bytes — PDFs render SVGs to paths, lossy to text inspection)
    - `_flag_svg_inline(<player nationality_code>)` returns non-None
      for known codes (BRA, MAR, BHR), None for unknown

  Item 4 (Wyscout subtitle):
    - 'season · N matches' subtitle in PDF text for Arthur
    - '2025-26' present (DB format kept; see CHANGELOG for rationale)
    - Bouhra (Moroccan, 16 matches) gets his own subtitle

  Item 5 (performance + loading indicator):
    - Profile page HTML contains `class="passport-btn"` with `onclick`
      attribute setting innerHTML to '⏳ Generating'
    - Flask log captures the timing line emitted by render_passport_pdf
    - Single PDF wall-time recorded for the CHANGELOG note

Per hard rule: real Flask + real HTTP. No flask.test_client.
"""
import os
import re
import sys
import time
from io import BytesIO
from urllib.request import build_opener, HTTPCookieProcessor, Request
from http.cookiejar import CookieJar
from urllib.parse import urlencode

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

# Make `app` importable so we can hit the data-layer helpers directly
# for assertions that PDF-text inspection can't cover (e.g. SVG markup).
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent))

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


results = []
def chk(label, ok, ev=""):
    results.append((label, ok, ev))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}  {ev}")


def extract_pdf_text(pdf_bytes):
    from pypdf import PdfReader
    return "\n".join(
        (p.extract_text() or "")
        for p in PdfReader(BytesIO(pdf_bytes)).pages
    )


# ── Fixtures ─────────────────────────────────────────────────────
admin = login(os.environ["INITIAL_ADMIN_EMAIL"], os.environ["INITIAL_ADMIN_PASSWORD"])

with db() as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT id, full_name, nationality_code, nationality_status,
               bahrain_residency_start_date, eligible_from_date
        FROM   players WHERE is_active=TRUE ORDER BY id
    """)
    players = {p['full_name'].split()[0]: p for p in cur.fetchall()}

p_arthur = players.get('Arthur')
p_bouhra = next((p for n, p in players.items() if 'Bouhra' in (p['full_name'] or '') or n == 'Saifaldeen'), None)
p_bahraini = next((p for p in players.values() if p['nationality_status'] == 'bahraini'), None)

print(f"Fixtures: Arthur={(p_arthur or {}).get('id')}, "
      f"Bouhra={(p_bouhra or {}).get('id')}, "
      f"bahraini={(p_bahraini or {}).get('id')}")


# ── Generate Arthur's full PDF once, reuse for several assertions ──
print("\n=== Generate Arthur's PDF (timing + content inspection) ===")
t0 = time.perf_counter()
_, pdf_arthur, _, _ = http(admin, "GET",
    f"/players/{p_arthur['id']}/passport.pdf", raw=True)
arthur_wall = time.perf_counter() - t0
text_arthur = extract_pdf_text(pdf_arthur)
print(f"  Arthur PDF: {len(pdf_arthur)} bytes, wall {arthur_wall:.2f}s, "
      f"text len {len(text_arthur)} chars")


# ── Item 1: radar labels unclipped ─────────────────────────────
print("\n=== Item 1: radar axis labels unclipped ===")
for axis in ('Scoring', 'Passing', 'Dribbling', 'Defending', 'Aerial', 'Work Rate'):
    chk(f"axis label {axis!r} present in PDF text",
        axis in text_arthur,
        f"found at idx {text_arthur.find(axis)}" if axis in text_arthur else "")


# ── Item 2: eligibility wording ────────────────────────────────
print("\n=== Item 2: eligibility wording ===")
chk("Arthur passport: 'Eligible from' present",
    'Eligible from' in text_arthur)
chk("Arthur passport: 'Bahrain residency since' present "
    "(foreign_residency player with start date)",
    'Bahrain residency since' in text_arthur)
chk("Arthur passport: 'Article 5' NOT present (jargon scrubbed)",
    'Article 5' not in text_arthur)
chk("Arthur passport: 'admin to confirm' NOT present",
    'admin to confirm' not in text_arthur)
chk("Arthur passport: 'Suggested ' NOT present (old wording)",
    'Suggested ' not in text_arthur)
# The old "1y 3m" style should NOT appear; humanized form (year/month words) should.
chk("Arthur passport: old 'Xy Ym' abbreviation NOT present",
    re.search(r'\b\d+y \d+m\b', text_arthur) is None)
# 'Humanized duration' (e.g. "in 5 years") only appears when the eligible
# date is in the future. If Arthur's date is in the past he sees just
# "Eligible from <date>" — equally valid. Accept either form.
has_humanized = bool(re.search(r'\d+ years?(?:,\s*\d+ months?)?', text_arthur))
has_eligible_from = bool(re.search(r'Eligible from \d{4}-\d{2}-\d{2}', text_arthur))
chk("Arthur passport: either humanized duration OR 'Eligible from <date>' alone "
    "(eligible NOW)", has_humanized or has_eligible_from,
    f"humanized={has_humanized}, eligible_from={has_eligible_from}")


# Bahraini player passport — different wording branch ('Eligible now / Bahraini citizen').
if p_bahraini:
    _, pdf_bah, _, _ = http(admin, "GET",
        f"/players/{p_bahraini['id']}/passport.pdf", raw=True)
    text_bah = extract_pdf_text(pdf_bah)
    chk("Bahraini player passport: 'Eligible now' present",
        'Eligible now' in text_bah)
    chk("Bahraini player passport: 'Bahraini citizen' present",
        'Bahraini citizen' in text_bah)
    chk("Bahraini player passport: 'Bahrain residency since' NOT present "
        "(birthright route, residency line is irrelevant)",
        'Bahrain residency since' not in text_bah)
    chk("Bahraini player passport: 'Article 5' NOT present",
        'Article 5' not in text_bah)
else:
    print("  (no bahraini player — Item 2 bahraini branch skipped)")


# ── Item 2 (deeper): the 7 cases from the spec, exercised via helper ──
print("\n=== Item 2: exercise _build_passport_eligibility for all 7 cases ===")
from datetime import date
from app.passport.data import _build_passport_eligibility, _humanize_duration

# Cross-year date math: today+5y at the same day is the future_5y date used below.
today = date.today()
five_years_ahead = date(today.year + 5, today.month, today.day) if (today.month, today.day) != (2, 29) else date(today.year + 5, 2, 28)
five_years_ago   = date(today.year - 5, today.month, today.day) if (today.month, today.day) != (2, 29) else date(today.year - 5, 2, 28)

cases = [
    # (label, player_dict, expected fragments in label, expected note prefix or None)
    ("bahraini",
     {"nationality_status": "bahraini"},
     "Eligible now", "Bahraini citizen"),
    ("foreign_ancestry",
     {"nationality_status": "foreign_ancestry"},
     "Eligible now", "Foreign-eligible (ancestry)"),
    ("foreign_residency w/ future date + residency start",
     {"nationality_status": "foreign_residency",
      "bahrain_residency_start_date": date(2022, 8, 15),
      "eligible_from_date": five_years_ahead},
     "Eligible from", "Bahrain residency since 2022-08-15"),
    ("foreign_residency w/ past date",
     {"nationality_status": "foreign_residency",
      "bahrain_residency_start_date": date(2018, 1, 1),
      "eligible_from_date": five_years_ago},
     "Eligible from", "Bahrain residency since 2018-01-01"),
    ("foreign_residency w/o start date or eligible_from",
     {"nationality_status": "foreign_residency"},
     "Pending", None),
    ("not_eligible",
     {"nationality_status": "not_eligible"},
     "Not eligible", None),
    ("unknown",
     {"nationality_status": "unknown"},
     "Status unknown", None),
]
for label, player, expect_label_frag, expect_note in cases:
    out = _build_passport_eligibility(player)
    chk(f"case [{label}]: label contains {expect_label_frag!r}",
        expect_label_frag in (out['label'] or ''),
        f"got: {out}")
    if expect_note is None:
        chk(f"case [{label}]: note is None (no second line)",
            out['note'] is None,
            f"got note: {out['note']!r}")
    else:
        chk(f"case [{label}]: note starts with {expect_note!r}",
            (out['note'] or '').startswith(expect_note),
            f"got note: {out['note']!r}")
    # Sanity: no banned jargon in either field.
    combined = (out['label'] or '') + ' ' + (out['note'] or '')
    chk(f"case [{label}]: no FIFA jargon in output",
        'Article 5' not in combined and 'admin to confirm' not in combined,
        f"snippet: {combined!r}")

# Pluralization sanity
chk("_humanize_duration(0, 0) == 'less than 1 month'",
    _humanize_duration(0, 0) == 'less than 1 month')
chk("_humanize_duration(1, 0) == '1 year'",
    _humanize_duration(1, 0) == '1 year')
chk("_humanize_duration(2, 1) == '2 years, 1 month'",
    _humanize_duration(2, 1) == '2 years, 1 month')


# ── Item 3: flag SVG ─────────────────────────────────────────
print("\n=== Item 3: flag SVG ===")
from app.passport.data import _flag_svg_inline
from flask import Flask
# _flag_svg_inline needs current_app; spin up a request context.
from app import create_app
flask_app = create_app()
with flask_app.app_context():
    svg_br = _flag_svg_inline('BRA')
    svg_bh = _flag_svg_inline('BHR')
    svg_ma = _flag_svg_inline('MAR')
    svg_xx = _flag_svg_inline('XYZ')
    svg_none = _flag_svg_inline(None)

chk("flag for BRA loads (Arthur's nationality)",
    bool(svg_br) and svg_br.lstrip().startswith('<svg'),
    f"first 60: {(svg_br or '')[:60]!r}")
chk("flag for BHR loads (Bahrain)",
    bool(svg_bh) and svg_bh.lstrip().startswith('<svg'))
chk("flag for MAR loads (Bouhra's nationality)",
    bool(svg_ma) and svg_ma.lstrip().startswith('<svg'))
chk("flag for unknown 'XYZ' returns None",
    svg_xx is None)
chk("flag for None code returns None",
    svg_none is None)

# Profile-page HTML doesn't render the flag (that's PDF only). The
# template render via the route does. Verify the HTML output of the
# data layer ends up with the SVG class in the rendered template.
from app.passport.data import get_passport_data
from flask import render_template
with flask_app.test_request_context():
    data = get_passport_data(p_arthur['id'], mode='full')
    data['wyscout_radar_svg'] = None  # not under test here
    data['meta']['generator_name'] = 'test'
    # Inline render — avoid the WeasyPrint round-trip
    html = render_template('passport/passport.html', **data)
chk("passport HTML contains <span class=\"flag-inline\">",
    'class="flag-inline"' in html,
    f"first occurrence at idx {html.find('flag-inline')}" if 'flag-inline' in html else "")
chk("passport HTML contains an inline <svg> next to flag-inline",
    re.search(r'class="flag-inline"[^>]*>\s*<svg', html) is not None
    or re.search(r'class="flag-inline"[^>]*>[^<]*<svg', html, re.DOTALL) is not None)


# ── Item 4: Wyscout season subtitle ──────────────────────────
print("\n=== Item 4: Wyscout season subtitle ===")
chk("Arthur passport: subtitle 'season · 18 matches' present",
    'season · 18 matches' in text_arthur,
    f"snippet around '18 matches': "
    f"{text_arthur[max(0, text_arthur.find('18 matches')-40):text_arthur.find('18 matches')+40]!r}")
chk("Arthur passport: '2025-26' season label present "
    "(DB hyphen format kept; see CHANGELOG rationale)",
    '2025-26' in text_arthur)
if p_bouhra:
    _, pdf_bh, _, _ = http(admin, "GET",
        f"/players/{p_bouhra['id']}/passport.pdf", raw=True)
    text_bh = extract_pdf_text(pdf_bh)
    # Bouhra has 16 matches per the per-player breakdown from the 4.2 E2E.
    chk("Bouhra passport: subtitle present with '16 matches'",
        '16 matches' in text_bh,
        f"first chars: {text_bh[:200]!r}")


# ── Item 5: loading indicator + timing log ───────────────────
print("\n=== Item 5: loading indicator + timing log ===")
_, profile_html, _, _ = http(admin, "GET", f"/players/{p_arthur['id']}")
chk("profile HTML contains 'passport-btn' class",
    'passport-btn' in profile_html)
# The onclick attr is wrapped in " and contains ' inside (for the JS
# string literals), so [^\"'] would stop at the first inner '. Use
# `re.DOTALL` plus a lazy-match-everything-up-to-Generating.
chk("profile HTML contains onclick with classList.add('loading') and 'Generating' text",
    re.search(r"onclick=\"this\.classList\.add\('loading'\).*?Generating",
              profile_html, re.DOTALL) is not None,
    f"snippet: {profile_html[profile_html.find('passport-btn'):profile_html.find('passport-btn')+500] if 'passport-btn' in profile_html else 'N/A'}")
chk("profile HTML pointer-events:none on loading state",
    'pointer-events: none' in profile_html or 'pointer-events:none' in profile_html)

# Timing log: the renderer emits "passport PDF render: template=...s ...".
# Trigger one more PDF and tail the Flask log.
print("  triggering one more PDF for log capture...")
_, _, _, _ = http(admin, "GET",
    f"/players/{p_arthur['id']}/passport.pdf?public=1", raw=True)
time.sleep(0.5)
# Bash's /tmp ≠ Windows-Python's /tmp. Find the Flask log via the
# OS temp dir (the bash > redirect target), not the literal /tmp path.
import tempfile, pathlib
LOG_CANDIDATES = [
    pathlib.Path(tempfile.gettempdir()) / 'flask_6_1.log',
    pathlib.Path('/tmp/flask_6_1.log'),  # MSYS-style, just in case
    pathlib.Path('C:/Users/alawe/AppData/Local/Temp/flask_6_1.log'),
]
log_text = ''
for cand in LOG_CANDIDATES:
    if cand.exists():
        log_text = cand.read_text(encoding='utf-8', errors='replace')
        print(f"  flask log: {cand}")
        break
m = re.search(
    r"passport PDF render: template=([\d.]+)s  weasyprint=([\d.]+)s  total=([\d.]+)s  bytes=(\d+)",
    log_text,
)
chk("renderer emitted timing line to Flask log",
    m is not None,
    f"log tail: {log_text[-300:].strip()}")
if m:
    tmpl, wp, total, nbytes = float(m.group(1)), float(m.group(2)), float(m.group(3)), int(m.group(4))
    print(f"  TIMING — template {tmpl*1000:.0f}ms · weasyprint {wp:.2f}s · "
          f"total {total:.2f}s · {nbytes} bytes")
    chk("template phase < 1s (sanity — N+1 alert threshold)",
        tmpl < 1.0, f"{tmpl*1000:.0f}ms")
    # On Windows + GTK we expect 5-10s.
    chk("weasyprint phase logged > 0 (not a no-op)",
        wp > 0.05, f"{wp:.2f}s")


# ── Save artefacts for visual inspection ─────────────────────
# Best-effort: artefact writes are diagnostic, not load-bearing for
# pass/fail. If the file is locked (open PDF reader, antivirus scan,
# pypdfium2 mmap) we just skip — the in-memory PDF was already
# inspected for the assertions above.
print("\n=== Saving artefacts for visual review (best-effort) ===")
import pathlib
out_dir = pathlib.Path('/tmp')
try:
    out_dir.mkdir(exist_ok=True)
except OSError as e:
    print(f"  (tempdir mkdir skipped: {e})")
for name, blob in [('passport_6_1_arthur_full.pdf', pdf_arthur)] + \
                  ([('passport_6_1_bouhra_full.pdf', pdf_bh)] if p_bouhra else []):
    try:
        (out_dir / name).write_bytes(blob)
        print(f"  saved: {name} ({len(blob)} bytes)")
    except OSError as e:
        print(f"  (skip {name}: {e})")


# ── Summary ─────────────────────────────────────────────────
print("\n" + "=" * 60)
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"E2E summary: {n_pass} pass / {n_fail} fail (of {len(results)})")
if arthur_wall:
    print(f"Reference wall-time for Arthur's PDF: {arthur_wall:.2f}s")
sys.exit(0 if n_fail == 0 else 2)
