"""
Phase 4.2 synthetic E2E. Verifies:

  1. Live DB has `season` column on wyscout_match_stats; all existing
     rows are backfilled to '2025-26' (49 today, but checked dynamically).
  2. Re-uploading Arthur's Wyscout xlsx via ingest_wyscout() preserves
     season on UPSERT — no row drops or NULL-season regressions.
  3. derive_season() produces the same string as the SQL CASE for all
     match_dates currently in the DB (cross-language consistency check).
"""
import os
import sys
from datetime import date
from pathlib import Path
from dotenv import load_dotenv

# Make `app` importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

load_dotenv()

import psycopg2
import psycopg2.extras
from app import create_app
from app.wyscout.season import derive_season
from app.wyscout.ingest import ingest_wyscout

results = []
def chk(label, ok, ev=""):
    results.append((label, ok, ev))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}  {ev}")


def with_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"],
                            cursor_factory=psycopg2.extras.RealDictCursor)


# ── 1. Schema + backfill state ───────────────────────────────────
print("=== 1. Schema + backfill state ===")
with with_conn() as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT data_type, character_maximum_length, is_nullable
        FROM information_schema.columns
        WHERE table_name='wyscout_match_stats' AND column_name='season'
    """)
    r = cur.fetchone()
    chk("season column exists",
        r is not None,
        f"def: {dict(r) if r else None}")
    if r:
        chk("season column type/length/nullable correct",
            r['data_type'] == 'character varying'
            and r['character_maximum_length'] == 7
            and r['is_nullable'] == 'YES')

    cur.execute("""
        SELECT COUNT(*) AS total,
               COUNT(season) AS with_season,
               COUNT(*) FILTER (WHERE season = '2025-26') AS in_2025_26
        FROM wyscout_match_stats
    """)
    s = cur.fetchone()
    chk(f"all rows have season set",
        s['with_season'] == s['total'],
        f"total={s['total']}, with_season={s['with_season']}")
    chk(f"all rows are season=2025-26 (single-season state)",
        s['in_2025_26'] == s['total'])

    # Phase 4.2.1 ENABLEMENT: query-by-season returns sensible rows.
    cur.execute("""
        SELECT COUNT(*) AS n FROM wyscout_match_stats WHERE season='2025-26'
    """)
    chk("query-by-season works (smoke test for 4.2.1 UI later)",
        cur.fetchone()['n'] == s['total'])


# ── 2. Python helper matches SQL backfill for every live row ─────
print("\n=== 2. Python helper vs SQL backfill cross-check ===")
with with_conn() as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT DISTINCT match_date, season FROM wyscout_match_stats
        WHERE match_date IS NOT NULL ORDER BY match_date
    """)
    rows = cur.fetchall()
    mismatches = []
    for r in rows:
        py = derive_season(r['match_date'])
        if py != r['season']:
            mismatches.append((r['match_date'], r['season'], py))
    chk(f"derive_season() matches DB season for all {len(rows)} distinct match_dates",
        not mismatches, f"mismatches: {mismatches[:3]}")


# ── 3. Re-upload Arthur's xlsx; verify UPSERT preserves season ───
print("\n=== 3. Re-upload UPSERT integrity ===")
xlsx_path = Path(__file__).resolve().parent.parent / "sample_data" / "Player_stats_Arthur_Rezende.xlsx"
chk(f"sample xlsx exists: {xlsx_path.name}", xlsx_path.exists())

with with_conn() as conn, conn.cursor() as cur:
    cur.execute("SELECT id FROM players WHERE full_name ILIKE 'Arthur%' LIMIT 1")
    arthur = cur.fetchone()
chk("Arthur player row found", arthur is not None,
    f"id: {arthur['id'] if arthur else None}")

with with_conn() as conn, conn.cursor() as cur:
    cur.execute("SELECT id FROM users WHERE email = %s",
                (os.environ["INITIAL_ADMIN_EMAIL"],))
    admin = cur.fetchone()
