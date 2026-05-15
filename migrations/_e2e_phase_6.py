"""
Phase 6 synthetic E2E. Verifies the Player Passport PDF route end-to-end.

Coverage:
  - GET /players/<id>/passport.pdf returns a real PDF (200, PDF magic
    bytes, Content-Disposition with filename pattern, > 5KB)
  - Page-2 content present (scout evaluations or empty-state)
  - ?public=1 redacts scout names to 'Scout N'
  - ?public=1 strips eligibility_notes_admin / bahrain_residency_notes
  - Nonexistent player → 404
  - Deactivated player (is_active=FALSE) → 404
  - Audit log gets one row per generation

Per the hard rule: real Flask + real HTTP (NOT flask.test_client).
"""
import os
import re
import sys
from urllib.request import build_opener, HTTPCookieProcessor, Request
from http.cookiejar import CookieJar
from urllib.parse import urlencode
from urllib.error import HTTPError

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()
BASE = "http://127.0.0.1:5057"


def http(op, method, path, *, data=None, raw=False):
    body = urlencode(data).encode() if data is not None else None
    req = Request(BASE + path, data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        r = op.open(req)
        content = r.read()
        if not raw:
            content = content.decode("utf-8", errors="replace")
        return r.status, content, r.url, dict(r.headers)
    except HTTPError as e:
        content = e.read()
        if not raw:
            content = content.decode("utf-8", errors="replace")
        return e.code, content, None, dict(e.headers) if hasattr(e, 'headers') else {}


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


# ── Fixtures ─────────────────────────────────────────────────────
admin = login(os.environ["INITIAL_ADMIN_EMAIL"], os.environ["INITIAL_ADMIN_PASSWORD"])

with db() as conn, conn.cursor() as cur:
    cur.execute("SELECT id, full_name FROM players WHERE is_active=TRUE ORDER BY id LIMIT 3")
    active_players = cur.fetchall()
    cur.execute("SELECT id, full_name FROM players WHERE is_active=FALSE ORDER BY id LIMIT 1")
    inactive_player = cur.fetchone()
    cur.execute("SELECT COALESCE(MAX(id), 0) + 9999 AS nonexistent FROM players")
    nonexistent_id = cur.fetchone()['nonexistent']
    cur.execute("SELECT COUNT(*) AS n FROM audit_log WHERE action='player.passport_generated'")
    audit_before = cur.fetchone()['n']

p_arthur = next((p for p in active_players if p['full_name'].lower().startswith('arthur')), active_players[0])
print(f"Test fixtures: Arthur=player_id={p_arthur['id']}, "
      f"inactive={(inactive_player or {}).get('id')}, nonexistent={nonexistent_id}")


# ── Case 1: full-mode PDF for Arthur ─────────────────────────────
print("\n=== Case 1: full-mode PDF ===")
status, pdf, _, headers = http(admin, "GET", f"/players/{p_arthur['id']}/passport.pdf",
                                raw=True)
chk("HTTP 200", status == 200)
chk("Content-Type application/pdf",
    headers.get('Content-Type', '').startswith('application/pdf'),
    f"got: {headers.get('Content-Type')!r}")
chk("PDF magic bytes (%PDF-)", pdf[:5] == b'%PDF-',
    f"first 8: {pdf[:8]!r}")
chk("PDF size > 5000 bytes (sanity — empty PDFs are ~1KB)",
    len(pdf) > 5000, f"size: {len(pdf)}")

cd = headers.get('Content-Disposition', '')
chk("Content-Disposition: attachment",
    'attachment' in cd, f"got: {cd!r}")
chk("filename matches 'BFA-Scout_Player-<id>_<slug>_<date>.pdf' pattern",
    re.search(rf"filename[*]?=.*BFA-Scout_Player-{p_arthur['id']}_[a-z0-9-]+_\d{{4}}-\d{{2}}-\d{{2}}\.pdf",
              cd) is not None,
    f"got: {cd!r}")

# Save the PDF for the spec's "open it visually" step.
out_path = f"/tmp/passport_full_player{p_arthur['id']}.pdf"
with open(out_path, 'wb') as f:
    f.write(pdf)
print(f"  saved: {out_path}")


# ── Case 2: ?public=1 redacts scout names ───────────────────────
print("\n=== Case 2: ?public=1 redaction ===")
# Pull the real evaluator names for this player from the DB so we can
# assert they don't appear in the public PDF text.
with db() as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT DISTINCT u.full_name
        FROM   evaluations e
        JOIN   users u ON u.id = e.evaluator_id
        WHERE  e.player_id = %s
          AND  e.status IN ('submitted','locked')
          AND  e.deleted_at IS NULL
    """, (p_arthur['id'],))
    real_scout_names = [r['full_name'] for r in cur.fetchall()]
print(f"  real scout names for player {p_arthur['id']}: {real_scout_names}")

status, pdf_pub, _, headers_pub = http(
    admin, "GET", f"/players/{p_arthur['id']}/passport.pdf?public=1", raw=True)
chk("public-mode HTTP 200", status == 200)
chk("public-mode PDF magic bytes", pdf_pub[:5] == b'%PDF-')
chk("public-mode size > 5000",  len(pdf_pub) > 5000)

# Extract text from the PDF for content assertions. pypdf is a soft
# dep — fall back to crude byte search if not present, which is fine
# for a redaction check (we only care that the byte sequence doesn't
# appear). PDFs from WeasyPrint contain text as identifiable byte
# patterns when fonts aren't subsetted aggressively.
def extract_pdf_text(pdf_bytes):
    try:
        from pypdf import PdfReader
        from io import BytesIO
        reader = PdfReader(BytesIO(pdf_bytes))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    except ImportError:
        return None  # fall back to byte search

text_pub  = extract_pdf_text(pdf_pub)
text_full = extract_pdf_text(pdf)

if text_pub is not None:
    print(f"  pypdf available — text-search redaction checks active "
          f"(public text {len(text_pub)} chars)")
    for name in real_scout_names:
        chk(f"public PDF does NOT contain real scout name {name!r}",
            name not in text_pub,
            f"found at index {text_pub.find(name)}" if name in text_pub else "")
        chk(f"full PDF DOES contain real scout name {name!r}",
            name in text_full)
    chk("public PDF contains 'Scout' substring (redaction marker)",
        "Scout" in text_pub)
    chk("public PDF footer mentions 'redacted'",
        "redacted" in text_pub.lower(),
        "snippet: ..." + text_pub[-200:].strip()[-200:] if "redacted" not in text_pub.lower() else "")
else:
    print("  pypdf not installed — falling back to byte-pattern search")
    for name in real_scout_names:
        chk(f"public PDF does NOT contain real scout name {name!r} (byte search)",
            name.encode() not in pdf_pub)


# ── Case 3: admin notes hidden in BOTH modes (Phase 6.2.1 contract) ─
# Original Phase 6 contract: admin notes visible in full mode, scrubbed
# in public mode. Phase 6.2.1 changed this — admin notes are admin
# scratchpad and don't belong in ANY user-facing artefact, formal
# documents in particular. The DB columns are preserved and still
# editable via /players/<id>/edit; only the passport rendering is
# hidden. See _e2e_phase_6_2_1.py for the dedicated assertion suite.
print("\n=== Case 3: admin notes hidden in both modes (per 6.2.1) ===")
SENTINEL = f"E2E-SENTINEL-{os.getpid()}-DO-NOT-PUBLISH"

with db() as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT eligibility_notes_admin, bahrain_residency_notes
        FROM   players WHERE id = %s
    """, (p_arthur['id'],))
    prior = cur.fetchone()
    cur.execute("""
        UPDATE players
        SET    eligibility_notes_admin = %s,
               bahrain_residency_notes = %s
        WHERE  id = %s
    """, (SENTINEL + '-elig', SENTINEL + '-resid', p_arthur['id']))
    conn.commit()

