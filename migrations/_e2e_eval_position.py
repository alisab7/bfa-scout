"""
E2E — evaluation: position played in the match (required, display-only).

Real Flask + real HTTP (NOT flask.test_client). Server on 127.0.0.1:5057.

  A  fresh form defaults the position dropdown to the player's primary
  B  save draft with a position != primary → persisted + shown on view
  C  save WITHOUT a position → rejected with required-field error, no draft
  D  winger (primary LW) evaluated as ST → view shows ST; primary stays LW
  E  criteria driver unchanged → eval.position_group_id == player's group
  F  submitted eval shows the played position in the player history
  G  existing evaluations backfilled (no NULL position_played_id)
  H  non-eligible role / unaffected (admin can evaluate) — basic 200 guard
"""
from __future__ import annotations

import os
import re
import sys
from datetime import date
from urllib.request import build_opener, HTTPCookieProcessor, Request
from urllib.error import HTTPError
from http.cookiejar import CookieJar
from urllib.parse import urlencode

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent))

load_dotenv()
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
BASE = "http://127.0.0.1:5057"
PREFIX = "E2E-EVP"


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


def db():
    return psycopg2.connect(os.environ["DATABASE_URL"], cursor_factory=psycopg2.extras.RealDictCursor)


results = []
def chk(label, ok, ev=""):
    results.append((label, ok, ev))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}  {ev}")


PID = os.getpid()
WINGER = f"{PREFIX}-Winger"
INSERTED_PLAYER_IDS = []
INSERTED_MATCH_IDS = []


def cleanup():
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM players WHERE full_name LIKE %s", (f'{PREFIX}-%',))
        pids = [r['id'] for r in cur.fetchall()]
        if pids:
            cur.execute("DELETE FROM evaluation_scores WHERE evaluation_id IN "
                        "(SELECT id FROM evaluations WHERE player_id = ANY(%s))", (pids,))
            cur.execute("DELETE FROM evaluations WHERE player_id = ANY(%s)", (pids,))
            cur.execute("DELETE FROM players WHERE id = ANY(%s)", (pids,))
        if INSERTED_MATCH_IDS:
            cur.execute("DELETE FROM matches WHERE id = ANY(%s)", (INSERTED_MATCH_IDS,))
        conn.commit()


print("=== Setup ===")
cleanup()
with db() as conn, conn.cursor() as cur:
    cur.execute("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1")
    admin_id = cur.fetchone()['id']
    # Pick LW (winger) as primary, ST as the played position, GK as a 3rd.
    def pos_id(code):
        cur.execute("SELECT id, position_group_id FROM positions WHERE code=%s", (code,))
        return cur.fetchone()
    lw = pos_id('LW') or pos_id('LWF') or pos_id('AMF')
    st = pos_id('ST') or pos_id('CF')
    LW_ID, LW_GROUP = lw['id'], lw['position_group_id']
    ST_ID, ST_GROUP = st['id'], st['position_group_id']
    cur.execute("""INSERT INTO players (full_name, national_id, age_group,
                     primary_position_id, is_active, created_by)
                   VALUES (%s,%s,'senior',%s,TRUE,%s) RETURNING id""",
                (WINGER, f'EVP{PID%100000}', LW_ID, admin_id))
    winger_id = cur.fetchone()['id']
    INSERTED_PLAYER_IDS.append(winger_id)
    cur.execute("""INSERT INTO matches (match_date, home_team, away_team, source, created_by)
                   VALUES (%s,'EVP Home','EVP Away','manual',%s) RETURNING id""",
                (date.today().isoformat(), admin_id))
    match_id = cur.fetchone()['id']
    INSERTED_MATCH_IDS.append(match_id)
    conn.commit()
print(f"  winger={winger_id} (primary LW id={LW_ID} grp={LW_GROUP}), ST id={ST_ID} grp={ST_GROUP}, match={match_id}")


def draft_id_for(pid, mid):
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM evaluations WHERE player_id=%s AND match_id=%s "
                    "ORDER BY id DESC LIMIT 1", (pid, mid))
        r = cur.fetchone()
    return r['id'] if r else None


