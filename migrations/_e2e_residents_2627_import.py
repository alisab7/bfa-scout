"""
E2E — 26/27 residents import (Report.xlsx -> Phase-9 bulk importer).

Real Flask + real HTTP (NOT flask.test_client). Server on 127.0.0.1:5057.
Drives the REAL import path: /admin/players/bulk-import upload ->
preview -> commit, using exports/residents_2627_import.csv produced by
scripts/transform_report_residents.py (88 kept rows — the 24 whole-row
highlighted players are excluded by the transform, cross-checked
against the ratified 24-BFA-ID list).

Cases:
  A  dup-safety: seed a player holding one of the file's BFA IDs, run
     the import, verify that row is SKIPPED (default action) and the
     seeded player's data is NEVER overwritten
  B  reset players table (final state is rebuilt from scratch)
  C  REAL import: commit all 88; verify names/BFA IDs/DOBs/club_id
     (0 unmapped), 44 bahraini / 44 foreign_residency, ALL 24 excluded
     BFA IDs absent, origin NULL, residency date NULL, position NULL,
     notes carry the labelled interim Years estimate
  D  idempotency: re-upload the same CSV -> everything classified
     duplicate -> commit (default skip) -> 0 created, still 88 rows
  E  eligibility surfaces: profile of a no-date foreign_residency
     player renders "Pending — residency start not set"; passport
     holder (origin pending) renders Citizen; /nt/residents renders
     "date not set" — all real HTTP, no crashes
  F  gap-list CSV: 88 rows, all need entry date, exactly 44 need
     origin, 1 blank-nationality flag, 4 missing-BFA-ID, 2 missing-DOB,
     0 withdrawn (the 4 withdrawn rows are inside the excluded 24)
  G  relabel: the player new/edit forms, profile, /admin/assign-clubs
     table header, the youth intake form and the passport PDF all
     render "National / BFA ID" (display only; column name unchanged).
     The assign-clubs header needs a club-less player to render, so the
     case seeds one throwaway row and deletes it in a finally: block —
     the DB still ends on exactly the 88.

Leaves the LOCAL dev DB in the delivered state: the 88 imported
players (this is the point of the run — Ali reviews it before prod).
"""
from __future__ import annotations

import csv
import os
import re
import sys
import uuid
from pathlib import Path
from urllib.request import build_opener, HTTPCookieProcessor, Request
from urllib.error import HTTPError
from http.cookiejar import CookieJar
from urllib.parse import urlencode, urlparse

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = "http://127.0.0.1:5057"
REPO = Path(__file__).resolve().parent.parent
IMPORT_CSV = REPO / "exports" / "residents_2627_import.csv"
GAP_CSV = REPO / "exports" / "residents_2627_gap_list.csv"

SEED_BFA_ID = "008287M97"          # HAMZA BUIHAMGHET's ID in the file

# The ratified 24 excluded BFA IDs (whole-row yellow/red in the source).
# NONE of these may exist in the DB after the import.
EXCLUDED_IDS = [
    "008286M06", "008337M03", "008965M05", "009002M05", "003300M01",
    "000999M90", "002860M96", "007377M00", "008065M01", "003457M92",
    "007361M05", "007340M05", "008840M05", "008853M01", "009199M06",
    "009383M06", "007387M96", "007394M96", "008083M92", "008134M02",
    "008338M04", "000090M01", "005641M00", "005835M04",
]


# ───────── HTTP helpers (same conventions as _e2e_phase_9.py) ──────────

def _build_multipart(fields):
    boundary = f"----E2E{uuid.uuid4().hex}"
    lines = []
    for name, val in fields.items():
        if isinstance(val, tuple) and len(val) == 3:
            filename, file_bytes, ctype = val
            lines.append(f"--{boundary}".encode())
            lines.append(
                f'Content-Disposition: form-data; name="{name}"; '
                f'filename="{filename}"'.encode())
            lines.append(f"Content-Type: {ctype}".encode())
            lines.append(b"")
            lines.append(file_bytes if isinstance(file_bytes, bytes)
                         else file_bytes.encode())
        else:
            lines.append(f"--{boundary}".encode())
            lines.append(
                f'Content-Disposition: form-data; name="{name}"'.encode())
            lines.append(b"")
            lines.append(str(val).encode())
    lines.append(f"--{boundary}--".encode())
    lines.append(b"")
    return b"\r\n".join(lines), f"multipart/form-data; boundary={boundary}"


