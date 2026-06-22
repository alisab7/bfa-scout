"""
E2E — youth shortlist (tracked prospects).

Real Flask + real HTTP (NOT flask.test_client). Server on 127.0.0.1:5057.

  1  admin adds a youth player with a note → appears on /youth/shortlist
  2  nt_staff can add; TD can view (admin/TD/nt_staff access)
  3  scout/viewer/youth_nt → 403 on add route AND on /youth/shortlist
  4  profile shows correct button state (add vs on-shortlist) for admin
  5  remove → drops off the shortlist
  6  re-add already-shortlisted → updates note, no duplicate (UNIQUE holds)
  7  shortlist page shows age_group + note + added_by
  8  promoted-to-senior shortlisted player stays on the list (keep decision)
  9  only youth can be newly added (senior non-listed → rejected)
 10  conn.commit() — persists across a fresh request / DB read
"""
from __future__ import annotations

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
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
BASE = "http://127.0.0.1:5057"
PREFIX = "E2E-YSL"


def http(op, method, path, *, data=None):
    body = urlencode(data).encode() if data is not None else None
    req = Request(BASE + path, data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
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
    http(op, "POST", "/auth/login", data={"email": email, "password": pw, "csrf_token": csrf_of(html)})
    return op


def csrf_from(op, path):
    return csrf_of(http(op, "GET", path)[1])


def db():
    return psycopg2.connect(os.environ["DATABASE_URL"], cursor_factory=psycopg2.extras.RealDictCursor)


results = []
def chk(label, ok, ev=""):
    results.append((label, ok, ev))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}  {ev}")


PID = os.getpid()
USERS = {
    'td':     (f"e2e-ysl-td-{PID}@bfa.bh",     f"pw-{PID}", 'technical_director'),
    'nt':     (f"e2e-ysl-nt-{PID}@bfa.bh",     f"pw-{PID}", 'nt_staff'),
    'scout':  (f"e2e-ysl-scout-{PID}@bfa.bh",  f"pw-{PID}", 'scout'),
    'viewer': (f"e2e-ysl-viewer-{PID}@bfa.bh", f"pw-{PID}", 'viewer'),
    'youth':  (f"e2e-ysl-youth-{PID}@bfa.bh",  f"pw-{PID}", 'youth_nt'),
}
INSERTED_USER_IDS = []
ids = {}
YOUTH = f"{PREFIX}-YouthA"
YOUTH2 = f"{PREFIX}-YouthB"
SENIOR = f"{PREFIX}-Senior"


def cleanup():
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM players WHERE full_name LIKE %s", (f'{PREFIX}-%',))
        pids = [r['id'] for r in cur.fetchall()]
        if pids:
            cur.execute("DELETE FROM youth_shortlist WHERE player_id = ANY(%s)", (pids,))
            cur.execute("DELETE FROM audit_log WHERE entity_type='player' AND entity_id = ANY(%s)", (pids,))
            cur.execute("DELETE FROM players WHERE id = ANY(%s)", (pids,))
        if INSERTED_USER_IDS:
            cur.execute("DELETE FROM users WHERE id = ANY(%s)", (INSERTED_USER_IDS,))
        conn.commit()


print("=== Setup ===")
cleanup()
with db() as conn, conn.cursor() as cur:
    for (email, pw, role) in USERS.values():
        cur.execute("""INSERT INTO users (email,password_hash,full_name,role,is_active)
                       VALUES (%s,%s,%s,%s,TRUE) RETURNING id""",
                    (email, generate_password_hash(pw, method='pbkdf2:sha256:600000'),
                     f'E2E YSL {role}', role))
        INSERTED_USER_IDS.append(cur.fetchone()['id'])
    cur.execute("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1")
    admin_id = cur.fetchone()['id']

    def mk(name, age_group):
        cur.execute("""INSERT INTO players (full_name, full_name_ar, national_id,
                         age_group, is_active, created_by)
                       VALUES (%s,%s,%s,%s,TRUE,%s) RETURNING id""",
                    (name, 'لاعب', f'YSL{abs(hash(name))%1000000}', age_group, admin_id))
        return cur.fetchone()['id']

    ids['youth'] = mk(YOUTH, 'U20')
    ids['youth2'] = mk(YOUTH2, 'U17')
    ids['senior'] = mk(SENIOR, 'senior')
    conn.commit()
print(f"  players={ids}")


def on_shortlist(name):
    """Is `name` present on the shortlist page (as admin)?"""
    _, html, _ = http(admin, "GET", "/youth/shortlist")
    return name in html


