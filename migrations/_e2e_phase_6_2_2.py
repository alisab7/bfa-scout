"""
Phase 6.2.2 synthetic E2E — Wyscout idempotency audit.

Three diagnostic queries to confirm:
  Q1. No duplicate (player_id, match_label, match_date) rows exist in
      wyscout_match_stats (would indicate UPSERT is not firing).
  Q2. The UNIQUE constraint matching the ON CONFLICT clause is present
      in pg_constraint.
  Q3. Total row count + per-player breakdown (sanity check / baseline).

Code-review verdict (pre-run): ingest.py ON CONFLICT clause exactly
matches schema.sql UNIQUE constraint — both use
  (player_id, match_label, match_date)
so duplicates cannot accumulate via the normal ingest path. This script
confirms that verdict against the live DB and exits 0 only if all
three checks pass.

Per hard rule: real DB connection (DATABASE_URL env var). No test
client, no mocks.
"""
import os
import sys
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

results = []


def chk(label: str, ok: bool, evidence: str = ""):
    results.append((label, ok, evidence))
    status = "PASS" if ok else "FAIL"
    suffix = f"  {evidence}" if evidence else ""
    print(f"  [{status}] {label}{suffix}")


def db():
    return psycopg2.connect(
        os.environ["DATABASE_URL"],
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


print("=" * 60)
print("BFA-Scout Phase 6.2.2 — Wyscout idempotency audit")
print("=" * 60)

with db() as conn, conn.cursor() as cur:

    # ── Q1: Duplicate rows ────────────────────────────────────────
    print("\n=== Q1: Duplicate (player_id, match_label, match_date) rows ===")
    cur.execute(
        """
        SELECT player_id,
               match_label,
               match_date,
               COUNT(*) AS n
        FROM   wyscout_match_stats
        GROUP  BY player_id, match_label, match_date
        HAVING COUNT(*) > 1
        ORDER  BY n DESC, player_id
        LIMIT  20
        """
    )
    dupes = cur.fetchall()
    chk(
        "No duplicate (player_id, match_label, match_date) rows",
        len(dupes) == 0,
        f"{len(dupes)} duplicate group(s) found" if dupes else "",
    )
    if dupes:
        print("  Duplicates detail:")
        for row in dupes:
            print(f"    player_id={row['player_id']}  match_label={row['match_label']!r}"
                  f"  match_date={row['match_date']}  count={row['n']}")

    # ── Q2: UNIQUE constraint present ───────────────────────────
    print("\n=== Q2: UNIQUE constraint exists in pg_constraint ===")
    cur.execute(
        """
        SELECT conname, pg_get_constraintdef(oid) AS def
        FROM   pg_constraint
        WHERE  conrelid = 'wyscout_match_stats'::regclass
          AND  contype  = 'u'
        ORDER  BY conname
        """
    )
    constraints = cur.fetchall()
    # We expect exactly one UNIQUE constraint on (player_id, match_label, match_date)
    target_cols = {"player_id", "match_label", "match_date"}
    found_matching = False
    for c in constraints:
        defn = (c["def"] or "").lower()
        if all(col in defn for col in target_cols):
            found_matching = True
            chk(
                "UNIQUE (player_id, match_label, match_date) constraint present",
                True,
                f"conname={c['conname']!r}  def={c['def']!r}",
            )
    if not found_matching:
        chk(
            "UNIQUE (player_id, match_label, match_date) constraint present",
            False,
            f"constraints found: {[c['conname'] for c in constraints]}",
        )

    # Bonus: also confirm there is no UNIQUE on just (player_id, match_date)
    # — that stricter constraint would wrongly block two games on the same day.
    cur.execute(
        """
        SELECT conname, pg_get_constraintdef(oid) AS def
        FROM   pg_constraint
        WHERE  conrelid = 'wyscout_match_stats'::regclass
          AND  contype  = 'u'
          AND  pg_get_constraintdef(oid) ILIKE '%player_id%'
          AND  pg_get_constraintdef(oid) ILIKE '%match_date%'
          AND  pg_get_constraintdef(oid) NOT ILIKE '%match_label%'
        """
    )
    bad_constraints = cur.fetchall()
    chk(
        "No over-strict UNIQUE (player_id, match_date) without match_label",
        len(bad_constraints) == 0,
        f"found: {[c['conname'] for c in bad_constraints]}" if bad_constraints else "",
    )

    # ── Q3: Row count baseline ───────────────────────────────────
    print("\n=== Q3: Row count + per-player breakdown ===")
    cur.execute("SELECT COUNT(*) AS total FROM wyscout_match_stats")
    total = cur.fetchone()["total"]
    print(f"  Total wyscout_match_stats rows: {total}")

    cur.execute(
        """
        SELECT p.full_name,
               COUNT(w.id) AS match_rows
        FROM   wyscout_match_stats w
        JOIN   players p ON p.id = w.player_id
        GROUP  BY p.id, p.full_name
        ORDER  BY match_rows DESC
        LIMIT  15
        """
    )
    breakdown = cur.fetchall()
    if breakdown:
        print("  Top players by Wyscout row count:")
        for row in breakdown:
            print(f"    {row['full_name']}: {row['match_rows']} row(s)")
    else:
        print("  (no Wyscout data loaded yet)")

    chk(
        "Wyscout row count query executed without error",
        True,
        f"total rows = {total}",
    )

# ── Summary ──────────────────────────────────────────────────────
print("\n" + "=" * 60)
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"E2E summary: {n_pass} pass / {n_fail} fail (of {len(results)})")
sys.exit(0 if n_fail == 0 else 2)
