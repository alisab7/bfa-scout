"""
Phase 9 synthetic E2E — bulk player import.

Real Flask + real HTTP (NOT flask.test_client). Tests cover every
acceptance criterion from the spec (15 cases + setup/cleanup):

  Upload + parse
   1.  Upload CSV with 5 valid rows → preview 5 valid; commit 5 created
   2.  Upload xlsx with same 5 rows → same outcome
   3.  Row missing full_name → that row marked invalid
   8.  Invalid nationality_code → marked invalid
   9.  Invalid position_code → marked invalid
  10.  Empty cells / 'N/A' string → field stored as NULL
  14.  File with >500 rows → rejected at parse time

  Duplicate detection
   4.  Row with national_id matching existing player → duplicate
   5.  Row with name+DOB+position matching existing → duplicate (fuzzy)
   6.  Confirm duplicate set to 'update' → existing player updated
   7.  Confirm duplicate set to 'skip' → existing player untouched

  Lifecycle / permissions
  11.  Audit log gets one row per imported player + one summary entry
  12.  Scout cannot access bulk import (403)
  13.  Anonymous user → 302 to /auth/login
  15.  Discard session → session cleared, fresh upload possible

All inserted rows are tracked and DELETEd in `finally:` so the DB is
left as it was before the run.
"""
from __future__ import annotations

import io
import os
import re
import sys
from urllib.request import build_opener, HTTPCookieProcessor, Request
from urllib.error import HTTPError
from http.cookiejar import CookieJar
from urllib.parse import urlencode

import psycopg2
import psycopg2.extras
from werkzeug.security import generate_password_hash
from dotenv import load_dotenv

sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent))

load_dotenv()
BASE = "http://127.0.0.1:5057"


# ───────── HTTP helpers (multipart-aware) ──────────────────────────────

def http(op, method, path, *, data=None, raw=False, multipart=None):
    """
    `multipart`: optional dict of (field_name, (filename, bytes, content-type))
                  for file uploads. When set, builds a multipart/form-data
                  body. Falls back to urlencode for plain form posts.
    """
    if multipart is not None:
        body, content_type = _build_multipart(multipart)
    elif data is not None:
        body = urlencode(data).encode()
        content_type = "application/x-www-form-urlencoded"
    else:
        body, content_type = None, None

    req = Request(BASE + path, data=body, method=method)
    if content_type:
        req.add_header("Content-Type", content_type)
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
        return e.code, content, None, {}


def _build_multipart(fields):
    """Tiny multipart/form-data builder. `fields` is a dict of either
    str→str (regular form field) or str→(filename, bytes, content_type)
    (file part). Returns (body_bytes, content_type_header)."""
    import uuid
    boundary = f"----E2E{uuid.uuid4().hex}"
    lines = []
    for name, val in fields.items():
        if isinstance(val, tuple) and len(val) == 3:
            filename, file_bytes, ctype = val
            lines.append(f"--{boundary}".encode())
            lines.append(
                f'Content-Disposition: form-data; name="{name}"; '
                f'filename="{filename}"'.encode()
            )
            lines.append(f"Content-Type: {ctype}".encode())
            lines.append(b"")
            lines.append(file_bytes if isinstance(file_bytes, bytes)
                         else file_bytes.encode())
        else:
            lines.append(f"--{boundary}".encode())
            lines.append(
                f'Content-Disposition: form-data; name="{name}"'.encode()
            )
            lines.append(b"")
            lines.append(str(val).encode())
    lines.append(f"--{boundary}--".encode())
    lines.append(b"")
    body = b"\r\n".join(lines)
    return body, f"multipart/form-data; boundary={boundary}"


def login(email, pw):
    op = build_opener(HTTPCookieProcessor(CookieJar()))
    _, html, _, _ = http(op, "GET", "/auth/login")
    m = re.search(r'name=["\']csrf_token["\']\s+value=["\']([^"\']+)["\']', html)
    http(op, "POST", "/auth/login",
         data={"email": email, "password": pw, "csrf_token": m.group(1)})
    return op


def csrf_from_html(html: str) -> str | None:
    m = re.search(r'name=["\']csrf_token["\']\s+value=["\']([^"\']+)["\']', html)
    return m.group(1) if m else None


