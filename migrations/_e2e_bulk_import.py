"""
E2E — Bulk import: Player Registry Excel + CPR-matched photos.

Real Flask + real HTTP (NOT flask.test_client). Server on 127.0.0.1:5057.
Photos use the real DEV pipeline (local FS via app/storage.py — no S3 in
dev, so nothing to stub; we verify the on-disk file + clean it up).

Player import:
  P1  preview classifies NEW / UPDATE / SKIP(example) / ERROR(bad CPR)
  P2  commit creates players; CPR stored as 9-digit TEXT, age_group set
  P3  born-2000 CPR 503061 -> stored '000503061'
  P4  example row skipped (not imported)
  P5  malformed CPR reported as ERROR, not imported
  P6  same CPR as U20 then U23 -> ends up U23 (highest wins)
  P7  imported youth player appears in /youth/<group>, NOT in /players
  P8  re-import same file -> idempotent (no new rows; all UPDATE)
  P9  non-admin -> 403

Photo import:
  H1  <cpr>.jpg matched -> uploaded (player photo URL resolves)
  H2  <unknown-cpr>.jpg -> NO MATCH, not attached
  H3  zero-stripped 41209370.jpg matches player 041209370
  H4  non-admin -> 403
"""
from __future__ import annotations

import io
import os
import re
import sys
import uuid
from datetime import datetime
from urllib.request import build_opener, HTTPCookieProcessor, Request
from urllib.error import HTTPError
from http.cookiejar import CookieJar
from urllib.parse import urlencode

import psycopg2
import psycopg2.extras
from werkzeug.security import generate_password_hash
from dotenv import load_dotenv
from openpyxl import Workbook
from PIL import Image

sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent))

load_dotenv()
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
BASE = "http://127.0.0.1:5057"

# Import storage so we can verify/clean the dev photo files directly.
from app import storage  # noqa: E402


# ───────── HTTP + multipart helpers ──────────────────────────────────────────

def _build_multipart(parts):
    """parts: list of (name, value). value is str OR (filename, bytes, ctype).
    Supports REPEATED field names (needed for multi-file photo upload)."""
    boundary = f"----E2E{uuid.uuid4().hex}"
    lines = []
    for name, val in parts:
        if isinstance(val, tuple) and len(val) == 3:
            filename, file_bytes, ctype = val
            lines.append(f"--{boundary}".encode())
            lines.append(f'Content-Disposition: form-data; name="{name}"; '
                         f'filename="{filename}"'.encode())
            lines.append(f"Content-Type: {ctype}".encode())
            lines.append(b"")
            lines.append(file_bytes)
        else:
            lines.append(f"--{boundary}".encode())
            lines.append(f'Content-Disposition: form-data; name="{name}"'.encode())
            lines.append(b"")
            lines.append(str(val).encode())
    lines.append(f"--{boundary}--".encode())
    lines.append(b"")
    return b"\r\n".join(lines), f"multipart/form-data; boundary={boundary}"


def http(op, method, path, *, data=None, parts=None):
    if parts is not None:
        body, ctype = _build_multipart(parts)
    elif data is not None:
        body, ctype = urlencode(data).encode(), "application/x-www-form-urlencoded"
    else:
        body, ctype = None, None
    req = Request(BASE + path, data=body, method=method)
    if ctype:
        req.add_header("Content-Type", ctype)
    try:
        r = op.open(req)
        return r.status, r.read().decode("utf-8", "replace"), r.url
    except HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), None


def csrf_of(html):
    m = re.search(r'name=["\']csrf_token["\']\s+value=["\']([^"\']+)["\']', html)
    return m.group(1) if m else None


def login(email, pw):
    op = build_opener(HTTPCookieProcessor(CookieJar()))
    _, html, _ = http(op, "GET", "/auth/login")
    http(op, "POST", "/auth/login",
         data={"email": email, "password": pw, "csrf_token": csrf_of(html)})
    return op


def get_csrf(op, path):
    _, html, _ = http(op, "GET", path)
    return csrf_of(html)


def db():
    return psycopg2.connect(os.environ["DATABASE_URL"],
                            cursor_factory=psycopg2.extras.RealDictCursor)


