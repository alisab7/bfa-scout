"""
Phase 6.2.1 synthetic E2E. Verifies admin notes are gone from all
user-facing surfaces.

Approach: seed a throwaway player, inject distinctive sentinel strings
into its `eligibility_notes_admin` and `bahrain_residency_notes`
columns, then assert those strings do NOT appear in:
  - the full-mode passport PDF
  - the public-mode passport PDF
  - the player profile page HTML

…BUT do appear (in form-field shape) on the admin edit page —
proving the data path is intact, only the user-facing rendering is
hidden. The player is seeded by this suite and deleted in `finally:`
(the `try:` opens before the first mutation), so the test leaves no
trace and never mutates a real player's admin notes.

Per hard rule: real Flask + real HTTP. No flask.test_client.
"""
import os
import pathlib
import re
import sys
from io import BytesIO
from urllib.request import build_opener, HTTPCookieProcessor, Request
from http.cookiejar import CookieJar
from urllib.parse import urlencode

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()
BASE = "http://127.0.0.1:5057"
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


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
    return "\n".join(
        (p.extract_text() or "")
        for p in PdfReader(BytesIO(pdf_bytes)).pages
    )


results = []
def chk(label, ok, ev=""):
    results.append((label, ok, ev))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}  {ev}")


# ── Fixtures ─────────────────────────────────────────────────────
admin = login(os.environ["INITIAL_ADMIN_EMAIL"], os.environ["INITIAL_ADMIN_PASSWORD"])

PID = os.getpid()
PLAYER_NAME    = f"E2E-621 Player {PID}"
SENTINEL_ELIG  = f"S621-ELIG-{PID}-DO-NOT-PUBLISH"
SENTINEL_RESID = f"S621-RESID-{PID}-DO-NOT-PUBLISH"

INSERTED_PLAYER_IDS: list[int] = []


def cleanup():
    """Remove every fixture this suite creates. Safe to call twice."""
    with db() as conn, conn.cursor() as cur:
        if INSERTED_PLAYER_IDS:
            cur.execute("DELETE FROM audit_log WHERE entity_type='player' "
                        "AND entity_id = ANY(%s)", (INSERTED_PLAYER_IDS,))
            cur.execute("DELETE FROM players WHERE id = ANY(%s)",
                        (INSERTED_PLAYER_IDS,))
        conn.commit()