chk("admin user found",
    admin is not None,
    f"id: {admin['id'] if admin else None}")

# Snapshot pre-state for Arthur.
with with_conn() as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT COUNT(*) AS n,
               COUNT(season) AS with_season,
               COUNT(*) FILTER (WHERE season='2025-26') AS in_2025_26
        FROM wyscout_match_stats WHERE player_id=%s
    """, (arthur['id'],))
    pre = cur.fetchone()
print(f"  pre-upload Arthur rows: n={pre['n']}, with_season={pre['with_season']}, 2025-26={pre['in_2025_26']}")

# Run ingest through the real pipeline (NOT flask.test_client, per hard rule).
# Need an app context because ingest pulls a conn from the pool.
app = create_app()
with app.app_context():
    result = ingest_wyscout(
        player_id=arthur['id'],
        file_path=str(xlsx_path),
        file_name=xlsx_path.name,
        uploaded_by_id=admin['id'],
    )
print(f"  ingest result: {result}")

chk("ingest reported status=success",
    result.get('status') == 'success',
    f"status: {result.get('status')}, error: {result.get('error')}")
# Re-upload of an already-imported file should be all updates, no inserts.
chk("ingest inserted == 0 (re-upload, all rows already present)",
    result.get('inserted', -1) == 0,
    f"inserted: {result.get('inserted')}")
chk("ingest updated > 0 (at least one row matched on conflict)",
    (result.get('updated') or 0) > 0,
    f"updated: {result.get('updated')}")

# Post-state.
with with_conn() as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT COUNT(*) AS n,
               COUNT(season) AS with_season,
               COUNT(*) FILTER (WHERE season='2025-26') AS in_2025_26
        FROM wyscout_match_stats WHERE player_id=%s
    """, (arthur['id'],))
    post = cur.fetchone()
print(f"  post-upload Arthur rows: n={post['n']}, with_season={post['with_season']}, 2025-26={post['in_2025_26']}")

chk("Arthur row count unchanged by re-upload",
    pre['n'] == post['n'],
    f"pre={pre['n']}, post={post['n']}")
chk("all Arthur rows still have season set (no NULLs introduced by UPSERT)",
    post['with_season'] == post['n'],
    f"with_season={post['with_season']}, n={post['n']}")
chk("all Arthur rows still season='2025-26' after re-upload",
    post['in_2025_26'] == post['n'],
    f"in_2025_26={post['in_2025_26']}, n={post['n']}")

# Global sanity: total row count unchanged, no NULL seasons anywhere.
with with_conn() as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT COUNT(*) AS total,
               COUNT(*) FILTER (WHERE season IS NULL) AS null_season,
               COUNT(*) FILTER (WHERE season='2025-26') AS in_2025_26
        FROM wyscout_match_stats
    """)
    g = cur.fetchone()
chk("global total wyscout_match_stats rows >= pre-existing 49",
    g['total'] >= 49,
    f"total: {g['total']}")
chk("0 NULL season rows globally",
    g['null_season'] == 0)
chk("all global rows in season='2025-26' (single-season state)",
    g['in_2025_26'] == g['total'])

# Final eyeball: per-player breakdown
with with_conn() as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT p.full_name, COUNT(*) AS n, MIN(s.match_date) AS lo,
               MAX(s.match_date) AS hi, STRING_AGG(DISTINCT s.season, ',') AS seasons
        FROM   wyscout_match_stats s
        JOIN   players p ON p.id = s.player_id
        GROUP  BY p.full_name
        ORDER  BY p.full_name
    """)
    print("\nPer-player breakdown:")
    for r in cur.fetchall():
        print(f"  {r['full_name']:<30} n={r['n']:<3} {r['lo']} .. {r['hi']}  seasons={r['seasons']}")


print("\n" + "=" * 60)
n_pass = sum(1 for _, ok, _ in results if ok)
n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"E2E summary: {n_pass} pass / {n_fail} fail (of {len(results)})")
sys.exit(0 if n_fail == 0 else 2)