results = []
def chk(label, ok, ev=""):
    results.append((label, ok, ev))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}  {ev}")


# ───────── Build a registry .xlsx mirroring the real template ────────────────

NAME_PREFIX = "E2E-BULK"

def build_registry_xlsx():
    wb = Workbook()
    ws = wb.active
    ws.title = '➡ Player Registry'
    ws['A1'] = 'BFA Player Registry'                 # row 1 banner
    ws['A2'] = 'Fill from row 4'                      # row 2 banner
    ws.append(['Full Name Arabic', 'Full Name (English)', 'CPR Number',
               'Date of Birth', 'Age Group', 'Notes', '#'])   # row 3 headers

    # row 4 — example row (must be skipped)
    ws.append(['مثال', f'{NAME_PREFIX}-Example', 999111222,
               '01/01/2000', 'U17', 'Example only — delete before submitting', 4])
    # data rows (row 5+)
    ws.append(['ألفا', f'{NAME_PREFIX}-Alpha', 41209370,        # int 8d -> 041209370
               datetime(2004, 9, 12), 'U17', None, 5])
    ws.append(['بيتا', f'{NAME_PREFIX}-Beta', 503061,            # born-2000 -> 000503061
               '20/5/2006', 'U20', None, 6])
    ws.append(['جاما', f'{NAME_PREFIX}-Gamma', '605508418',      # text 9d
               ' 18/8/2003', 'senior', None, 7])
    ws.append(['دلتا', f'{NAME_PREFIX}-Delta', 700000041,        # appears twice (U20 then U23)
               '15/3/2005', 'U20', None, 8])
    ws.append(['دلتا', f'{NAME_PREFIX}-Delta', 700000041,        # same CPR, U23 -> highest wins
               '15/3/2005', 'U23', None, 9])
    ws.append(['غارب', f'{NAME_PREFIX}-BadCpr', ' 26/12',        # malformed CPR -> ERROR
               '01/01/2005', 'U17', None, 10])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def png_bytes():
    img = Image.new('RGB', (50, 50), (200, 30, 30))
    b = io.BytesIO()
    img.save(b, format='PNG')
    return b.getvalue()


# Photo-import fixtures. NOTE: these CPRs must NOT collide with any CPR in
# the registry .xlsx — a shared CPR is the SAME player by design, so the
# registry import would rename the photo fixture. ZS uses a short value to
# exercise zero-stripped filename matching (77.jpg -> 000000077).
PHOTO_CPR_FULL = '081112099'        # player created directly; photo named exactly
PHOTO_CPR_ZS_STORED = '000000077'   # player stored CPR (9-digit)
PHOTO_CPR_ZS_FILE   = '77'          # filename stem; normalize -> 000000077
PHOTO_PLAYER_NAME = f'{NAME_PREFIX}-PhotoTarget'
PHOTO_PLAYER_ZS   = f'{NAME_PREFIX}-PhotoZeroStrip'

INSERTED_USER_IDS = []
PHOTO_PLAYER_IDS = []


def cleanup():
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM players WHERE full_name LIKE %s", (f'{NAME_PREFIX}-%',))
        pids = [r['id'] for r in cur.fetchall()]
        if pids:
            cur.execute("DELETE FROM audit_log WHERE entity_type='player' AND entity_id = ANY(%s)", (pids,))
            cur.execute("DELETE FROM evaluations WHERE player_id = ANY(%s)", (pids,))
            cur.execute("DELETE FROM players WHERE id = ANY(%s)", (pids,))
        if INSERTED_USER_IDS:
            cur.execute("DELETE FROM users WHERE id = ANY(%s)", (INSERTED_USER_IDS,))
        conn.commit()
    # remove any dev photo files we created
    for pid in PHOTO_PLAYER_IDS:
        try:
            storage.delete_player_photo(pid)
        except Exception:
            pass


PID = os.getpid()
SCOUT = (f"e2e-bulk-scout-{PID}@bfa.bh", f"pw-{PID}", 'scout')

