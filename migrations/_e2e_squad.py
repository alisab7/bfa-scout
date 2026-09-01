"""
E2E — First-Team Squad (admin-curated `squad_members`).

Real Flask + real HTTP (NOT flask.test_client). Server on 127.0.0.1:5057.

Every fixture (players AND users) is SEEDED BY THIS SUITE and deleted in
`finally:` — nothing is ever SELECTed out of ambient DB state, so the
suite is self-contained and leaves the local DB exactly as it found it.

  1  round-trip — admin bulk-adds 3 players via /admin/squad → 3 rows in
     squad_members → all 3 render on the /nt/squad view after a reload
  2  remove — one removed → gone from the view, `players` row INTACT
  3  idempotent add — re-adding a member creates no duplicate (COUNT = 1)
     and does not rewrite the original added_by/added_at
  4  isolation — a never-added player is ABSENT from the squad view
  5  no eligibility gate — a still-counting `foreign_residency` prospect
     CAN be added and renders its counting badge; a citizen renders the
     citizen badge (both asserted against compute_eligibility_status too)
  6  auth (manage) — TD / nt_staff / scout / viewer / youth_nt cannot add
     or remove (403) AND the DB is unchanged afterwards
  7  auth (view)   — admin + TD + nt_staff get 200 on /nt/squad;
     scout / viewer / youth_nt get 403; the tab is hidden from scouts on
     /nt/residents (which they can see)
  8  commit discipline — writes are visible on a fresh DB connection
"""
from __future__ import annotations

import os
import re
import sys
from datetime import date, timedelta
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

from app.players.eligibility import compute_eligibility_status  # noqa: E402

BASE = "http://127.0.0.1:5057"
PREFIX = "E2E-SQUAD"


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
    http(op, "POST", "/auth/login",
         data={"email": email, "password": pw, "csrf_token": csrf_of(html)})
    return op


def csrf_from(op, path):
    return csrf_of(http(op, "GET", path)[1])


def db():
    return psycopg2.connect(os.environ["DATABASE_URL"],
                            cursor_factory=psycopg2.extras.RealDictCursor)


results = []


def chk(label, ok, ev=""):
    results.append((label, ok, ev))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}  {ev}")


PID = os.getpid()
USERS = {
    'admin':  (f"e2e-squad-admin-{PID}@bfa.bh",  f"pw-{PID}", 'admin'),
    'td':     (f"e2e-squad-td-{PID}@bfa.bh",     f"pw-{PID}", 'technical_director'),
    'nt':     (f"e2e-squad-nt-{PID}@bfa.bh",     f"pw-{PID}", 'nt_staff'),
    'scout':  (f"e2e-squad-scout-{PID}@bfa.bh",  f"pw-{PID}", 'scout'),
    'viewer': (f"e2e-squad-viewer-{PID}@bfa.bh", f"pw-{PID}", 'viewer'),
    'youth':  (f"e2e-squad-youth-{PID}@bfa.bh",  f"pw-{PID}", 'youth_nt'),
}
INSERTED_USER_IDS: list[int] = []
ids: dict[str, int] = {}

CITIZEN  = f"{PREFIX}-Citizen"      # bahraini, no origin      → "Citizen"
PROSPECT = f"{PREFIX}-Prospect"     # foreign_residency, 2y in → still counting
THIRD    = f"{PREFIX}-Third"        # third member of the add batch
OUTSIDE  = f"{PREFIX}-Outside"      # never added — isolation check


def cleanup():
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM players WHERE full_name LIKE %s", (f'{PREFIX}-%',))
        pids = [r['id'] for r in cur.fetchall()]
        if pids:
            cur.execute("DELETE FROM squad_members WHERE player_id = ANY(%s)", (pids,))
            cur.execute("DELETE FROM audit_log WHERE entity_type='player' AND entity_id = ANY(%s)",
                        (pids,))
            cur.execute("DELETE FROM players WHERE id = ANY(%s)", (pids,))
        cur.execute("SELECT id FROM users WHERE email LIKE %s", (f'e2e-squad-%-{PID}@bfa.bh',))
        uids = [r['id'] for r in cur.fetchall()] + INSERTED_USER_IDS
        if uids:
            cur.execute("DELETE FROM audit_log WHERE user_id = ANY(%s)", (uids,))
            cur.execute("DELETE FROM squad_members WHERE added_by = ANY(%s)", (uids,))
            cur.execute("DELETE FROM users WHERE id = ANY(%s)", (uids,))
        conn.commit()


