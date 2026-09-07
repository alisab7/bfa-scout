"""
E2E — /players eligibility-YEAR bucket filter (?elig_year=).

Real Flask + real HTTP (NOT flask.test_client). Server on 127.0.0.1:5057.

The bar groups the CURRENT result set into the fixed buckets
    Eligible now | 2026 | 2027 | 2028 | More than 2028 | Date not set
using `eligibility_year_bucket` (app/players/eligibility.py), which reads the
value the eligibility ENGINE already produced for the badge
(`compute_eligibility_status` + `_resolve_eligibility_date`). No new column,
no second date calculation — so a chip and the badge on the card can never
disagree.

This suite SEEDS EVERY FIXTURE IT ASSERTS ON (players AND a club) and drops
them in `finally:` — it never SELECTs ambient DB rows.

  Y1  ?elig_year=2028   → exactly the seeded 2028 players
  Y2  ?elig_year=later  → only the 2029+ player
  Y3  ?elig_year=now    → only the already-eligible player
  Y4  ?elig_year=unset  → only the no-resolvable-date players
  Y5  buttons render only for NON-EMPTY buckets, in the fixed order
  Y6  an empty bucket has NO button at all (scoped by the seeded club)
  Y7  composition: ?elig_year=2028&club=<seeded club> → the intersection
  Y8  active state + clear/reset link
  Y9  badge consistency: every returned card's bucket agrees with its badge
  Y10 mover: add residency start + origin_country → moves unset → 2027
  Y11 an unknown ?elig_year= value is ignored (no silent empty list)
  Y12 the HTMX partial carries the bar as an hx-swap-oob fragment
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
from dotenv import load_dotenv

sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent))
load_dotenv()
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = "http://127.0.0.1:5057"
PREFIX = "E2E-EYEAR"
CLUB_NAME = f"{PREFIX} United"

# Canonical bar order — must match ELIG_YEAR_BUCKETS in app/players/eligibility.py
ORDER = ["now", "2026", "2027", "2028", "later", "unset"]


def http(op, method, path, *, data=None):
    body = urlencode(data, doseq=True).encode() if data is not None else None
    req = Request(BASE + path, data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        r = op.open(req)
        return r.status, r.read().decode("utf-8", "replace"), r.url
    except HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), e.url


def csrf_of(html):
    m = re.search(r'name=["\']csrf_token["\']\s+value=["\']([^"\']+)["\']', html)
    return m.group(1) if m else None


admin_jar = CookieJar()


def login(email, pw):
    op = build_opener(HTTPCookieProcessor(admin_jar))
    _, html, _ = http(op, "GET", "/auth/login")
    http(op, "POST", "/auth/login",
         data={"email": email, "password": pw, "csrf_token": csrf_of(html)})
    return op


def db():
    return psycopg2.connect(os.environ["DATABASE_URL"],
                            cursor_factory=psycopg2.extras.RealDictCursor)


# ─── HTML helpers ────────────────────────────────────────────────────────────

def bar_of(html):
    """The <div id="elig-year-bar"> … </div> block."""
    i = html.find('id="elig-year-bar"')
    if i < 0:
        return ""
    start = html.rfind("<div", 0, i)
    end = html.find('id="player-grid"', i)
    if end < 0:
        end = len(html)
    return html[start:end] if start >= 0 else ""


def chips(html):
    """[(bucket_key, active_flag, count)] in DOCUMENT order."""
    bar = bar_of(html)
    out = []
    for m in re.finditer(
        r'data-elig-year="([^"]+)"\s+data-active="([01])"(.*?)</a>', bar, re.S
    ):
        cnt = re.search(r"\((\d+)\)", m.group(3))
        out.append((m.group(1), m.group(2) == "1", int(cnt.group(1)) if cnt else None))
    return out


def cards(html):
    """{player_name: card_html} for every seeded player present on the page."""
    out = {}
    for m in re.finditer(r'<a href="/players/\d+"[^>]*class="player-card".*?</a>',
                         html, re.S):
        block = m.group(0)
        nm = re.search(rf"({re.escape(PREFIX)}-[A-Za-z0-9]+)", block)
        if nm:
            out[nm.group(1)] = block
    return out


def badge_status(card_html):
    m = re.search(r'class="elig-badge[^"]*"\s+data-status="([^"]+)"', card_html)
    return m.group(1) if m else None


results = []


def chk(label, ok, ev=""):
    results.append((label, ok, ev))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}  {ev}")


# ─── Fixture dates ───────────────────────────────────────────────────────────
today = date.today()
D_NOW = today - timedelta(days=365 * 6)      # residency start 6y ago → +5y past
D_2026 = date(2026, 12, 31)
D_2027 = date(2027, 6, 15)
D_2028 = date(2028, 3, 10)
D_2029 = date(2029, 5, 20)
MOVER_RESIDENCY = date(2022, 6, 15)          # +5y = 2027-06-15 → bucket 2027

P_NOW = f"{PREFIX}-Now"
P_2026 = f"{PREFIX}-Y2026"
P_2027 = f"{PREFIX}-Y2027"
P_2028A = f"{PREFIX}-Y2028a"                  # in the seeded club
P_2028B = f"{PREFIX}-Y2028b"                  # NOT in the seeded club
P_LATER = f"{PREFIX}-Later"
P_UNSET = f"{PREFIX}-Unset"                   # foreign_residency, no dates
P_CITIZ = f"{PREFIX}-BornCitizen"             # bahraini, origin NULL
P_MOVER = f"{PREFIX}-Mover"                   # starts unset, gains a countdown

EXPECTED = {
    P_NOW: "now",
    P_2026: "2026",
    P_2027: "2027",
    P_2028A: "2028",
    P_2028B: "2028",
    P_LATER: "later",
    P_UNSET: "unset",
    P_CITIZ: "unset",
    P_MOVER: "unset",
}
BADGE_FOR_BUCKET = {
    "now": {"eligible_now"},
    "2026": {"eligible_future"},
    "2027": {"eligible_future"},
    "2028": {"eligible_future"},
    "later": {"eligible_future"},
    "unset": {"citizen", "unknown", "not_eligible"},
}

ids = {}
club_id = None


def cleanup():
    with db() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM players WHERE full_name LIKE %s", (f"{PREFIX}-%",))
        cur.execute("DELETE FROM clubs   WHERE name      LIKE %s", (f"{PREFIX}%",))
        conn.commit()


print("=== Setup ===")
if D_2026 <= today:
    print(f"  !! today={today} is past the 2026 fixture date {D_2026}; "
          f"the 2026 bucket assertions no longer make sense. Update D_2026.")
    sys.exit(2)

cleanup()
with db() as conn, conn.cursor() as cur:
    cur.execute("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1")
    admin_id = cur.fetchone()["id"]

    cur.execute(
        "INSERT INTO clubs (name, division, is_active) VALUES (%s,'premier',TRUE) "
        "RETURNING id", (CLUB_NAME,))
    club_id = cur.fetchone()["id"]

    seq = [0]

    def mk(name, status, *, origin=None, resi=None, efrom=None, in_club=False):
        seq[0] += 1
        cur.execute(
            """INSERT INTO players
                 (full_name, national_id, age_group, nationality_status,
                  nationality_code, origin_country, origin_country_code,
                  bahrain_residency_start_date, eligible_from_date,
                  club_id, is_active, created_by)
               VALUES (%s,%s,'senior',%s,%s,%s,%s,%s,%s,%s,TRUE,%s)
               RETURNING id""",
            (name, f"EY{seq[0]:08d}", status,
             "BHR" if status == "bahraini" else "BRA",
             origin, ("BRA" if origin else None),
             resi, efrom, club_id if in_club else None, admin_id))
        return cur.fetchone()["id"]

    # 'now' — residency route completed (NOT an explicit date): the counting
    # path the spec calls out.
    ids[P_NOW] = mk(P_NOW, "foreign_residency", resi=D_NOW, in_club=True)
    ids[P_2026] = mk(P_2026, "foreign_residency", efrom=D_2026)
    ids[P_2027] = mk(P_2027, "foreign_residency", efrom=D_2027)
    ids[P_2028A] = mk(P_2028A, "foreign_residency", efrom=D_2028, in_club=True)
    ids[P_2028B] = mk(P_2028B, "foreign_residency", efrom=D_2028)
    ids[P_LATER] = mk(P_LATER, "foreign_residency", efrom=D_2029, in_club=True)
    # no resolvable date at all
    ids[P_UNSET] = mk(P_UNSET, "foreign_residency")
    # born citizen: is_eligible_now=True but NO date → spec puts it in 'unset'
    ids[P_CITIZ] = mk(P_CITIZ, "bahraini")
    ids[P_MOVER] = mk(P_MOVER, "bahraini")
    conn.commit()
print(f"  club={club_id} players={len(ids)}")


try:
    admin = login(os.environ["INITIAL_ADMIN_EMAIL"],
                  os.environ["INITIAL_ADMIN_PASSWORD"])
    st, full, _ = http(admin, "GET", "/players/")
    chk("S0 /players renders 200", st == 200, f"status={st}")
    seen = cards(full)
    chk("S1 all 9 seeded players visible unfiltered",
        len(seen) == 9, f"seen={sorted(seen)}")

    print("\n=== Y1: ?elig_year=2028 → exactly the 2028 players ===")
    _, h, _ = http(admin, "GET", "/players/?elig_year=2028")
    got = set(cards(h))
    chk("Y1 exactly {2028a, 2028b}", got == {P_2028A, P_2028B}, f"got={sorted(got)}")

    print("\n=== Y2: ?elig_year=later → only 2029+ ===")
    _, h, _ = http(admin, "GET", "/players/?elig_year=later")
    got = set(cards(h))
    chk("Y2 exactly {Later}", got == {P_LATER}, f"got={sorted(got)}")

    print("\n=== Y3: ?elig_year=now → only already-eligible ===")
    _, h, _ = http(admin, "GET", "/players/?elig_year=now")
    got = set(cards(h))
    chk("Y3 exactly {Now}", got == {P_NOW}, f"got={sorted(got)}")
    chk("Y3b born citizen NOT in 'now' (spec: born citizens are 'Date not set')",
        P_CITIZ not in got)

    print("\n=== Y4: ?elig_year=unset → only no-resolvable-date players ===")
    _, h, _ = http(admin, "GET", "/players/?elig_year=unset")
    got = set(cards(h))
    chk("Y4 exactly {Unset, BornCitizen, Mover}",
        got == {P_UNSET, P_CITIZ, P_MOVER}, f"got={sorted(got)}")

    print("\n=== Y5: 2027 bucket + fixed button order ===")
    _, h, _ = http(admin, "GET", "/players/?elig_year=2027")
    got = set(cards(h))
    chk("Y5a exactly {Y2027}", got == {P_2027}, f"got={sorted(got)}")
    keys = [k for k, _, _ in chips(full)]
    chk("Y5b buttons appear in the fixed canonical order",
        keys == [k for k in ORDER if k in keys], f"keys={keys}")
    chk("Y5c every seeded bucket has a button",
        set(EXPECTED.values()) <= set(keys), f"keys={keys}")

    print("\n=== Y6: empty buckets render NO button (scoped by seeded club) ===")
    _, hc, _ = http(admin, "GET", f"/players/?club={club_id}")
    ck = [k for k, _, _ in chips(hc)]
    chk("Y6a club scope shows only now/2028/later buttons",
        ck == ["now", "2028", "later"], f"keys={ck}")
    chk("Y6b NO 2026 button", 'data-elig-year="2026"' not in bar_of(hc))
    chk("Y6c NO 2027 button", 'data-elig-year="2027"' not in bar_of(hc))
    chk("Y6d NO unset button", 'data-elig-year="unset"' not in bar_of(hc))
    counts = {k: c for k, _, c in chips(hc)}
    chk("Y6e counts reflect the club-filtered set",
        counts == {"now": 1, "2028": 1, "later": 1}, f"counts={counts}")

    print("\n=== Y7: composition ?elig_year=2028&club=<club> → intersection ===")
    _, h, _ = http(admin, "GET", f"/players/?elig_year=2028&club={club_id}")
    got = set(cards(h))
    chk("Y7a exactly {Y2028a} (2028b is club-less)",
        got == {P_2028A}, f"got={sorted(got)}")
    _, h2, _ = http(admin, "GET", f"/players/?elig_year=2028&club=other")
    got2 = set(cards(h2))
    chk("Y7b club=other + 2028 → {Y2028b}", P_2028B in got2 and P_2028A not in got2,
        f"got={sorted(got2)}")
    _, h3, _ = http(admin, "GET", f"/players/?elig_year=now&elig=eligible_now")
    chk("Y7c composes with the existing elig= filter", P_NOW in cards(h3))
    _, h4, _ = http(admin, "GET", f"/players/?elig_year=2028&q={P_2028A}")
    chk("Y7d composes with the search box",
        set(cards(h4)) == {P_2028A}, f"got={sorted(cards(h4))}")

    print("\n=== Y8: active state + clear/reset ===")
    _, h, _ = http(admin, "GET", "/players/?elig_year=2028")
    active = [(k, a) for k, a, _ in chips(h)]
    chk("Y8a only the 2028 chip is active",
        [k for k, a in active if a] == ["2028"], f"{active}")
    chk("Y8b clear link present when filtered",
        'data-elig-year-clear="1"' in bar_of(h))
    chk("Y8c clear link drops elig_year",
        "elig_year" not in re.search(
            r'href="([^"]*)"[^>]*data-elig-year-clear', bar_of(h)).group(1))
    chk("Y8d no clear link when unfiltered",
        'data-elig-year-clear="1"' not in bar_of(full))
    chk("Y8e chip href carries the other active filters",
        f"club={club_id}" in re.search(
            r'href="([^"]*)"\s+data-elig-year="2028"', bar_of(hc)).group(1))

    print("\n=== Y9: badge consistency — bucket agrees with the row badge ===")
    bad = []
    for key in ORDER:
        _, hb, _ = http(admin, "GET", f"/players/?elig_year={key}")
        for name, card in cards(hb).items():
            st_code = badge_status(card)
            if st_code not in BADGE_FOR_BUCKET[key]:
                bad.append((name, key, st_code))
    chk("Y9 every card's badge matches its bucket", not bad, f"mismatches={bad}")

    print("\n=== Y10: mover gains a countdown → unset ⟶ 2027 ===")
    _, hu, _ = http(admin, "GET", "/players/?elig_year=unset")
    chk("Y10a mover starts in 'unset'", P_MOVER in cards(hu))
    with db() as conn, conn.cursor() as cur:
        cur.execute("""UPDATE players
                          SET origin_country = 'Brazil',
                              origin_country_code = 'BRA',
                              bahrain_residency_start_date = %s
                        WHERE id = %s""", (MOVER_RESIDENCY, ids[P_MOVER]))
        conn.commit()
    _, h27, _ = http(admin, "GET", "/players/?elig_year=2027")
    chk("Y10b mover now in the 2027 bucket", P_MOVER in cards(h27))
    _, hu2, _ = http(admin, "GET", "/players/?elig_year=unset")
    chk("Y10c mover no longer in 'unset'", P_MOVER not in cards(hu2))
    chk("Y10d mover's badge is now a future countdown",
        badge_status(cards(h27).get(P_MOVER, "")) == "eligible_future",
        f"status={badge_status(cards(h27).get(P_MOVER, ''))}")

    print("\n=== Y11: unknown ?elig_year= is ignored ===")
    _, hz, _ = http(admin, "GET", "/players/?elig_year=banana")
    chk("Y11 bogus value falls back to unfiltered", len(cards(hz)) == 9,
        f"n={len(cards(hz))}")

    print("\n=== Y12: HTMX partial ships the bar out-of-band ===")
    hx = build_opener(HTTPCookieProcessor(admin_jar))
    req = Request(BASE + f"/players/?elig_year=2028&club={club_id}", method="GET")
    req.add_header("HX-Request", "true")
    hx_html = hx.open(req).read().decode("utf-8", "replace")
    chk("Y12a HTMX response filters the grid too",
        set(cards(hx_html)) == {P_2028A}, f"got={sorted(cards(hx_html))}")
    chk("Y12b HTMX response carries the bar as an OOB swap",
        'id="elig-year-bar"' in hx_html and 'hx-swap-oob="true"' in hx_html)
    chk("Y12c OOB bar keeps only the club's non-empty buckets",
        [k for k, _, _ in chips(hx_html)] == ["now", "2028", "later"],
        f"keys={[k for k, _, _ in chips(hx_html)]}")
    chk("Y12d HTMX response is a partial (no full page chrome)",
        "<html" not in hx_html.lower())

finally:
    print("\n(cleanup)")
    cleanup()
    print("  done")

print("\n" + "=" * 60)
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"Eligibility-year bucket E2E summary: {n_pass} pass / {n_fail} fail "
      f"(of {len(results)})")
sys.exit(0 if n_fail == 0 else 2)