print("=== Setup ===")
cleanup()   # in case a prior crashed run left rows
with db() as conn, conn.cursor() as cur:
    cur.execute("""INSERT INTO users (email,password_hash,full_name,role,is_active)
                   VALUES (%s,%s,%s,%s,TRUE) RETURNING id""",
                (SCOUT[0], generate_password_hash(SCOUT[1], method='pbkdf2:sha256:600000'),
                 'E2E Bulk Scout', SCOUT[2]))
    INSERTED_USER_IDS.append(cur.fetchone()['id'])
    # photo-target players created directly (registry import not needed for them)
    cur.execute("""INSERT INTO players (full_name,national_id,age_group,is_active,created_by)
                   VALUES (%s,%s,'senior',TRUE,(SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1))
                   RETURNING id""", (PHOTO_PLAYER_NAME, PHOTO_CPR_FULL))
    PHOTO_PLAYER_IDS.append(cur.fetchone()['id'])
    cur.execute("""INSERT INTO players (full_name,national_id,age_group,is_active,created_by)
                   VALUES (%s,%s,'senior',TRUE,(SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1))
                   RETURNING id""", (PHOTO_PLAYER_ZS, PHOTO_CPR_ZS_STORED))
    PHOTO_PLAYER_IDS.append(cur.fetchone()['id'])
    conn.commit()
print(f"  scout={INSERTED_USER_IDS}, photo_players={PHOTO_PLAYER_IDS}")