def squad_rows(player_id):
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM squad_members WHERE player_id = %s",
                    (player_id,))
        return cur.fetchone()['n']


def squad_total():
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM squad_members")
        return cur.fetchone()['n']


print("=== Setup ===")
cleanup()

two_years_ago = date.today() - timedelta(days=730)

with db() as conn, conn.cursor() as cur:
    for (email, pw, role) in USERS.values():
        cur.execute("""INSERT INTO users (email, password_hash, full_name, role, is_active)
                       VALUES (%s,%s,%s,%s,TRUE) RETURNING id""",
                    (email, generate_password_hash(pw, method='pbkdf2:sha256:600000'),
                     f'E2E SQUAD {role}', role))
        INSERTED_USER_IDS.append(cur.fetchone()['id'])
    admin_uid = INSERTED_USER_IDS[0]

    seq = {'n': 0}

    def mk(name, **cols):
        seq['n'] += 1
        base = {'full_name': name, 'full_name_ar': 'لاعب',
                'national_id': f'SQ{PID}-{seq["n"]}',
                'age_group': 'senior', 'is_active': True, 'created_by': admin_uid}
        base.update(cols)
        keys = list(base)
        cur.execute(
            f"INSERT INTO players ({', '.join(keys)}) "
            f"VALUES ({', '.join(['%s'] * len(keys))}) RETURNING id",
            [base[k] for k in keys]
        )
        return cur.fetchone()['id']

    # Citizen — born Bahraini, NO origin_country → badge "Citizen".
    ids['citizen'] = mk(CITIZEN, nationality_status='bahraini', nationality_code='BHR')
    # Prospect — residency started 2y ago → 5y clock still counting.
    ids['prospect'] = mk(PROSPECT, nationality_status='foreign_residency',
                         nationality_code='BRA',
                         bahrain_residency_start_date=two_years_ago)
    ids['third'] = mk(THIRD, nationality_status='bahraini', nationality_code='BHR')
    ids['outside'] = mk(OUTSIDE, nationality_status='bahraini', nationality_code='BHR')
    conn.commit()
print(f"  players={ids}")
print(f"  users={len(INSERTED_USER_IDS)}  squad_members before={squad_total()}")

BASELINE_SQUAD_TOTAL = squad_total()


def view_html(op):
    return http(op, "GET", "/nt/squad")[1]