try:
    admin = login(os.environ["INITIAL_ADMIN_EMAIL"], os.environ["INITIAL_ADMIN_PASSWORD"])

    # A — default-to-primary on a fresh form
    print("\n=== Cases ===")
    s, form_html, _ = http(admin, "GET", f"/players/{winger_id}/evaluate")
    chk("H form loads (admin can evaluate)", s == 200, f"got {s}")
    chk("A position dropdown defaults to the player's primary (LW selected)",
        bool(re.search(rf'value="{LW_ID}"[^>]*selected', form_html)),
        "looking for selected primary option")
    chk("A dropdown lists ST as an option too",
        f'value="{ST_ID}"' in form_html)

    # C — save WITHOUT a position → required error, no draft created
    tok = csrf_of(form_html)
    s, body_c, _ = http(admin, "POST", f"/players/{winger_id}/evaluate",
                        data={"csrf_token": tok, "match_id": str(match_id),
                              "position_played_id": "", "action": "save_draft"})
    chk("C save without position is rejected with required error",
        "Position played is required" in body_c, f"status={s}")
    chk("C no draft was created when position missing", draft_id_for(winger_id, match_id) is None)

    # B/D/E — save draft with ST (!= primary LW)
    tok = csrf_of(http(admin, "GET", f"/players/{winger_id}/evaluate")[1])
    http(admin, "POST", f"/players/{winger_id}/evaluate",
         data={"csrf_token": tok, "match_id": str(match_id),
               "position_played_id": str(ST_ID), "action": "save_draft"})
    did = draft_id_for(winger_id, match_id)
    chk("B draft created after saving with a position", did is not None)
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT position_played_id, position_group_id FROM evaluations WHERE id=%s", (did,))
        row = cur.fetchone()
        cur.execute("SELECT primary_position_id FROM players WHERE id=%s", (winger_id,))
        prow = cur.fetchone()
    chk("B position_played_id persisted as ST", row['position_played_id'] == ST_ID,
        f"got {row['position_played_id']}")
    chk("D player's registered primary position UNCHANGED (still LW)",
        prow['primary_position_id'] == LW_ID, f"got {prow['primary_position_id']}")
    chk("E criteria driver unchanged (eval.position_group_id == player's LW group)",
        row['position_group_id'] == LW_GROUP, f"got {row['position_group_id']} want {LW_GROUP}")

    # B (view) — view shows the played position (ST)
    _, view_html, _ = http(admin, "GET", f"/evaluations/{did}")
    chk("B view shows 'Position played' with ST",
        "Position played:" in view_html and "ST" in view_html)

    # F — submit an eval (with position + required fields) → shows in history
    tok = csrf_of(http(admin, "GET", f"/players/{winger_id}/evaluate")[1])
    http(admin, "POST", f"/players/{winger_id}/evaluate",
         data={"csrf_token": tok, "match_id": str(match_id),
               "position_played_id": str(ST_ID), "action": "submit",
               "nt_readiness_level": "u23", "recommendation": "monitor"})
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT status FROM evaluations WHERE id=%s", (did,))
        st_status = cur.fetchone()['status']
    chk("F eval submitted", st_status == 'submitted', f"status={st_status}")
    _, profile_html, _ = http(admin, "GET", f"/players/{winger_id}")
    chk("F player history shows the played position (ST)",
        "played" in profile_html and "ST" in profile_html)

    # G — existing evaluations backfilled (no NULL position_played_id anywhere)
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM evaluations WHERE position_played_id IS NULL "
                    "AND player_id IN (SELECT id FROM players WHERE primary_position_id IS NOT NULL)")
        n_null = cur.fetchone()['n']
    chk("G no eval has NULL position_played_id (for players with a primary position)",
        n_null == 0, f"null count={n_null}")

finally:
    print("\n(cleanup)")
    cleanup()
    print("  done")

print("\n" + "=" * 60)
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"Eval-position E2E summary: {n_pass} pass / {n_fail} fail (of {len(results)})")
sys.exit(0 if n_fail == 0 else 2)