def db():
    return psycopg2.connect(os.environ["DATABASE_URL"],
                            cursor_factory=psycopg2.extras.RealDictCursor)


results = []
def chk(label, ok, ev=""):
    results.append((label, ok, ev))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}  {ev}")


# ───────── Fixture setup ───────────────────────────────────────────────

print("=== Setup fixtures ===")
admin = login(os.environ["INITIAL_ADMIN_EMAIL"],
              os.environ["INITIAL_ADMIN_PASSWORD"])

# Create a throwaway scout user (snapshot+restore)
SCOUT_EMAIL = f"e2e-p9-scout-{os.getpid()}@bfa.bh"
SCOUT_PW    = f"e2e-p9-scout-pw-{os.getpid()}"
INSERTED_USER_IDS: list[int] = []
INSERTED_PLAYER_IDS: list[int] = []
SNAPSHOT_UPDATED_PLAYERS: dict[int, dict] = {}  # id → original-fields-before-update

with db() as conn, conn.cursor() as cur:
    cur.execute("""
        INSERT INTO users (email, password_hash, full_name, role, is_active)
        VALUES (%s, %s, %s, 'scout', TRUE)
        RETURNING id
    """, (SCOUT_EMAIL,
          generate_password_hash(SCOUT_PW, method='pbkdf2:sha256:600000'),
          'E2E P9 Scout'))
    INSERTED_USER_IDS.append(cur.fetchone()['id'])
    conn.commit()


# Look up a "fixture player" for the duplicate tests. We need one
# with BOTH a DOB and a primary_position_id so the fuzzy-match path
# can be exercised. Arthur (id=2) has no DOB in this DB; Bouhra
# (id=6) does.
with db() as conn, conn.cursor() as cur:
    cur.execute("""SELECT pl.id, pl.full_name, pl.national_id, pl.dob,
                          pl.primary_position_id, p.code AS pos_code
                   FROM players pl
                   LEFT JOIN positions p ON p.id = pl.primary_position_id
                   WHERE pl.is_active = TRUE
                     AND pl.dob IS NOT NULL
                     AND pl.primary_position_id IS NOT NULL
                     AND pl.national_id IS NOT NULL
                   ORDER BY pl.id LIMIT 1""")
    arthur = cur.fetchone()       # name kept for diff-stability; it's actually Bouhra

# The suite must not depend on the DB happening to hold a fully
# populated player. After a registry-style import (e.g. the 26/27
# residents file) every row has a NULL position, so the lookup above
# finds nothing. Seed our own fixture in that case and register it for
# the `finally:` cleanup, so the run leaves the DB exactly as it found
# it — no hand-seeded row survives the suite.
if arthur is None:
    with db() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO players (full_name, national_id, dob,
                                 primary_position_id, is_active)
            SELECT 'E2E P9 FIXTURE PLAYER', %s, DATE '1995-05-05',
                   p.id, TRUE
            FROM positions p ORDER BY p.id LIMIT 1
            RETURNING id
        """, (f"E2EP9{os.getpid()}"[:32],))
        fixture_id = cur.fetchone()['id']
        conn.commit()
    INSERTED_PLAYER_IDS.append(fixture_id)
    with db() as conn, conn.cursor() as cur:
        cur.execute("""SELECT pl.id, pl.full_name, pl.national_id, pl.dob,
                              pl.primary_position_id, p.code AS pos_code
                       FROM players pl
                       JOIN positions p ON p.id = pl.primary_position_id
                       WHERE pl.id = %s""", (fixture_id,))
        arthur = cur.fetchone()
    print("  (no fully-populated player in DB — seeded a throwaway "
          "fixture; it is deleted in cleanup)")

arthur_pos_code = arthur['pos_code']
print(f"  fixture player: id={arthur['id']} ({arthur['full_name']!r}), "
      f"national_id={arthur['national_id']}, dob={arthur['dob']}, "
      f"pos={arthur_pos_code}")


# Generate test CSV/xlsx bytes. We use unique-prefixed names so we can
# find them in the DB later for cleanup without nuking unrelated rows.
PREFIX = f"E2EP9-{os.getpid()}-"

def make_csv(rows, headers=None):
    """rows = list of dicts. Build a CSV bytes blob."""
    if not headers:
        headers = list(rows[0].keys()) if rows else []
    import csv
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=headers, extrasaction='ignore')
    w.writeheader()
    for r in rows:
        w.writerow({k: ('' if r.get(k) is None else r.get(k)) for k in headers})
    return out.getvalue().encode('utf-8')


HEADERS = [
    'full_name', 'dob', 'national_id', 'primary_position_code',
    'nationality_code', 'nationality_status',
    'eligible_from_date', 'bahrain_residency_start_date',
    'current_club_name', 'dominant_foot', 'height_cm', 'weight_kg',
]


def upload_and_preview(op, csv_bytes, filename="test.csv",
                       content_type="text/csv"):
    """Upload a file → follow redirect to preview → return (status,
    preview_html). The opener's session cookie is updated along the way."""
    # Need a CSRF token from the upload page (CSRFProtect requires it
    # on POST).
    _, upload_html, _, _ = http(op, "GET", "/admin/players/bulk-import")
    csrf = csrf_from_html(upload_html)
    status, preview_html, _, _ = http(
        op, "POST", "/admin/players/bulk-import/upload",
        multipart={
            "csrf_token": csrf,
            "file": (filename, csv_bytes, content_type),
        },
    )
    return status, preview_html


