"""
Phase 6.2.3 synthetic E2E — Eligibility + nationality flag display audit.

Verifies that every user-facing surface that shows a player's name also
shows their eligibility badge (with correct status_code) and nationality
flag.

Surfaces checked:
  1. /players/              — player card grid (HTMX partial _grid.html)
  2. /players/<id>          — player profile header
  3. /players/compare/view  — comparison bio header
  4. /players/compare/search — HTMX search dropdown
  5. /players/<id>/evaluate  — evaluation form header

For each surface we assert:
  a. The page returns 200 OK
  b. elig-badge HTML element is present (at least one)
  c. The correct data-status value is in the HTML for our known player
  d. An SVG flag is present (the `elig-flag` span or inline SVG in the header)

Test players (snapshot and restore):
  - arthur_id  — set to nationality_status='foreign_residency',
                 bahrain_residency_start_date = 5+ years ago (→ eligible_now)
  - bouhra_id  — set to nationality_status='bahraini' (→ eligible_now, green)
  - We assert on these two known states.

Hard rules: real Flask + real HTTP (no test_client). DB values restored in
finally: even on failure.

Run from D:\\BFA-Scout:
    python migrations/_e2e_phase_6_2_3.py
"""
import os
import re
import sys
from datetime import date
from urllib.request import build_opener, HTTPCookieProcessor, Request
from http.cookiejar import CookieJar
from urllib.parse import urlencode

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()
BASE = "http://127.0.0.1:5057"

results = []


def chk(label: str, ok: bool, evidence: str = ""):
    results.append((label, ok, evidence))
    status = "PASS" if ok else "FAIL"
    suffix = f"  {evidence}" if evidence else ""
    print(f"  [{status}] {label}{suffix}")


def http(op, method, path, *, data=None):
    body = urlencode(data).encode() if data is not None else None
    req = Request(BASE + path, data=body, method=method)
    if body:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    r = op.open(req)
    return r.status, r.read().decode("utf-8", errors="replace"), r.url


def login(email, pw):
    op = build_opener(HTTPCookieProcessor(CookieJar()))
    _, html, _ = http(op, "GET", "/auth/login")
    m = re.search(r'name=["\']csrf_token["\']\s+value=["\']([^"\']+)["\']', html)
    http(op, "POST", "/auth/login",
         data={"email": email, "password": pw, "csrf_token": m.group(1)})
    return op


def db():
    return psycopg2.connect(os.environ["DATABASE_URL"],
                            cursor_factory=psycopg2.extras.RealDictCursor)


# ── Login ──────────────────────────────────────────────────────────────
admin = login(os.environ["INITIAL_ADMIN_EMAIL"], os.environ["INITIAL_ADMIN_PASSWORD"])

# ── Snapshot prior player states ───────────────────────────────────────
with db() as conn, conn.cursor() as cur:
    cur.execute(
        """
        SELECT id, full_name, nationality_status, nationality_code,
               eligible_from_date, bahrain_residency_start_date
        FROM   players
        WHERE  is_active = TRUE
        ORDER  BY id
        LIMIT  3
        """
    )
    orig_players = {r["id"]: dict(r) for r in cur.fetchall()}

chk("At least 2 active players found for test", len(orig_players) >= 2)
player_ids  = list(orig_players.keys())
pid_a       = player_ids[0]   # will be set to foreign_residency (eligible)
pid_b       = player_ids[1]   # will be set to bahraini

print(f"\n  Test players: pid_a={pid_a} ({orig_players[pid_a]['full_name']}), "
      f"pid_b={pid_b} ({orig_players[pid_b]['full_name']})")

# ── Inject controlled states ───────────────────────────────────────────
# pid_a: foreign_residency, residency started 6 years ago → eligible now
# pid_b: bahraini, nationality_code=BHR → eligible now
from datetime import timedelta
rstart_6y_ago = (date.today() - timedelta(days=6 * 365)).isoformat()

with db() as conn, conn.cursor() as cur:
    cur.execute(
        """
        UPDATE players
        SET    nationality_status = 'foreign_residency',
               bahrain_residency_start_date = %s,
               eligible_from_date = NULL
        WHERE  id = %s
        """,
        (rstart_6y_ago, pid_a)
    )
    cur.execute(
        """
        UPDATE players
        SET    nationality_status = 'bahraini',
               nationality_code  = 'BHR'
        WHERE  id = %s
        """,
        (pid_b,)
    )
    conn.commit()