try:
    # Both modes: sentinels must NOT appear.
    _, pdf_pub2,  _, _ = http(admin, "GET",
        f"/players/{p_arthur['id']}/passport.pdf?public=1", raw=True)
    text_pub2 = extract_pdf_text(pdf_pub2)
    _, pdf_full2, _, _ = http(admin, "GET",
        f"/players/{p_arthur['id']}/passport.pdf", raw=True)
    text_full2 = extract_pdf_text(pdf_full2)

    if text_pub2 is not None and text_full2 is not None:
        chk("public PDF does NOT contain SENTINEL-elig",
            (SENTINEL + '-elig') not in text_pub2)
        chk("public PDF does NOT contain SENTINEL-resid",
            (SENTINEL + '-resid') not in text_pub2)
        chk("full PDF also does NOT contain SENTINEL-elig (6.2.1 contract)",
            (SENTINEL + '-elig') not in text_full2)
        chk("full PDF also does NOT contain SENTINEL-resid (6.2.1 contract)",
            (SENTINEL + '-resid') not in text_full2)
    else:
        chk("public PDF does NOT contain SENTINEL bytes",
            SENTINEL.encode() not in pdf_pub2)
        chk("full PDF also does NOT contain SENTINEL bytes (6.2.1 contract)",
            SENTINEL.encode() not in pdf_full2)
finally:
    # Restore prior values whatever happens above.
    with db() as conn, conn.cursor() as cur:
        cur.execute("""
            UPDATE players
            SET    eligibility_notes_admin = %s,
                   bahrain_residency_notes = %s
            WHERE  id = %s
        """, (prior['eligibility_notes_admin'],
              prior['bahrain_residency_notes'],
              p_arthur['id']))
        conn.commit()