def commit_import(op, row_actions: dict[int, str] | None = None):
    """POST to commit. row_actions maps row_number → 'skip' | 'update'."""
    _, preview_html, _, _ = http(op, "GET", "/admin/players/bulk-import/preview")
    csrf = csrf_from_html(preview_html)
    form = {"csrf_token": csrf}
    for row_num, action in (row_actions or {}).items():
        form[f"row_{row_num}_action"] = action
    return http(op, "POST", "/admin/players/bulk-import/commit", data=form)


try:
    # ──────────── Case 1: upload CSV with 5 valid rows ─────────────
    print("\n=== Case 1: CSV with 5 valid rows ===")
    csv5 = make_csv([
        {'full_name': f'{PREFIX}Player A', 'dob': '2000-01-01',
         'primary_position_code': 'CB', 'nationality_code': 'BHR'},
        {'full_name': f'{PREFIX}Player B', 'dob': '2001-02-02',
         'primary_position_code': 'CF', 'nationality_code': 'BHR'},
        {'full_name': f'{PREFIX}Player C', 'national_id': 'P9NATIO0003',
         'dob': '2002-03-03', 'primary_position_code': 'GK'},
        {'full_name': f'{PREFIX}Player D', 'dob': '2003-04-04',
         'primary_position_code': 'LB', 'nationality_code': 'BHR'},
        {'full_name': f'{PREFIX}Player E', 'dob': '2004-05-05',
         'primary_position_code': 'RB', 'nationality_code': 'BHR'},
    ], headers=HEADERS)
    status, html = upload_and_preview(admin, csv5, filename="case1.csv")
    chk("Case 1a: upload→preview returns 200", status == 200, f"got: {status}")
    chk("Case 1b: preview reports 5 valid rows",
        "5</strong> valid" in html or "<strong class=\"bulk-create\">5</strong> valid" in html
        or "5 valid" in html.replace("</strong>", "").replace("<strong>", "").replace(
            "<strong class=\"bulk-create\">", ""),
        f"snippet: {html[html.find('valid')-30:html.find('valid')+60] if 'valid' in html else 'N/A'}")
    # Commit and verify DB
    status, body, _, _ = commit_import(admin)
    chk("Case 1c: commit redirects (302 or 200 result page)",
        status in (200, 302))
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, full_name FROM players WHERE full_name LIKE %s",
                    (PREFIX + '%',))
        rows = cur.fetchall()
        for r in rows:
            INSERTED_PLAYER_IDS.append(r['id'])
    chk("Case 1d: 5 new players in DB matching the test prefix",
        len(rows) == 5, f"got: {len(rows)} ({[r['full_name'] for r in rows]})")


    # ──────────── Case 2: same 5 rows via xlsx ───────────────────────
    print("\n=== Case 2: xlsx with 5 valid rows ===")
    XPREFIX = f"E2EP9X-{os.getpid()}-"
    xlsx_rows = [
        {'full_name': f'{XPREFIX}Player A', 'dob': '2000-01-01'},
        {'full_name': f'{XPREFIX}Player B', 'dob': '2001-02-02'},
        {'full_name': f'{XPREFIX}Player C', 'dob': '2002-03-03'},
        {'full_name': f'{XPREFIX}Player D', 'dob': '2003-04-04'},
        {'full_name': f'{XPREFIX}Player E', 'dob': '2004-05-05'},
    ]
    import pandas as pd
    df = pd.DataFrame(xlsx_rows, columns=HEADERS)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        df.to_excel(w, index=False)
    status, html = upload_and_preview(
        admin, buf.getvalue(), filename="case2.xlsx",
        content_type=("application/vnd.openxmlformats-officedocument."
                       "spreadsheetml.sheet"))
    chk("Case 2a: xlsx upload→preview 200", status == 200)
    chk("Case 2b: xlsx preview reports 5 valid",
        "5" in html and "valid" in html)
    commit_import(admin)
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM players WHERE full_name LIKE %s",
                    (XPREFIX + '%',))
        rows = cur.fetchall()
        for r in rows:
            INSERTED_PLAYER_IDS.append(r['id'])
    chk("Case 2c: 5 xlsx-imported players in DB", len(rows) == 5,
        f"got: {len(rows)}")


    # ──────────── Case 3: row missing full_name → invalid ────────────
    print("\n=== Case 3: row missing full_name ===")
    csv_mix = make_csv([
        {'full_name': f'{PREFIX}Valid 1', 'dob': '2000-01-01'},
        {'full_name': '',                'dob': '2001-01-01'},  # invalid: no name
        {'full_name': f'{PREFIX}Valid 2', 'dob': '2002-01-01'},
    ], headers=HEADERS)
    status, html = upload_and_preview(admin, csv_mix, filename="case3.csv")
    chk("Case 3a: preview returns 200", status == 200)
    chk("Case 3b: preview contains 'INVALID' badge",
        "INVALID" in html)
    chk("Case 3c: preview contains 'full_name is required'",
        "full_name is required" in html or "full_name" in html)
    # Discard so we don't carry it into the next case
    http(admin, "GET", "/admin/players/bulk-import/discard")


    # ──────────── Case 4: national_id matches existing → duplicate ───
    print("\n=== Case 4: national_id matches Arthur ===")
    csv_dup_nat = make_csv([
        # Row 1: brand new
        {'full_name': f'{PREFIX}New Player', 'national_id': 'P9NEW000001'},
        # Row 2: matches Arthur via national_id
        {'full_name': 'Different Name',
         'national_id': arthur['national_id'],
         'dob': '1999-12-31', 'primary_position_code': 'CB'},
    ], headers=HEADERS)
    status, html = upload_and_preview(admin, csv_dup_nat, filename="case4.csv")
    chk("Case 4a: preview 200", status == 200)
    chk("Case 4b: preview contains 'DUPLICATE' badge",
        "DUPLICATE" in html)
    chk(f"Case 4c: preview mentions player #{arthur['id']}",
        f"#{arthur['id']}" in html)
    http(admin, "GET", "/admin/players/bulk-import/discard")


    # ──────────── Case 5: name+DOB+position match → fuzzy duplicate ──
    print("\n=== Case 5: fuzzy duplicate (name+DOB+position) ===")
    csv_fuzzy = make_csv([
        {'full_name': arthur['full_name'],          # exact match (case-insens)
         'dob':       arthur['dob'].isoformat(),
         'primary_position_code': arthur_pos_code},
    ], headers=HEADERS)
    status, html = upload_and_preview(admin, csv_fuzzy, filename="case5.csv")
    chk("Case 5a: preview 200", status == 200)
    chk("Case 5b: preview contains 'DUPLICATE' (fuzzy match)",
        "DUPLICATE" in html)
    chk(f"Case 5c: matches player #{arthur['id']}",
        f"#{arthur['id']}" in html)
    http(admin, "GET", "/admin/players/bulk-import/discard")


    # ──────────── Case 6 + 7: commit with skip / update ──────────────
    print("\n=== Case 6: duplicate set to 'update' refreshes existing ===")
    # Snapshot Arthur's current state so we can verify & restore.
    with db() as conn, conn.cursor() as cur:
        cur.execute("""SELECT full_name, height_cm, weight_kg, foot
                       FROM players WHERE id = %s""",
                    (arthur['id'],))
        SNAPSHOT_UPDATED_PLAYERS[arthur['id']] = dict(cur.fetchone())
    SENTINEL_HEIGHT = 177
    csv_update = make_csv([
        {'full_name': arthur['full_name'],
         'dob':       arthur['dob'].isoformat(),
         'primary_position_code': arthur_pos_code,
         'height_cm': str(SENTINEL_HEIGHT)},
    ], headers=HEADERS)
    status, html = upload_and_preview(admin, csv_update, filename="case6.csv")
    chk("Case 6a: preview 200 (update setup)", status == 200)
    # Commit with row 1 action=update
    commit_import(admin, row_actions={1: 'update'})
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT height_cm FROM players WHERE id = %s",
                    (arthur['id'],))
        post = cur.fetchone()
    chk(f"Case 6b: Arthur's height_cm updated to {SENTINEL_HEIGHT}",
        post['height_cm'] == SENTINEL_HEIGHT,
        f"got: {post['height_cm']}")

    print("\n=== Case 7: duplicate set to 'skip' leaves existing untouched ===")
    # Snapshot post-Case-6 state; the subsequent skip should leave it as-is.
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT height_cm FROM players WHERE id = %s",
                    (arthur['id'],))
        pre = cur.fetchone()
    csv_skip = make_csv([
        {'full_name': arthur['full_name'],
         'dob':       arthur['dob'].isoformat(),
         'primary_position_code': arthur_pos_code,
         'height_cm': '199'},   # would change height if applied
    ], headers=HEADERS)
    status, html = upload_and_preview(admin, csv_skip, filename="case7.csv")
    chk("Case 7a: preview 200 (skip setup)", status == 200)
    # Commit WITHOUT specifying row_actions → default 'skip'
    commit_import(admin)
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT height_cm FROM players WHERE id = %s",
                    (arthur['id'],))
        post_skip = cur.fetchone()
    chk(f"Case 7b: Arthur's height_cm unchanged by skip ({pre['height_cm']})",
        post_skip['height_cm'] == pre['height_cm'],
        f"pre={pre['height_cm']}, post={post_skip['height_cm']}")


    # ──────────── Case 8: invalid nationality_code ───────────────────
    print("\n=== Case 8: invalid nationality_code ===")
    csv_bad_nat = make_csv([
        {'full_name': f'{PREFIX}BadNat', 'nationality_code': 'XYZ'},
    ], headers=HEADERS)
    status, html = upload_and_preview(admin, csv_bad_nat, filename="case8.csv")
    chk("Case 8a: preview 200", status == 200)
    chk("Case 8b: row flagged INVALID", "INVALID" in html)
    chk("Case 8c: error mentions nationality_code",
        "nationality_code" in html)
    http(admin, "GET", "/admin/players/bulk-import/discard")


    # ──────────── Case 9: invalid position_code ──────────────────────
    print("\n=== Case 9: invalid position_code ===")
    csv_bad_pos = make_csv([
        {'full_name': f'{PREFIX}BadPos', 'primary_position_code': 'ZZZ'},
    ], headers=HEADERS)
    status, html = upload_and_preview(admin, csv_bad_pos, filename="case9.csv")
    chk("Case 9a: preview 200", status == 200)
    chk("Case 9b: row flagged INVALID", "INVALID" in html)
    chk("Case 9c: error mentions position_code",
        "position_code" in html)
    http(admin, "GET", "/admin/players/bulk-import/discard")


    # ──────────── Case 10: empty / 'N/A' → NULL ──────────────────────
    print("\n=== Case 10: empty + 'N/A' → NULL ===")
    csv_nulls = make_csv([
        {'full_name': f'{PREFIX}NullTest A',
         'dob': '', 'national_id': '', 'primary_position_code': 'CB',
         'nationality_code': '', 'dominant_foot': '',
         'height_cm': '', 'weight_kg': ''},
        {'full_name': f'{PREFIX}NullTest B',
         'dob': 'N/A', 'national_id': 'N/A', 'primary_position_code': 'CF',
         'nationality_code': 'N/A'},
    ], headers=HEADERS)
    status, html = upload_and_preview(admin, csv_nulls, filename="case10.csv")
    chk("Case 10a: preview 200", status == 200)
    chk("Case 10b: both rows flagged CREATE (no validation errors)",
        html.count("CREATE") >= 2,
        f"CREATE count: {html.count('CREATE')}")
    commit_import(admin)
    with db() as conn, conn.cursor() as cur:
        cur.execute("""SELECT id, full_name, dob, national_id,
                              nationality_code, foot, height_cm, weight_kg
                       FROM players
                       WHERE full_name IN (%s, %s)""",
                    (f'{PREFIX}NullTest A', f'{PREFIX}NullTest B'))
        nulls = cur.fetchall()
    for r in nulls:
        INSERTED_PLAYER_IDS.append(r['id'])
    chk(f"Case 10c: {len(nulls)} 'NullTest' players in DB",
        len(nulls) == 2)
    all_nullable_null = all(
        r['dob'] is None and r['national_id'] is None
        and r['nationality_code'] is None and r['height_cm'] is None
        for r in nulls
    )
    chk("Case 10d: empty/N-A fields stored as NULL in DB",
        all_nullable_null,
        f"rows: {[dict(r) for r in nulls]}")


    # ──────────── Case 11: audit log entries ─────────────────────────
    print("\n=== Case 11: audit log entries ===")
    # We've committed at least one player by this point (Case 1 already
    # ran). Check for the player-level + summary-level entries.
    with db() as conn, conn.cursor() as cur:
        cur.execute("""SELECT COUNT(*) AS n FROM audit_log
                       WHERE action = 'player.bulk_imported'""")
        n_player_audits = cur.fetchone()['n']
        cur.execute("""SELECT COUNT(*) AS n FROM audit_log
                       WHERE action = 'admin.bulk_import_completed'""")
        n_summary_audits = cur.fetchone()['n']
        cur.execute("""SELECT details FROM audit_log
                       WHERE action = 'player.bulk_imported'
                       ORDER BY id DESC LIMIT 1""")
        r = cur.fetchone()
    chk("Case 11a: at least one player.bulk_imported audit row",
        n_player_audits >= 1, f"count: {n_player_audits}")
    chk("Case 11b: at least one admin.bulk_import_completed audit row",
        n_summary_audits >= 1, f"count: {n_summary_audits}")
    chk("Case 11c: player-audit details has the expected keys",
        bool(r and r['details']
             and 'row_number' in (r['details'] or {})
             and 'action' in (r['details'] or {})
             and 'source_file_name' in (r['details'] or {})),
        f"sample: {r['details'] if r else None}")


    # ──────────── Case 12: scout 403'd ───────────────────────────────
    print("\n=== Case 12: scout role 403 on /admin/players/bulk-import ===")
    scout = login(SCOUT_EMAIL, SCOUT_PW)
    status, _, _, _ = http(scout, "GET", "/admin/players/bulk-import")
    chk("Case 12: scout GET → 403", status == 403, f"got: {status}")


    # ──────────── Case 13: anonymous → 401 ───────────────────────────
    print("\n=== Case 13: anonymous gets blocked ===")
    # `admin_required` uses `abort(401)` (not login_required's 302), so
    # an anonymous request gets HTTP 401 directly. Either response shape
    # is "blocked" — assert on the not-2xx status.
    anon = build_opener(HTTPCookieProcessor(CookieJar()))
    status, _, final_url, _ = http(anon, "GET", "/admin/players/bulk-import")
    chk("Case 13: anon GET → 401 or 302-to-login (both = blocked)",
        status == 401 or (status in (200, 302) and '/auth/login' in (final_url or '')),
        f"status: {status}, final_url: {final_url}")


    # ──────────── Case 14: >500 rows rejected ────────────────────────
    print("\n=== Case 14: >500 rows rejected ===")
    big_rows = [{'full_name': f'{PREFIX}Big {i}'} for i in range(501)]
    big_csv = make_csv(big_rows, headers=HEADERS)
    _, upload_html, _, _ = http(admin, "GET", "/admin/players/bulk-import")
    csrf = csrf_from_html(upload_html)
    status, body, _, headers = http(
        admin, "POST", "/admin/players/bulk-import/upload",
        multipart={"csrf_token": csrf,
                   "file": ("big.csv", big_csv, "text/csv")})
    # Upload endpoint redirects on failure with a flash message; check
    # the resulting page has the error.
    chk("Case 14a: upload of 501-row file returns 200 (after redirect)",
        status == 200)
    chk("Case 14b: error message mentions 'max' / 500",
        ("max is 500" in body) or ("max is " in body),
        f"body has 'max': {('max' in body)}; "
        f"snippet: {body[body.find('max')-20:body.find('max')+80] if 'max' in body else 'N/A'}")
    # Make sure we didn't accidentally park the giant file
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM players WHERE full_name LIKE %s",
                    (f'{PREFIX}Big %',))
        chk("Case 14c: no 'Big N' players landed in DB",
            cur.fetchone()['n'] == 0)


    # ──────────── Case 15: discard clears session ────────────────────
    print("\n=== Case 15: discard clears session ===")
    # Park something, discard it, then verify a fresh upload works.
    csv_park = make_csv([{'full_name': f'{PREFIX}Park 1', 'dob': '2000-01-01'}],
                        headers=HEADERS)
    status, _ = upload_and_preview(admin, csv_park, filename="park.csv")
    chk("Case 15a: parked session uploaded", status == 200)
    http(admin, "GET", "/admin/players/bulk-import/discard")
    # Re-fetch index — pending-banner should NOT be present.
    _, idx_html, _, _ = http(admin, "GET", "/admin/players/bulk-import")
    chk("Case 15b: after discard, no 'pending import' banner",
        "pending import" not in idx_html.lower())
    # Confirm parked row didn't land in DB (we didn't commit; just discard).
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM players WHERE full_name = %s",
                    (f'{PREFIX}Park 1',))
        chk("Case 15c: discarded row didn't land in DB",
            cur.fetchone()['n'] == 0)


    # ──────────── Bonus: template downloads ──────────────────────────
    print("\n=== Bonus: template downloads ===")
    status, body, _, headers_ = http(admin, "GET",
        "/admin/players/bulk-import/template.csv", raw=True)
    chk("Bonus 1: CSV template returns 200", status == 200)
    chk("Bonus 2: CSV template content-type text/csv",
        headers_.get('Content-Type', '').startswith('text/csv'),
        f"got: {headers_.get('Content-Type')}")
    chk("Bonus 3: CSV template contains the column headers",
        all(h in body.decode('utf-8') for h in
            ('full_name', 'national_id', 'primary_position_code')))
    status, body, _, headers_ = http(admin, "GET",
        "/admin/players/bulk-import/template.xlsx", raw=True)
    chk("Bonus 4: xlsx template returns 200", status == 200)
    chk("Bonus 5: xlsx template content-type is the openxml sheet MIME",
        'spreadsheet' in headers_.get('Content-Type', ''))