try:
    admin = login(os.environ["INITIAL_ADMIN_EMAIL"], os.environ["INITIAL_ADMIN_PASSWORD"])
    scout = login(SCOUT[0], SCOUT[1])
    xlsx = build_registry_xlsx()

    # ── P9: non-admin 403 ─────────────────────────────────────────
    print("\n=== Player import ===")
    s, _, _ = http(scout, "GET", "/admin/import/players")
    chk("P9 scout GET /admin/import/players -> 403", s == 403, f"got {s}")

    # ── Upload + preview ──────────────────────────────────────────
    tok = get_csrf(admin, "/admin/import/players")
    http(admin, "POST", "/admin/import/players/upload",
         parts=[("csrf_token", tok),
                ("file", ("registry.xlsx", xlsx,
                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))])
    s, prev, _ = http(admin, "GET", "/admin/import/players/preview")
    chk("P1a preview loads", s == 200, f"got {s}")
    chk("P1b example row SKIP present", "example row" in prev)
    chk("P1c bad CPR ERROR present", "bad CPR" in prev)
    chk("P1d Beta CPR normalized to 000503061 in preview", "000503061" in prev)

    # ── Commit ────────────────────────────────────────────────────
    tok = get_csrf(admin, "/admin/import/players/preview")
    http(admin, "POST", "/admin/import/players/commit", data={"csrf_token": tok})

    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT full_name, national_id, age_group, dob FROM players "
                    "WHERE full_name LIKE %s ORDER BY full_name", (f'{NAME_PREFIX}-%',))
        imported = {r['full_name']: r for r in cur.fetchall()}

    chk("P2 Alpha created, CPR 9-digit TEXT 041209370",
        imported.get(f'{NAME_PREFIX}-Alpha', {}).get('national_id') == '041209370',
        f"got {imported.get(f'{NAME_PREFIX}-Alpha', {}).get('national_id')}")
    chk("P3 born-2000 Beta CPR stored as 000503061",
        imported.get(f'{NAME_PREFIX}-Beta', {}).get('national_id') == '000503061')
    chk("P2b Beta age_group U20",
        imported.get(f'{NAME_PREFIX}-Beta', {}).get('age_group') == 'U20')
    chk("P4 example row NOT imported",
        f'{NAME_PREFIX}-Example' not in imported)
    chk("P5 malformed-CPR row NOT imported",
        f'{NAME_PREFIX}-BadCpr' not in imported)
    chk("P6 Delta (U20 then U23 same CPR) -> U23 (highest wins)",
        imported.get(f'{NAME_PREFIX}-Delta', {}).get('age_group') == 'U23',
        f"got {imported.get(f'{NAME_PREFIX}-Delta', {}).get('age_group')}")
    chk("P3b Gamma messy-DOB ' 18/8/2003' parsed",
        str(imported.get(f'{NAME_PREFIX}-Gamma', {}).get('dob')) == '2003-08-18',
        f"got {imported.get(f'{NAME_PREFIX}-Gamma', {}).get('dob')}")

    # ── P7: youth routing ─────────────────────────────────────────
    _, u17_html, _ = http(admin, "GET", "/youth/u17")
    chk("P7a Alpha (U17) appears in /youth/u17", f'{NAME_PREFIX}-Alpha' in u17_html)
    _, players_html, _ = http(admin, "GET", "/players/")
    chk("P7b Alpha (U17) NOT on general /players", f'{NAME_PREFIX}-Alpha' not in players_html)
    chk("P7c Gamma (senior) IS on general /players", f'{NAME_PREFIX}-Gamma' in players_html)

    # ── P8: idempotent re-import ──────────────────────────────────
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM players WHERE full_name LIKE %s", (f'{NAME_PREFIX}-%',))
        count_before = cur.fetchone()['n']
    tok = get_csrf(admin, "/admin/import/players")
    http(admin, "POST", "/admin/import/players/upload",
         parts=[("csrf_token", tok),
                ("file", ("registry.xlsx", xlsx,
                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))])
    _, prev2, _ = http(admin, "GET", "/admin/import/players/preview")
    tok = get_csrf(admin, "/admin/import/players/preview")
    http(admin, "POST", "/admin/import/players/commit", data={"csrf_token": tok})
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM players WHERE full_name LIKE %s", (f'{NAME_PREFIX}-%',))
        count_after = cur.fetchone()['n']
    chk("P8a re-import creates NO new rows (idempotent)", count_before == count_after,
        f"before={count_before} after={count_after}")
    chk("P8b re-import preview shows 0 new", ">0 new<".replace('>','').replace('<','') and
        re.search(r'(\d+)\s*new', prev2) and int(re.search(r'(\d+)\s*new', prev2).group(1)) == 0,
        f"new-count in preview")

    # ── Photo import ──────────────────────────────────────────────
    print("\n=== Photo import ===")
    s, _, _ = http(scout, "GET", "/admin/import/photos")
    chk("H4 scout GET /admin/import/photos -> 403", s == 403, f"got {s}")

    png = png_bytes()
    tok = get_csrf(admin, "/admin/import/photos")
    http(admin, "POST", "/admin/import/photos/upload",
         parts=[("csrf_token", tok),
                ("files", (f"{PHOTO_CPR_FULL}.jpg", png, "image/jpeg")),
                ("files", (f"{PHOTO_CPR_ZS_FILE}.jpg", png, "image/jpeg")),  # 77 -> 000000077
                ("files", ("999888777.jpg", png, "image/jpeg"))])           # no match
    s, pprev, _ = http(admin, "GET", "/admin/import/photos/preview")
    chk("H1a photo preview loads", s == 200, f"got {s}")
    chk("H1b exact-CPR file shows MATCH to target", PHOTO_PLAYER_NAME in pprev)
    chk("H3a zero-stripped file matches 041209370 player", PHOTO_PLAYER_ZS in pprev)
    chk("H2a unknown CPR shows NO MATCH", "NO_MATCH" in pprev and "999888777" in pprev)

    tok = get_csrf(admin, "/admin/import/photos/preview")
    http(admin, "POST", "/admin/import/photos/commit", data={"csrf_token": tok})

    url_target = storage.get_player_photo_url(PHOTO_PLAYER_IDS[0])
    url_zs     = storage.get_player_photo_url(PHOTO_PLAYER_IDS[1])
    chk("H1c exact-CPR player photo now resolves", bool(url_target), f"url={url_target}")
    chk("H3b zero-stripped player photo now resolves", bool(url_zs), f"url={url_zs}")

finally:
    print("\n(cleanup)")
    cleanup()
    print("  done")


print("\n" + "=" * 60)
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"Bulk-import E2E summary: {n_pass} pass / {n_fail} fail (of {len(results)})")
sys.exit(0 if n_fail == 0 else 2)