def http(op, method, path, *, data=None, multipart=None):
    if multipart is not None:
        body, ctype = _build_multipart(multipart)
    elif data is not None:
        body, ctype = urlencode(data).encode(), \
            "application/x-www-form-urlencoded"
    else:
        body, ctype = None, None
    req = Request(BASE + path, data=body, method=method)
    if ctype:
        req.add_header("Content-Type", ctype)
    try:
        r = op.open(req)
        return r.status, r.read().decode("utf-8", errors="replace"), r.url
    except HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace"), None


def csrf_from_html(html):
    m = re.search(
        r'name=["\']csrf_token["\']\s+value=["\']([^"\']+)["\']', html)
    return m.group(1) if m else None


def login(email, pw):
    op = build_opener(HTTPCookieProcessor(CookieJar()))
    _, html, _ = http(op, "GET", "/auth/login")
    http(op, "POST", "/auth/login",
         data={"email": email, "password": pw,
               "csrf_token": csrf_from_html(html)})
    return op


def _assert_local_db(dsn: str) -> None:
    """Refuse to run anywhere but a local dev database.

    This suite rebuilds from a clean slate: it runs `DELETE FROM players`,
    and players cascade to evaluations, ai_artifacts, youth_shortlist and
    wyscout_match_stats. Against production that is an unrecoverable data
    loss, so the host is checked before any connection is opened. It has
    already wiped a local table once when its input CSV was missing.
    """
    host = (urlparse(dsn).hostname or "").lower()
    if host not in ("", "localhost", "127.0.0.1", "::1"):
        sys.exit(
            f"REFUSING TO RUN: DATABASE_URL points at '{host}', not a local "
            "database.\nThis suite DELETEs every row in `players` (cascading "
            "to evaluations) before reimporting.\nIt is a local-dev harness "
            "only. To import on production, upload the CSV through "
            "/admin/players/bulk-import and review the preview."
        )


def db():
    dsn = os.environ["DATABASE_URL"]
    _assert_local_db(dsn)
    return psycopg2.connect(dsn,
                            cursor_factory=psycopg2.extras.RealDictCursor)


results = []


def chk(label, ok, ev=""):
    results.append((label, ok, ev))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}  {ev}")


def run_import(op) -> tuple[str, str]:
    """Upload the CSV, hit preview, commit with DEFAULT actions (all
    duplicates skipped). Returns (preview_html, result_html)."""
    _, idx_html, _ = http(op, "GET", "/admin/players/bulk-import")
    token = csrf_from_html(idx_html)
    st, _, url = http(op, "POST", "/admin/players/bulk-import/upload",
                      multipart={
                          "csrf_token": token,
                          "file": ("residents_2627_import.csv",
                                   IMPORT_CSV.read_bytes(), "text/csv"),
                      })
    assert url and url.endswith("/preview"), f"upload failed: {st} {url}"
    _, preview_html, _ = http(op, "GET", "/admin/players/bulk-import/preview")
    token = csrf_from_html(preview_html)
    st, result_html, url = http(op, "POST",
                                "/admin/players/bulk-import/commit",
                                data={"csrf_token": token})
    assert url and url.endswith("/result"), \
        f"commit did not reach result page: {st} {url}"
    return preview_html, result_html