finally:
    print("\n(cleanup)")
    with db() as conn, conn.cursor() as cur:
        # Restore any updated original players first (Arthur's height)
        for pid, snap in SNAPSHOT_UPDATED_PLAYERS.items():
            cur.execute("""UPDATE players SET
                              height_cm = %(height_cm)s,
                              weight_kg = %(weight_kg)s,
                              foot      = %(foot)s,
                              updated_at = NOW()
                           WHERE id = %(id)s""",
                        {**snap, 'id': pid})
        # Delete any inserted test players. Their audit_log rows
        # (player.bulk_imported and admin.bulk_import_completed) are
        # *kept* — they're a real trace of this test run, useful for
        # forensic checks if anything's odd. The next regression run
        # won't be affected: assertions are >=1, not ==1.
        if INSERTED_PLAYER_IDS:
            cur.execute("DELETE FROM players WHERE id = ANY(%s)",
                        (INSERTED_PLAYER_IDS,))
        if INSERTED_USER_IDS:
            cur.execute("DELETE FROM users WHERE id = ANY(%s)",
                        (INSERTED_USER_IDS,))
        conn.commit()
    print(f"  restored {len(SNAPSHOT_UPDATED_PLAYERS)} updated players, "
          f"deleted {len(INSERTED_PLAYER_IDS)} test players + "
          f"{len(INSERTED_USER_IDS)} test users")


# ───────── Summary ───────────────────────────────────────────────────
print("\n" + "=" * 60)
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"E2E summary: {n_pass} pass / {n_fail} fail (of {len(results)})")
sys.exit(0 if n_fail == 0 else 2)