# The `try:` opens BEFORE the first mutation, so a failure during setup still
# removes the seeded player instead of leaking it.
try:
    # Seed the player carrying the sentinels. Residency route with a start
    # date >5y ago so the eligibility section actually renders a recognised
    # label on the passport (asserted below).
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1")
        admin_user_id = cur.fetchone()['id']
        cur.execute("SELECT id FROM positions ORDER BY id LIMIT 1")
        position_id = cur.fetchone()['id']
        cur.execute("""
            INSERT INTO players (full_name, full_name_ar, national_id, dob,
                                 primary_position_id, nationality,
                                 nationality_status,
                                 bahrain_residency_start_date,
                                 eligibility_notes_admin,
                                 bahrain_residency_notes,
                                 age_group, is_active, created_by)
            VALUES (%s, %s, %s, DATE '2000-01-01', %s, 'Brazil',
                    'foreign_residency', CURRENT_DATE - INTERVAL '6 years',
                    %s, %s, 'senior', TRUE, %s)
            RETURNING id, full_name
        """, (PLAYER_NAME, 'لاعب', f'E2E621{PID}', position_id,
              SENTINEL_ELIG, SENTINEL_RESID, admin_user_id))
        player = cur.fetchone()
        INSERTED_PLAYER_IDS.append(player['id'])
        conn.commit()
    chk("seeded player row created", player is not None)
    print(f"  player_id={player['id']} ({PLAYER_NAME!r}) — sentinels injected")

    # ── Full-mode PDF ─────────────────────────────────────────
    print("\n=== Full-mode passport PDF ===")
    _, pdf_full, _, _ = http(admin, "GET",
        f"/players/{player['id']}/passport.pdf", raw=True)
    text_full = extract_pdf_text(pdf_full)
    chk("full PDF returned (%PDF magic + > 5KB)",
        pdf_full[:5] == b'%PDF-' and len(pdf_full) > 5000)
    chk("full PDF does NOT contain SENTINEL_ELIG",
        SENTINEL_ELIG not in text_full,
        f"found at idx {text_full.find(SENTINEL_ELIG)}" if SENTINEL_ELIG in text_full else "")
    chk("full PDF does NOT contain SENTINEL_RESID",
        SENTINEL_RESID not in text_full)
    chk("full PDF does NOT contain 'Eligibility notes (admin)' label",
        'Eligibility notes (admin)' not in text_full)
    chk("full PDF does NOT contain 'Residency notes (admin)' label",
        'Residency notes (admin)' not in text_full)
    # Eligibility section itself still renders.
    chk("full PDF still has eligibility content (one of the recognised labels)",
        any(s in text_full for s in
            ('Eligible from', 'Eligible now', 'Not eligible',
             'Status unknown', 'Pending', 'Foreign-eligible')),
        f"first 200 chars of eligibility region: "
        f"{text_full[max(0, text_full.find('Eligibility')-20):text_full.find('Eligibility')+200]!r}")

    # ── Public-mode PDF ───────────────────────────────────────
    print("\n=== Public-mode passport PDF ===")
    _, pdf_pub, _, _ = http(admin, "GET",
        f"/players/{player['id']}/passport.pdf?public=1", raw=True)
    text_pub = extract_pdf_text(pdf_pub)
    chk("public PDF returned (%PDF magic + > 5KB)",
        pdf_pub[:5] == b'%PDF-' and len(pdf_pub) > 5000)
    chk("public PDF does NOT contain SENTINEL_ELIG",
        SENTINEL_ELIG not in text_pub)
    chk("public PDF does NOT contain SENTINEL_RESID",
        SENTINEL_RESID not in text_pub)
    chk("public PDF does NOT contain 'Eligibility notes (admin)' label",
        'Eligibility notes (admin)' not in text_pub)

    # ── Profile page HTML ─────────────────────────────────────
    print("\n=== Profile page HTML (/players/<id>) ===")
    _, profile_html, _, _ = http(admin, "GET", f"/players/{player['id']}")
    chk("profile page HTML does NOT contain SENTINEL_ELIG",
        SENTINEL_ELIG not in profile_html,
        f"found at idx {profile_html.find(SENTINEL_ELIG)}" if SENTINEL_ELIG in profile_html else "")
    chk("profile page HTML does NOT contain SENTINEL_RESID",
        SENTINEL_RESID not in profile_html)
    chk("profile page HTML does NOT contain 'Eligibility notes (admin)' label",
        'Eligibility notes (admin)' not in profile_html)
    chk("profile page HTML does NOT contain 'Residency notes (admin)' label",
        'Residency notes (admin)' not in profile_html)

    # ── Edit form (admin-only path) — SHOULD contain the data ──
    print("\n=== Admin edit page (/players/<id>/edit) ===")
    _, edit_html, _, _ = http(admin, "GET", f"/players/{player['id']}/edit")
    chk("edit page has the eligibility_notes_admin form field "
        "(admin authors them here)",
        'name="eligibility_notes_admin"' in edit_html)
    chk("edit page has the bahrain_residency_notes form field",
        'name="bahrain_residency_notes"' in edit_html)
    chk("edit page contains SENTINEL_ELIG (form prefilled with DB value)",
        SENTINEL_ELIG in edit_html,
        f"snippet: ...{edit_html[max(0, edit_html.find('eligibility_notes_admin')-40):edit_html.find('eligibility_notes_admin')+300] if 'eligibility_notes_admin' in edit_html else 'N/A'}")
    chk("edit page contains SENTINEL_RESID (form prefilled with DB value)",
        SENTINEL_RESID in edit_html)

    # ── Sanity: passport template literal check ──────────────
    print("\n=== Template sanity: passport.html has no admin-note rendering ===")
    tmpl = (REPO_ROOT / 'app' / 'templates' / 'passport'
            / 'passport.html').read_text(encoding='utf-8')
    # The Jinja conditional shouldn't appear; comments mentioning the
    # field names are fine (they're explanatory).
    chk("passport.html has no `{% if player.eligibility_notes_admin %}` block",
        '{% if player.eligibility_notes_admin %}' not in tmpl)
    chk("passport.html has no `{% if player.bahrain_residency_notes %}` block",
        '{% if player.bahrain_residency_notes %}' not in tmpl)
    chk("passport.html has no `{{ player.eligibility_notes_admin }}` print",
        '{{ player.eligibility_notes_admin }}' not in tmpl)
    chk("passport.html has no `{{ player.bahrain_residency_notes }}` print",
        '{{ player.bahrain_residency_notes }}' not in tmpl)

finally:
    # ── Remove the seeded fixture (leave no trace) ───────────
    cleanup()
    print(f"\n(cleanup: deleted {len(INSERTED_PLAYER_IDS)} seeded player(s))")


# ── Summary ────────────────────────────────────────────────────
print("\n" + "=" * 60)
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"E2E summary: {n_pass} pass / {n_fail} fail (of {len(results)})")
sys.exit(0 if n_fail == 0 else 2)