def main():
    admin = login(os.environ["INITIAL_ADMIN_EMAIL"],
                  os.environ["INITIAL_ADMIN_PASSWORD"])

    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM players")
        n0 = cur.fetchone()["n"]
    print(f"players before run: {n0}")

    # ── Case A: dup-safety — seeded BFA ID is skipped, never overwritten
    print("\n=== Case A: seeded duplicate is skipped, not overwritten ===")
    with db() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM players")          # clean slate for the seed
        cur.execute(
            """
            INSERT INTO players (full_name, national_id, dob, notes,
                                 is_active)
            VALUES ('SEEDED DUP-TEST PLAYER', %s, '1990-01-01',
                    'seed-original-notes', TRUE)
            RETURNING id
            """, (SEED_BFA_ID,))
        seed_id = cur.fetchone()["id"]
        conn.commit()

    preview_html, result_html = run_import(admin)
    chk("A1 preview flags the seeded BFA ID as duplicate",
        "duplicate" in preview_html.lower())
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM players")
        n_after_a = cur.fetchone()["n"]
        cur.execute("SELECT full_name, dob, notes, nationality_status, "
                    "club_id FROM players WHERE id = %s", (seed_id,))
        seeded = cur.fetchone()
    chk("A2 commit created 87 (88 file rows - 1 skipped duplicate)",
        n_after_a == 88, f"total now {n_after_a} (incl. seed)")
    chk("A3 seeded player NOT overwritten (name intact)",
        seeded["full_name"] == "SEEDED DUP-TEST PLAYER", str(seeded))
    chk("A4 seeded player notes/dob/status untouched",
        seeded["notes"] == "seed-original-notes"
        and str(seeded["dob"]) == "1990-01-01"
        and seeded["nationality_status"] is None
        and seeded["club_id"] is None)

    # ── Case B: reset to empty for the real import ─────────────────────
    print("\n=== Case B: reset players table ===")
    with db() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM players")
        conn.commit()
        cur.execute("SELECT COUNT(*) AS n FROM players")
        chk("B1 players table reset to 0", cur.fetchone()["n"] == 0)

    # ── Case C: the REAL import ────────────────────────────────────────
    print("\n=== Case C: real import of the 88 kept players ===")
    preview_html, result_html = run_import(admin)
    chk("C0 preview rendered before commit (contains row count)",
        "88" in preview_html)

    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM players")
        chk("C1 88 players imported", cur.fetchone()["n"] == 88)

        cur.execute("""
            SELECT nationality_status, COUNT(*) AS n FROM players
            GROUP BY nationality_status ORDER BY nationality_status
        """)
        split = {r["nationality_status"]: r["n"] for r in cur.fetchall()}
        chk("C2 status split 44 bahraini / 44 foreign_residency",
            split == {"bahraini": 44, "foreign_residency": 44}, str(split))

        cur.execute("SELECT COUNT(*) AS n FROM players "
                    "WHERE national_id = ANY(%s)", (EXCLUDED_IDS,))
        chk("C2x ALL 24 excluded BFA IDs ABSENT from the DB",
            cur.fetchone()["n"] == 0)

        cur.execute("SELECT COUNT(*) AS n FROM players "
                    "WHERE origin_country IS NOT NULL")
        chk("C3 origin_country NULL for all", cur.fetchone()["n"] == 0)
        cur.execute("SELECT COUNT(*) AS n FROM players "
                    "WHERE bahrain_residency_start_date IS NOT NULL")
        chk("C4 residency start date NULL for all (no invented dates)",
            cur.fetchone()["n"] == 0)
        cur.execute("SELECT COUNT(*) AS n FROM players "
                    "WHERE primary_position_id IS NOT NULL")
        chk("C5 position NULL for all (assign later)",
            cur.fetchone()["n"] == 0)
        cur.execute("SELECT COUNT(*) AS n FROM players "
                    "WHERE secondary_position_id IS NOT NULL")
        chk("C5b secondary position NULL for all",
            cur.fetchone()["n"] == 0)

        cur.execute("SELECT COUNT(*) AS n FROM players WHERE club_id IS NULL")
        chk("C6 club_id resolved for ALL rows (0 unmapped)",
            cur.fetchone()["n"] == 0)
        cur.execute("""
            SELECT COUNT(*) AS n FROM players p
            JOIN clubs c ON c.id = p.club_id
            WHERE p.current_club = c.name
        """)
        chk("C7 current_club matches clubs.name for all 88",
            cur.fetchone()["n"] == 88)

        cur.execute("SELECT COUNT(*) AS n FROM players "
                    "WHERE national_id IS NOT NULL")
        chk("C8 84 rows carry a BFA ID (4 'New' rows blank, not faked)",
            cur.fetchone()["n"] == 84)
        cur.execute("SELECT COUNT(*) AS n FROM players WHERE dob IS NULL")
        chk("C9 exactly 2 blank DOBs kept blank", cur.fetchone()["n"] == 2)

        cur.execute("""
            SELECT full_name, dob, nationality_status, current_club
            FROM players WHERE national_id = '007362M99'
        """)
        r = cur.fetchone()
        chk("C10 spot-check EAMON HATOUM (007362M99)",
            r is not None and r["full_name"] == "EAMON HATOUM"
            and str(r["dob"]) == "1999-02-03"
            and r["nationality_status"] == "foreign_residency"
            and r["current_club"] == "Al-Ahli Manama", str(r))

        cur.execute("""
            SELECT full_name, dob FROM players WHERE national_id = '003336M01'
        """)
        r = cur.fetchone()
        chk("C11 spot-check string-DOB row FRANCK KONY NSANGET 15/01/2001",
            r is not None and str(r["dob"]) == "2001-01-15", str(r))

        cur.execute("SELECT COUNT(*) AS n FROM players WHERE notes LIKE "
                    "'Years in Bahrain (management estimate%'")
        chk("C12 all 88 notes carry the labelled interim Years estimate",
            cur.fetchone()["n"] == 88)
        cur.execute("SELECT COUNT(*) AS n FROM players "
                    "WHERE notes LIKE '%Tumooh feedback (source file):%'")
        chk("C13 all 88 notes carry the source Tumooh feedback",
            cur.fetchone()["n"] == 88)

    # ── Case D: idempotency — re-run creates nothing ───────────────────
    print("\n=== Case D: idempotent re-run ===")
    preview_html, result_html = run_import(admin)
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM players")
        chk("D1 re-run created no new rows (still 88)",
            cur.fetchone()["n"] == 88)
        cur.execute("""
            SELECT COUNT(*) AS n FROM (
                SELECT LOWER(full_name) FROM players
                GROUP BY LOWER(full_name) HAVING COUNT(*) > 1
            ) d
        """)
        chk("D2 no duplicated names", cur.fetchone()["n"] == 0)

    # ── Case E: eligibility surfaces render gracefully with NULL date ──
    print("\n=== Case E: eligibility surfaces (real HTTP) ===")
    from app.players.eligibility import compute_eligibility_status

    ELIG_COLS = ("id, full_name, dob, nationality_status, eligible_from_date, "
                 "bahrain_residency_start_date, origin_country")
    with db() as conn, conn.cursor() as cur:
        cur.execute(f"""
            SELECT {ELIG_COLS} FROM players
            WHERE nationality_status = 'foreign_residency'
              AND bahrain_residency_start_date IS NULL LIMIT 1
        """)
        resident = cur.fetchone()
        resident_id = resident["id"]
        cur.execute(f"""
            SELECT {ELIG_COLS} FROM players
            WHERE nationality_status = 'bahraini'
              AND origin_country IS NULL LIMIT 1
        """)
        citizen = cur.fetchone()
        passport_id = citizen["id"]

    # The rendered text must be what compute_eligibility_status returns —
    # assert the helper's own output first, then that the page shows it.
    res_st = compute_eligibility_status(resident)
    cit_st = compute_eligibility_status(citizen)
    chk("E0a compute_eligibility_status: foreign_residency + NULL date "
        "-> pending, NOT eligible now",
        res_st["is_eligible_now"] is False
        and "residency start not set" in (res_st["label"] or ""),
        str(res_st))
    chk("E0b compute_eligibility_status: bahraini + NULL origin -> "
        "Citizen (birthright), status_code=citizen",
        cit_st["label"] == "Citizen"
        and cit_st.get("status_code") == "citizen",
        str(cit_st))

    st, html, _ = http(admin, "GET", f"/players/{resident_id}")
    chk("E1 foreign_residency profile loads (200)", st == 200)
    chk("E2 shows 'Pending — residency start not set' (no fake date)",
        "residency start not set" in html)
    chk("E2b foreign_residency profile does NOT claim 'Eligible now'",
        "Eligible now" not in html)
    chk("E2c no fabricated eligibility date/countdown rendered",
        "Eligible in " not in html)
    st, html, _ = http(admin, "GET", f"/players/{passport_id}")
    chk("E3 passport-holder profile loads (200)", st == 200)
    chk("E4 renders Citizen (origin pending, no crash)", "Citizen" in html)
    chk("E4b born-citizen profile does NOT render 'Eligible now' label",
        "Eligible now" not in html)
    st, html, _ = http(admin, "GET", "/nt/residents")
    chk("E5 /nt/residents loads (200)", st == 200)
    chk("E6 /nt/residents shows 'date not set' gracefully",
        "date not set" in html)
    st, html, _ = http(admin, "GET", "/players/")
    chk("E7 players list loads (200)", st == 200)

    # ── Case F: gap-list assertions ────────────────────────────────────
    print("\n=== Case F: gap-list CSV ===")
    with GAP_CSV.open(encoding="utf-8-sig") as fh:
        gaps = list(csv.DictReader(fh))
    chk("F1 gap-list has 88 rows", len(gaps) == 88)
    chk("F2 all 88 need entry date",
        all(g["needs_entry_date"] == "YES" for g in gaps))
    chk("F3 exactly 44 need origin (the passport holders)",
        sum(1 for g in gaps if g["needs_origin"] == "YES") == 44)
    chk("F4 1 blank-nationality row flagged",
        sum(1 for g in gaps if "blank Main Nationality" in g["flags"]) == 1)
    chk("F5 4 missing-BFA-ID rows flagged",
        sum(1 for g in gaps if "missing BFA ID" in g["flags"]) == 4)
    chk("F6 2 missing-DOB rows flagged",
        sum(1 for g in gaps if "missing date of birth" in g["flags"]) == 2)
    chk("F7 0 withdrawn rows among the kept 88 (all inside excluded 24)",
        sum(1 for g in gaps if "withdrawn" in g["flags"]) == 0)
    chk("F8 no excluded BFA ID appears in the gap-list",
        not any(g["bfa_id"] in EXCLUDED_IDS for g in gaps))

    # ── Case G: relabel — "National / BFA ID" rendered ─────────────────
    print("\n=== Case G: national_id relabel (display only) ===")
    st, html, _ = http(admin, "GET", "/players/new")
    chk("G1 /players/new form shows 'National / BFA ID'",
        st == 200 and "National / BFA ID" in html)
    st, html, _ = http(admin, "GET", f"/players/{resident_id}/edit")
    chk("G2 edit form shows 'National / BFA ID'",
        st == 200 and "National / BFA ID" in html)
    # profile.html renders the ID block only when the player HAS an ID
    # (4 of the 88 legitimately have none) — pick one that does.
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM players WHERE national_id IS NOT NULL "
                    "ORDER BY id LIMIT 1")
        with_id = cur.fetchone()["id"]
    st, html, _ = http(admin, "GET", f"/players/{with_id}")
    chk("G3 profile shows 'National / BFA ID'",
        st == 200 and "National / BFA ID" in html)

    # assign_clubs.html renders its table only when club-less players
    # exist; the import leaves 0 unmapped, so seed one throwaway row,
    # assert the header, then remove it (DB must end at exactly 88).
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO players (full_name, is_active) "
            "VALUES ('E2E RELABEL CLUBLESS FIXTURE', TRUE) RETURNING id")
        tmp_id = cur.fetchone()["id"]
        conn.commit()
    try:
        st, html, _ = http(admin, "GET", "/admin/assign-clubs")
        chk("G4 /admin/assign-clubs table header shows 'National / BFA ID'",
            st == 200 and "National / BFA ID" in html)
    finally:
        with db() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM players WHERE id = %s", (tmp_id,))
            conn.commit()
            cur.execute("SELECT COUNT(*) AS n FROM players")
            chk("G4b relabel fixture removed — back to exactly 88",
                cur.fetchone()["n"] == 88)

    st, html, _ = http(admin, "GET", "/youth/u23/new")
    chk("G5 /youth/u23/new form shows 'National / BFA ID'",
        st == 200 and "National / BFA ID" in html)
    chk("G6 no bare 'National ID' label left on the player forms",
        "National ID" not in html)

    # Passport PDF is rendered from passport/passport.html — assert the
    # relabel reached the PDF text layer (needs pypdf; dev-only dep).
    # The label is uppercased by CSS, so compare case-insensitively.
    req = Request(BASE + f"/players/{with_id}/passport.pdf")
    pdf_bytes = admin.open(req).read()
    try:
        from pypdf import PdfReader
        import io as _io
        text = "".join((p.extract_text() or "")
                       for p in PdfReader(_io.BytesIO(pdf_bytes)).pages)
        chk("G7 passport PDF text shows 'National / BFA ID'",
            "national / bfa id" in text.lower(),
            f"{len(pdf_bytes)} bytes")
    except ImportError:
        chk("G7 passport PDF text shows 'National / BFA ID'", False,
            "pypdf not installed (dev-only dep, absent from requirements.txt)")

    # ── Summary ────────────────────────────────────────────────────────
    fails = [r for r in results if not r[1]]
    print(f"\n{'='*60}\n{len(results) - len(fails)}/{len(results)} passed")
    if fails:
        for label, _, ev in fails:
            print(f"  FAILED: {label}  {ev}")
        sys.exit(1)
    print("ALL PASS — local dev DB left with the 88 imported players.")


if __name__ == "__main__":
    main()