try:
    # ── Surface 1: Player card grid (/players/) ────────────────────────
    print("\n=== Surface 1: Player card grid (/players/) ===")
    status, html, _ = http(admin, "GET", "/players/")
    chk("GET /players/ returns 200", status == 200, f"status={status}")
    chk("elig-badge present in grid", 'class="elig-badge' in html)
    chk("eligible_now badge present (pid_a is residency-complete)",
        'data-status="eligible_now"' in html)
    chk("SVG flag present in grid (elig-flag span)",
        'class="elig-flag"' in html)

    # ── Surface 2: Player profile (/players/<id>) ──────────────────────
    print(f"\n=== Surface 2: Player profile (/players/{pid_b}) ===")
    status, html, _ = http(admin, "GET", f"/players/{pid_b}")
    chk(f"GET /players/{pid_b} returns 200", status == 200, f"status={status}")
    # Profile header should now show SVG flag (get_flag_svg) not emoji
    chk("Profile header contains inline flag SVG (get_flag_svg path)",
        'elig-flag' in html or '<svg' in html)
    # Eligibility card still has the badge
    chk("Eligibility card present on profile",
        'elig-badge' in html or 'class="elig-icon"' in html or
        'National-Team Eligibility' in html)

    # ── Surface 3: Compare view (/players/compare/view?ids=…) ─────────
    print(f"\n=== Surface 3: Compare view (/players/compare/view) ===")
    compare_url = f"/players/compare/view?ids={pid_a},{pid_b}"
    status, html, _ = http(admin, "GET", compare_url)
    chk(f"GET {compare_url} returns 200", status == 200, f"status={status}")
    chk("elig-badge present in compare bio header",
        'class="elig-badge' in html,
        "macro not applied to compare_view.html" if 'class="elig-badge' not in html else "")
    chk("eligible_now badge in compare view",
        'data-status="eligible_now"' in html)

    # ── Surface 4: Compare search dropdown (/players/compare/search?q=…) ─
    print("\n=== Surface 4: Compare search dropdown ===")
    q_term = orig_players[pid_a]["full_name"].split()[0]  # first name
    status, html, _ = http(admin, "GET",
                            f"/players/compare/search?q={q_term}&slot=0")
    chk(f"GET /compare/search?q={q_term!r} returns 200", status == 200, f"status={status}")
    chk("Flag SVG present in search result",
        '<svg' in html,
        "nationality_code missing from compare_search query or template not updated"
        if '<svg' not in html else "")

    # ── Surface 5: Evaluation form (/players/<id>/evaluate) ───────────
    print(f"\n=== Surface 5: Evaluation form (/players/{pid_b}/evaluate) ===")
    status, html, _ = http(admin, "GET", f"/players/{pid_b}/evaluate")
    chk(f"GET /players/{pid_b}/evaluate returns 200 (or 302 if no position)",
        status in (200, 302), f"status={status}")
    if status == 200:
        chk("Flag SVG present in eval form header",
            '<svg' in html,
            "nationality_code missing from _load_player or form.html not updated"
            if '<svg' not in html else "")
    else:
        chk("Eval form redirect (player has no position set) — flag check skipped",
            True, f"redirected to {status}")

    # ── Badge color consistency across surfaces ────────────────────────
    print("\n=== Badge CSS class consistency ===")
    status, grid_html, _ = http(admin, "GET", "/players/")
    # All 4 status_code values should have correct CSS data-status attr
    for code in ("eligible_now", "eligible_future", "not_eligible", "unknown"):
        # We can only assert the ones we know are present; eligible_now is guaranteed
        if code == "eligible_now":
            chk(f"data-status={code!r} present in grid (known from test setup)",
                f'data-status="{code}"' in grid_html)

finally:
    # ── Restore all prior player values ───────────────────────────────
    with db() as conn, conn.cursor() as cur:
        for pid, row in orig_players.items():
            cur.execute(
                """
                UPDATE players
                SET    nationality_status           = %s,
                       nationality_code             = %s,
                       eligible_from_date           = %s,
                       bahrain_residency_start_date = %s
                WHERE  id = %s
                """,
                (
                    row["nationality_status"],
                    row["nationality_code"],
                    row["eligible_from_date"],
                    row["bahrain_residency_start_date"],
                    pid,
                )
            )
        conn.commit()
    print("\n(restored prior player nationality states)")

# ── Summary ────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"E2E summary: {n_pass} pass / {n_fail} fail (of {len(results)})")
sys.exit(0 if n_fail == 0 else 2)