try:
    admin  = login(os.environ["INITIAL_ADMIN_EMAIL"], os.environ["INITIAL_ADMIN_PASSWORD"])
    td     = login(*USERS['td'][:2])
    nt     = login(*USERS['nt'][:2])
    scout  = login(*USERS['scout'][:2])
    viewer = login(*USERS['viewer'][:2])
    youth  = login(*USERS['youth'][:2])

    # 3 — access boundary
    print("\n=== access boundary ===")
    for name, op in [('scout', scout), ('viewer', viewer), ('youth_nt', youth)]:
        s, _, _ = http(op, "GET", "/youth/shortlist")
        chk(f"3 {name} GET /youth/shortlist → 403", s == 403, f"got {s}")
    # scout POST add (with a valid csrf from a page they can load) → 403
    tok = csrf_from(scout, f"/players/{ids['youth']}")
    s, _, _ = http(scout, "POST", f"/players/{ids['youth']}/shortlist",
                   data={"csrf_token": tok, "note": "x"})
    chk("3 scout POST add → 403", s == 403, f"got {s}")
    s, _, _ = http(td, "GET", "/youth/shortlist")
    chk("2 TD GET /youth/shortlist → 200", s == 200, f"got {s}")

    # 4 — profile button state (admin), not yet shortlisted
    print("\n=== add + profile state ===")
    _, prof, _ = http(admin, "GET", f"/players/{ids['youth']}")
    chk("4a profile shows '+ Add to shortlist' before adding",
        "Add to shortlist" in prof and "On youth shortlist" not in prof)

    # 1 — admin adds youth player with note
    tok = csrf_from(admin, f"/players/{ids['youth']}")
    http(admin, "POST", f"/players/{ids['youth']}/shortlist",
         data={"csrf_token": tok, "note": "Strong left foot, track for U23"})
    chk("1 youth player appears on /youth/shortlist after add", on_shortlist(YOUTH))
    _, prof2, _ = http(admin, "GET", f"/players/{ids['youth']}")
    chk("4b profile shows 'On youth shortlist' after adding", "On youth shortlist" in prof2)

    # 7 — shortlist page shows age_group + note + added_by
    _, sl_html, _ = http(admin, "GET", "/youth/shortlist")
    chk("7 shortlist shows note", "Strong left foot" in sl_html)
    chk("7b shortlist shows age_group U20", "U20" in sl_html)
    chk("7c shortlist shows added-by name", "Initial Administrator" in sl_html or "by " in sl_html)

    # 2 — nt_staff can add (the U17 player)
    tok = csrf_from(nt, f"/players/{ids['youth2']}")
    s, _, _ = http(nt, "POST", f"/players/{ids['youth2']}/shortlist",
                   data={"csrf_token": tok, "note": "U17 prospect"})
    chk("2 nt_staff can add a youth player", on_shortlist(YOUTH2))

    # 6 — re-add updates note, no duplicate (UNIQUE)
    tok = csrf_from(admin, f"/players/{ids['youth']}")
    http(admin, "POST", f"/players/{ids['youth']}/shortlist",
         data={"csrf_token": tok, "note": "UPDATED NOTE v2"})
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n, MAX(note) AS note FROM youth_shortlist WHERE player_id=%s",
                    (ids['youth'],))
        row = cur.fetchone()
    chk("6 re-add did not duplicate (exactly 1 row)", row['n'] == 1, f"rows={row['n']}")
    chk("6b re-add updated the note", row['note'] == "UPDATED NOTE v2", f"note={row['note']!r}")

    # 9 — only youth can be newly added (senior, not on list → rejected)
    tok = csrf_from(admin, f"/players/{ids['senior']}")
    http(admin, "POST", f"/players/{ids['senior']}/shortlist",
         data={"csrf_token": tok, "note": "should be rejected"})
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM youth_shortlist WHERE player_id=%s", (ids['senior'],))
        chk("9 senior (not youth) NOT added to shortlist", cur.fetchone()['n'] == 0)

    # 8 — promoted player stays on shortlist
    print("\n=== promotion keeps + remove + commit ===")
    with db() as conn, conn.cursor() as cur:
        cur.execute("UPDATE players SET age_group='senior' WHERE id=%s", (ids['youth'],))
        conn.commit()
    chk("8 promoted-to-senior player still on shortlist", on_shortlist(YOUTH))
    # and update-note still works on the now-senior entry
    tok = csrf_from(admin, f"/players/{ids['youth']}")
    s, _, _ = http(admin, "POST", f"/players/{ids['youth']}/shortlist",
                   data={"csrf_token": tok, "note": "made it to senior"})
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT note FROM youth_shortlist WHERE player_id=%s", (ids['youth'],))
        chk("8b note-update works on promoted entry",
            cur.fetchone()['note'] == "made it to senior")

    # 5 — remove → drops off
    tok = csrf_from(admin, f"/players/{ids['youth']}")
    http(admin, "POST", f"/players/{ids['youth']}/shortlist/remove",
         data={"csrf_token": tok})
    chk("5 removed player drops off the shortlist", not on_shortlist(YOUTH))

    # 10 — commit persistence (fresh DB connection sees the U17 add)
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM youth_shortlist WHERE player_id=%s", (ids['youth2'],))
        chk("10 add persisted across fresh connection (commit)", cur.fetchone()['n'] == 1)

finally:
    print("\n(cleanup)")
    cleanup()
    print("  done")

print("\n" + "=" * 60)
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"Youth-shortlist E2E summary: {n_pass} pass / {n_fail} fail (of {len(results)})")
sys.exit(0 if n_fail == 0 else 2)