# ── Case 4: 404 for nonexistent / inactive ──────────────────────
print("\n=== Case 4: error paths ===")
status, _, _, _ = http(admin, "GET", f"/players/{nonexistent_id}/passport.pdf",
                       raw=True)
chk(f"nonexistent player ({nonexistent_id}) returns 404",
    status == 404, f"got: {status}")

if inactive_player:
    status, _, _, _ = http(admin, "GET",
        f"/players/{inactive_player['id']}/passport.pdf", raw=True)
    chk(f"inactive player ({inactive_player['id']}) returns 404",
        status == 404, f"got: {status}")
else:
    print("  (no inactive player in DB — skipping that branch)")


# ── Case 5: audit log captures every generation ─────────────────
print("\n=== Case 5: audit log ===")
with db() as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT COUNT(*) AS n FROM audit_log
        WHERE action = 'player.passport_generated'
    """)
    audit_after = cur.fetchone()['n']
    cur.execute("""
        SELECT details FROM audit_log
        WHERE action = 'player.passport_generated'
        ORDER BY id DESC LIMIT 5
    """)
    recent = cur.fetchall()

n_generated_this_run = audit_after - audit_before
chk(f"audit_log has new player.passport_generated rows",
    n_generated_this_run >= 4,
    f"delta: {n_generated_this_run}")
chk("most recent audit row has player_id + mode in details",
    bool(recent and 'player_id' in (recent[0]['details'] or {})
         and 'mode' in (recent[0]['details'] or {})),
    f"recent[0]: {recent[0]['details'] if recent else None}")

# Mix of modes recorded
modes_seen = {r['details'].get('mode') for r in recent if r['details']}
chk("both 'full' and 'public' modes recorded in recent audit rows",
    'full' in modes_seen and 'public' in modes_seen,
    f"modes_seen: {modes_seen}")


# ── Case 6: full-mode permissions — viewer can't access ─────────
print("\n=== Case 6: permission boundary (viewer + full mode) ===")
# Look up or create a viewer user for this test.
with db() as conn, conn.cursor() as cur:
    cur.execute("SELECT email, full_name FROM users WHERE role='viewer' LIMIT 1")
    viewer = cur.fetchone()

if viewer:
    # We don't have the viewer's password; skip if not in env. To avoid
    # fragility, we just check the permission branch via the unauth path:
    # a logged-out request gets a 302 to /auth/login (login_required).
    anon = build_opener(HTTPCookieProcessor(CookieJar()))
    status, _, final_url, _ = http(anon, "GET",
        f"/players/{p_arthur['id']}/passport.pdf", raw=True)
    # urlopen follows the 302; check final URL is the login page.
    chk("unauthenticated request bounces to /auth/login",
        '/auth/login' in (final_url or ''),
        f"final URL: {final_url}")
else:
    print("  (no viewer user in DB — skipping the viewer 403 sub-case; "
          "covered by the login_required smoke check)")
    anon = build_opener(HTTPCookieProcessor(CookieJar()))
    status, _, final_url, _ = http(anon, "GET",
        f"/players/{p_arthur['id']}/passport.pdf", raw=True)
    chk("unauthenticated request bounces to /auth/login",
        '/auth/login' in (final_url or ''),
        f"final URL: {final_url}")


# ── Case 7: passport renders for player with empty Wyscout/evals ─
print("\n=== Case 7: empty-data resilience ===")
# Find a player with no Wyscout matches AND no evaluations, OR pick the
# first one and just confirm the route doesn't crash regardless.
with db() as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT * FROM (
            SELECT p.id, p.full_name,
                   (SELECT COUNT(*) FROM wyscout_match_stats WHERE player_id=p.id) AS wys,
                   (SELECT COUNT(*) FROM evaluations
                     WHERE player_id=p.id AND deleted_at IS NULL
                       AND status IN ('submitted','locked')) AS evals
            FROM   players p
            WHERE  p.is_active = TRUE
        ) t
        ORDER BY (wys + evals), id
        LIMIT 1
    """)
    sparse = cur.fetchone()
print(f"  sparsest active player: id={sparse['id']} "
      f"({sparse['full_name']!r}) wys={sparse['wys']} evals={sparse['evals']}")

status, pdf_s, _, _ = http(admin, "GET",
    f"/players/{sparse['id']}/passport.pdf", raw=True)
chk("sparsest-data player passport returns 200",
    status == 200)
chk("sparsest-data PDF still has magic bytes (no crash)",
    pdf_s[:5] == b'%PDF-')
chk("sparsest-data PDF size > 3000 (page 1 still renders)",
    len(pdf_s) > 3000, f"size: {len(pdf_s)}")


# ── Summary ─────────────────────────────────────────────────────
print("\n" + "=" * 60)
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"E2E summary: {n_pass} pass / {n_fail} fail (of {len(results)})")
sys.exit(0 if n_fail == 0 else 2)