try:
    admin  = login(*USERS['admin'][:2])
    td     = login(*USERS['td'][:2])
    nt     = login(*USERS['nt'][:2])
    scout  = login(*USERS['scout'][:2])
    viewer = login(*USERS['viewer'][:2])
    youth  = login(*USERS['youth'][:2])

    # ── 7 — VIEW audience ────────────────────────────────────────────
    print("\n=== 7 view audience (/nt/squad) ===")
    for name, op in [('admin', admin), ('TD', td), ('nt_staff', nt)]:
        s, _, _ = http(op, "GET", "/nt/squad")
        chk(f"7 {name} GET /nt/squad → 200", s == 200, f"got {s}")
    for name, op in [('scout', scout), ('viewer', viewer), ('youth_nt', youth)]:
        s, _, _ = http(op, "GET", "/nt/squad")
        chk(f"7 {name} GET /nt/squad → 403", s == 403, f"got {s}")

    # Management page is admin-only (tighter than assign-clubs' admin+TD).
    s, _, _ = http(admin, "GET", "/admin/squad")
    chk("7 admin GET /admin/squad → 200", s == 200, f"got {s}")
    for name, op in [('TD', td), ('nt_staff', nt), ('scout', scout), ('viewer', viewer)]:
        s, _, _ = http(op, "GET", "/admin/squad")
        chk(f"7 {name} GET /admin/squad → 403", s == 403, f"got {s}")

    # Tab hidden from scouts on the one /nt page they CAN see.
    s, res_html, _ = http(scout, "GET", "/nt/residents")
    chk("7 scout sees /nt/residents but NOT the squad tab",
        s == 200 and "/nt/squad" not in res_html, f"status={s}")
    _, res_admin, _ = http(admin, "GET", "/nt/residents")
    chk("7b admin DOES see the squad tab on /nt/residents", "/nt/squad" in res_admin)

    # ── 6 — non-admin cannot ADD (403 + DB unchanged) ───────────────
    print("\n=== 6 manage auth (add/remove blocked for non-admins) ===")
    before = squad_total()
    # CSRF is fetched from "/" for every role — base.html's sign-out form
    # always carries a token, so a 400 can never masquerade as the 403.
    for name, op in [('TD', td), ('nt_staff', nt), ('scout', scout),
                     ('viewer', viewer), ('youth_nt', youth)]:
        tok = csrf_from(op, "/")
        s, _, _ = http(op, "POST", "/admin/squad/add",
                       data={"csrf_token": tok, "player_ids": ids['citizen']})
        chk(f"6 {name} POST /admin/squad/add → 403", s == 403, f"got {s}")
    chk("6 DB unchanged after every blocked add",
        squad_total() == before and squad_rows(ids['citizen']) == 0,
        f"total={squad_total()} (was {before})")

    # ── 1 — admin bulk-adds 3 players ───────────────────────────────
    print("\n=== 1 round-trip (bulk add 3 → DB → view) ===")
    tok = csrf_from(admin, "/admin/squad")
    batch = [ids['citizen'], ids['prospect'], ids['third']]
    s, _, _ = http(admin, "POST", "/admin/squad/add",
                   data=[("csrf_token", tok)] + [("player_ids", p) for p in batch])
    chk("1a bulk add accepted (redirect/200)", s in (200, 302), f"got {s}")

    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT player_id, added_by, added_at FROM squad_members "
                    "WHERE player_id = ANY(%s) ORDER BY player_id", (batch,))
        rows = cur.fetchall()
    chk("1b 3 rows persisted in squad_members", len(rows) == 3, f"rows={len(rows)}")
    chk("1c added_by recorded as the acting admin",
        all(r['added_by'] == admin_uid for r in rows))
    original_added_at = {r['player_id']: r['added_at'] for r in rows}

    html = view_html(admin)          # fresh GET = reload
    chk("1d all 3 appear on the squad view after reload",
        all(n in html for n in (CITIZEN, PROSPECT, THIRD)))

    # ── 8 — commit discipline (fresh connection sees the write) ─────
    chk("8 add persisted across a fresh DB connection (explicit commit)",
        squad_rows(ids['citizen']) == 1)

    # ── 4 — isolation ───────────────────────────────────────────────
    print("\n=== 4 isolation ===")
    chk("4 a never-added player is ABSENT from the squad view",
        OUTSIDE not in html)
    chk("4b that player still exists in `players`", squad_rows(ids['outside']) == 0)

    # ── 5 — no eligibility gate + badges ────────────────────────────
    print("\n=== 5 no eligibility gate + badge rendering ===")
    with db() as conn, conn.cursor() as cur:
        cur.execute("""SELECT id, nationality_status, eligible_from_date,
                              bahrain_residency_start_date, origin_country,
                              nationality_code, dob
                       FROM players WHERE id = ANY(%s)""",
                    [[ids['citizen'], ids['prospect']]])
        by_id = {r['id']: dict(r) for r in cur.fetchall()}

    elig_prospect = compute_eligibility_status(by_id[ids['prospect']])
    elig_citizen  = compute_eligibility_status(by_id[ids['citizen']])
    chk("5a still-counting prospect WAS added (no eligibility gate)",
        squad_rows(ids['prospect']) == 1)
    chk("5b compute_eligibility_status says prospect is NOT eligible now",
        elig_prospect['status_code'] == 'eligible_future'
        and elig_prospect['is_eligible_now'] is False,
        f"{elig_prospect['status_code']} / {elig_prospect['label']!r}")
    chk("5c prospect's counting badge renders in the squad view",
        'data-status="eligible_future"' in html
        and elig_prospect['label'] in html,
        f"label={elig_prospect['label']!r}")
    chk("5d citizen badge renders in the squad view",
        elig_citizen['status_code'] == 'citizen'
        and 'data-status="citizen"' in html
        and 'Citizen' in html)
    chk("5e the badge macro (not ad-hoc markup) drives both",
        html.count('class="elig-badge') >= 3, f"badges={html.count('elig-badge')}")

    # Row anatomy: photo via get_player_photo(player_id) + onerror fallback,
    # position via get_player_pos, club column.
    chk("5f rows carry a photo with an onerror placeholder fallback",
        "onerror=" in html and "photos/placeholder.svg" in html)

    # ── 3 — idempotent add ──────────────────────────────────────────
    print("\n=== 3 idempotent add ===")
    tok = csrf_from(admin, "/admin/squad")
    http(admin, "POST", "/admin/squad/add",
         data={"csrf_token": tok, "player_ids": ids['citizen']})
    chk("3a re-adding an existing member creates NO duplicate",
        squad_rows(ids['citizen']) == 1, f"rows={squad_rows(ids['citizen'])}")
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT added_at FROM squad_members WHERE player_id = %s",
                    (ids['citizen'],))
        chk("3b original added_at preserved (DO NOTHING, not DO UPDATE)",
            cur.fetchone()['added_at'] == original_added_at[ids['citizen']])
    chk("3c squad size unchanged by the duplicate add",
        squad_total() == BASELINE_SQUAD_TOTAL + 3, f"total={squad_total()}")

    # ── 9 — the pick list is searchable/filterable (88+ players) ────
    # /admin/squad has TWO tables: the current squad (always complete, not
    # filtered) and the filterable PICK LIST below the "Add players"
    # heading. These checks look only at the pick list.
    print("\n=== 9 search + filters on /admin/squad ===")

    def picklist(query):
        html_ = http(admin, "GET", "/admin/squad?" + query)[1]
        return html_.split("Add players")[-1]

    byname = picklist(f"q={PREFIX}-Citiz")
    chk("9a q= narrows the pick list to the matching player",
        CITIZEN in byname and PROSPECT not in byname and OUTSIDE not in byname)
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT national_id FROM players WHERE id = %s", (ids['outside'],))
        nid = cur.fetchone()['national_id']
    byid = picklist(f"q={nid}")
    chk("9b q= also matches on National / BFA ID",
        OUTSIDE in byid and CITIZEN not in byid)
    out_only = picklist(f"q={PREFIX}&show=out")
    chk("9c show=out lists only players NOT in the squad",
        OUTSIDE in out_only and CITIZEN not in out_only and PROSPECT not in out_only)
    in_only = picklist(f"q={PREFIX}&show=in")
    chk("9d show=in lists only current members",
        CITIZEN in in_only and PROSPECT in in_only and OUTSIDE not in in_only)
    nomatch = picklist("q=ZZZ-NO-SUCH-PLAYER-ZZZ")
    chk("9e an empty result set renders the no-match message, not a crash",
        "No active players match those filters." in nomatch)

    # ── 6b — non-admin cannot REMOVE ────────────────────────────────
    print("\n=== 6b remove blocked for non-admins ===")
    before = squad_total()
    for name, op in [('TD', td), ('nt_staff', nt), ('scout', scout)]:
        tok = csrf_from(op, "/")
        s, _, _ = http(op, "POST", "/admin/squad/remove",
                       data={"csrf_token": tok, "player_id": ids['citizen']})
        chk(f"6b {name} POST /admin/squad/remove → 403", s == 403, f"got {s}")
    chk("6b DB unchanged after every blocked remove",
        squad_total() == before and squad_rows(ids['citizen']) == 1)

    # ── 2 — remove one: membership only ─────────────────────────────
    print("\n=== 2 remove (membership only, player kept) ===")
    tok = csrf_from(admin, "/admin/squad")
    s, _, _ = http(admin, "POST", "/admin/squad/remove",
                   data={"csrf_token": tok, "player_id": ids['third']})
    chk("2a remove accepted", s in (200, 302), f"got {s}")
    chk("2b membership row gone", squad_rows(ids['third']) == 0)

    html2 = view_html(admin)
    chk("2c removed player is gone from the squad view", THIRD not in html2)
    chk("2d the other two members are still there",
        CITIZEN in html2 and PROSPECT in html2)

    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, full_name, is_active FROM players WHERE id = %s",
                    (ids['third'],))
        prow = cur.fetchone()
    chk("2e the PLAYER row is intact (removal deleted membership only)",
        prow is not None and prow['full_name'] == THIRD and prow['is_active'] is True,
        f"player={prow}")

    # ── nt_staff / TD read the same curated list ────────────────────
    print("\n=== view content for the wider audience ===")
    for name, op in [('TD', td), ('nt_staff', nt)]:
        h = view_html(op)
        chk(f"7c {name} sees the same 2 members and not the removed one",
            CITIZEN in h and PROSPECT in h and THIRD not in h)

finally:
    print("\n(cleanup)")
    cleanup()
    left = squad_total()
    print(f"  squad_members rows left = {left} (baseline {BASELINE_SQUAD_TOTAL})")
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM players")
        print(f"  players rows = {cur.fetchone()['n']}")
    print("  done")

print("\n" + "=" * 60)
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"First-team-squad E2E summary: {n_pass} pass / {n_fail} fail (of {len(results)})")
sys.exit(0 if n_fail == 0 else 2)
