"""
E2E — Recent Matches show the opponent ("vs <opponent>") on the player profile.

Real Flask + real HTTP (NOT flask.test_client). Server on 127.0.0.1:5057.

The profile's Recent Matches cell previously showed only the date. It now shows
the opponent next to it. Source: wyscout_match_stats.home_team/away_team (both
100% populated); is_home indicates the player's side but is NULL in real data,
so the template shows BOTH teams ("home vs away") and auto-upgrades to
"vs <opponent>" when is_home IS set. Cases:

  M1  both teams, is_home NULL  → "<home> vs <away>"            (the real case)
  M2  single team only          → "vs <team>"
  M3  is_home = TRUE            → opponent = away_team ("vs <away>", home hidden)
  M4  is_home = FALSE           → opponent = home_team ("vs <home>", away hidden)
  M5  no teams at all           → date only, row renders (graceful, no "vs")
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
PREFIX = "E2E-RMO"


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


def db():
    return psycopg2.connect(os.environ["DATABASE_URL"],
                            cursor_factory=psycopg2.extras.RealDictCursor)


results = []
def chk(label, ok, ev=""):
    results.append((label, ok, ev))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}  {ev}")


PLAYER = f"{PREFIX}-Player"


def cleanup():
    with db() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM players WHERE full_name LIKE %s", (f'{PREFIX}-%',))
        conn.commit()  # wyscout_match_stats cascades on player delete


print("=== Setup ===")
cleanup()
with db() as conn, conn.cursor() as cur:
    cur.execute("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1")
    admin_id = cur.fetchone()['id']
    cur.execute("""INSERT INTO players (full_name, national_id, age_group,
                       nationality_status, is_active, created_by)
                   VALUES (%s, %s, 'senior', 'bahraini', TRUE, %s) RETURNING id""",
                (PLAYER, 'RMO001', admin_id))
    pid = cur.fetchone()['id']

    def mk(d, label, home, away, is_home, comp):
        cur.execute("""INSERT INTO wyscout_match_stats
                         (player_id, match_label, competition, match_date,
                          home_team, away_team, is_home, minutes_played)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,90)""",
                    (pid, label, comp, d, home, away, is_home))

    # M1 both teams, is_home NULL → "Al Muharraq vs Riffa"
    mk(date(2026, 5, 1), 'M1 Al Muharraq - Riffa 1:0', 'Al Muharraq', 'Riffa', None, 'BPL')
    # M2 single team only → "vs Sitra"
    mk(date(2026, 4, 1), 'M2 Sitra solo', 'Sitra', None, None, 'BPL')
    # M3 is_home TRUE → opponent = away_team (Manama); home (Hidd) hidden
    mk(date(2026, 3, 1), 'M3 Hidd - Manama 2:2', 'Hidd', 'Manama', True, 'BPL')
    # M4 is_home FALSE → opponent = home_team (Budaiya); away (Najma) hidden
    mk(date(2026, 2, 1), 'M4 Budaiya - Najma 0:1', 'Budaiya', 'Najma', False, 'BPL')
    # M5 no teams → date only, must still render (unique comp sentinel)
    mk(date(2026, 1, 1), 'M5 unknown teams', None, None, None, 'NOOPPCOMP')
    conn.commit()
print(f"  player id={pid}, 5 match rows")


try:
    admin = login(os.environ["INITIAL_ADMIN_EMAIL"],
                  os.environ["INITIAL_ADMIN_PASSWORD"])
    status, html, _ = http(admin, "GET", f"/players/{pid}")
    chk("profile renders (200)", status == 200, f"status={status}")

    print("\n=== M1: both teams (is_home NULL) ===")
    chk("M1 shows 'Al Muharraq vs Riffa'", "Al Muharraq vs Riffa" in html)

    print("\n=== M2: single team only ===")
    chk("M2 shows 'vs Sitra'", "vs Sitra" in html)

    print("\n=== M3: is_home TRUE → opponent is away team ===")
    chk("M3 shows 'vs Manama' (opponent)", "vs Manama" in html)
    chk("M3 does NOT show own team 'Hidd vs'", "Hidd vs Manama" not in html)

    print("\n=== M4: is_home FALSE → opponent is home team ===")
    chk("M4 shows 'vs Budaiya' (opponent)", "vs Budaiya" in html)
    chk("M4 does NOT show 'Budaiya vs Najma'", "Budaiya vs Najma" not in html)

    print("\n=== M5: no teams → graceful (date only, row renders) ===")
    chk("M5 row still renders (sentinel competition present)",
        "NOOPPCOMP" in html)
    chk("M5 produced no stray 'vs ' for the empty match",
        "vs None" not in html and "vs  vs" not in html)

    print("\n=== Consistency: opponent text matches the DB record ===")
    with db() as conn, conn.cursor() as cur:
        cur.execute("""SELECT home_team, away_team FROM wyscout_match_stats
                       WHERE player_id=%s AND match_label LIKE 'M1%%'""", (pid,))
        r = cur.fetchone()
    chk("opponent on page matches record (home+away)",
        f"{r['home_team']} vs {r['away_team']}" in html,
        f"{r['home_team']} vs {r['away_team']}")

finally:
    print("\n(cleanup)")
    cleanup()
    print("  done")

print("\n" + "=" * 60)
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"Recent-matches-opponent E2E summary: {n_pass} pass / {n_fail} fail (of {len(results)})")
sys.exit(0 if n_fail == 0 else 2)
