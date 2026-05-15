"""
Throwaway-namespace verification for Phase 4.2:

1. Create a fresh schema, set search_path so unqualified references land in it.
2. Run the updated schema.sql top-to-bottom.
3. Verify:
   - wyscout_match_stats has a `season VARCHAR(7)` column, nullable
   - idx_wyscout_match_stats_season index exists on (season)
   - wyscout_match_stats is empty in a fresh install (no seed data)
4. DROP SCHEMA CASCADE in finally:, no matter what.

Confirms a fresh `flask init-db` reproduces the table shape (declarative
schema.sql, no ALTER TABLE statements in this file).
"""
import os
import sys
import secrets
from pathlib import Path
from dotenv import load_dotenv
import psycopg2

load_dotenv()

SCHEMA = f"phase42_check_{secrets.token_hex(4)}"
schema_path = Path(__file__).parent.parent / "schema.sql"
schema_sql  = schema_path.read_text(encoding="utf-8")

conn = psycopg2.connect(os.environ["DATABASE_URL"])
conn.autocommit = False
exit_code = 0
try:
    with conn.cursor() as cur:
        cur.execute(f'CREATE SCHEMA "{SCHEMA}"')
        cur.execute(f'SET search_path TO "{SCHEMA}", public')
        cur.execute(schema_sql)
    conn.commit()
    print(f"schema.sql applied cleanly to throwaway schema {SCHEMA!r}.")

    fails = []
    with conn.cursor() as cur:
        cur.execute(f'SET search_path TO "{SCHEMA}"')

        # 1. wyscout_match_stats.season exists, VARCHAR(7), nullable
        cur.execute("""
            SELECT data_type, character_maximum_length, is_nullable
            FROM   information_schema.columns
            WHERE  table_schema = %s
              AND  table_name   = 'wyscout_match_stats'
              AND  column_name  = 'season'
        """, (SCHEMA,))
        r = cur.fetchone()
        if not r:
            fails.append("wyscout_match_stats.season column missing")
        else:
            dtype, maxlen, nullable = r
            if dtype != 'character varying':
                fails.append(f"season column data_type = {dtype!r}, expected 'character varying'")
            if maxlen != 7:
                fails.append(f"season column max length = {maxlen}, expected 7")
            if nullable != 'YES':
                fails.append(f"season column is_nullable = {nullable!r}, expected 'YES'")
            if not fails:
                print(f"  wyscout_match_stats.season: VARCHAR({maxlen}), nullable={nullable} -- OK")

        # 2. idx_wyscout_match_stats_season index exists on (season)
        cur.execute("""
            SELECT indexdef FROM pg_indexes
            WHERE schemaname = %s
              AND tablename = 'wyscout_match_stats'
              AND indexname = 'idx_wyscout_match_stats_season'
        """, (SCHEMA,))
        r = cur.fetchone()
        if not r:
            fails.append("idx_wyscout_match_stats_season missing")
        elif "(season)" not in r[0]:
            fails.append(f"idx_wyscout_match_stats_season targets wrong cols: {r[0]!r}")
        else:
            print(f"  idx_wyscout_match_stats_season exists on (season) -- OK")

        # 3. wyscout_match_stats is empty in a fresh install
        cur.execute("SELECT COUNT(*) FROM wyscout_match_stats")
        n = cur.fetchone()[0]
        if n != 0:
            fails.append(f"wyscout_match_stats not empty in fresh schema: {n} rows")
        else:
            print("  wyscout_match_stats row count: 0 (expected -- schema.sql is fresh-install only)")

        # 4. Sanity: existing 5b indexes still present (no accidental drop)
        cur.execute("""
            SELECT indexname FROM pg_indexes
            WHERE schemaname = %s AND tablename = 'wyscout_match_stats'
        """, (SCHEMA,))
        idxs = {r[0] for r in cur.fetchall()}
        expected_existing = {
            'idx_wyscout_player', 'idx_wyscout_date',
            'idx_wyscout_competition', 'idx_wyscout_match_id',
            'idx_wyscout_match_stats_season',
        }
        missing = expected_existing - idxs
        if missing:
            fails.append(f"wyscout_match_stats missing indexes: {missing}")
        else:
            print(f"  all 5 wyscout indexes present (4 prior + season): OK")

    if fails:
        print("\nFAILS:")
        for f in fails:
            print(f"  ! {f}")
        exit_code = 2
    else:
        print("\nThrowaway-schema convergence confirmed.")
        print("Fresh `flask init-db` reproduces season column + index, no ALTER required.")
finally:
    try:
        conn.rollback()
    except Exception:
        pass
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
        print(f"Dropped throwaway schema {SCHEMA!r}.")
    finally:
        conn.close()

sys.exit(exit_code)
