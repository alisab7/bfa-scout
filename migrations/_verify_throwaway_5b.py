"""
Throwaway-namespace verification for Phase 5b:

1. Create a fresh schema, set search_path so unqualified references land in it
2. Run the updated schema.sql top-to-bottom
3. Verify:
   - matches table exists with expected columns
   - wyscout_match_stats has match_id column
   - the four expected indexes on matches exist
   - matches table is empty (schema.sql doesn't seed wyscout matches)
   - wyscout_match_stats is empty too — schema.sql is fresh-install, no Wyscout data
4. DROP SCHEMA CASCADE in finally:, no matter what

Confirms a fresh `flask init-db` reproduces the table shape (data is
loaded separately by uploads).
"""
import os
import sys
import secrets
from pathlib import Path
from dotenv import load_dotenv
import psycopg2

load_dotenv()

SCHEMA = f"phase5b_check_{secrets.token_hex(4)}"
schema_path = Path(__file__).parent.parent / "schema.sql"
schema_sql  = schema_path.read_text(encoding="utf-8")

EXPECTED_MATCHES_COLS = {
    "id", "match_date", "home_team", "away_team",
    "home_score", "away_score", "competition",
    "age_group", "match_type", "bfa_team_side",
    "notes", "source",
    "created_by", "created_at", "updated_at",
}
EXPECTED_INDEXES = {
    "idx_matches_lookup",
    "idx_matches_age_group",
    "idx_matches_source",
    "idx_matches_date",
}

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

        # 1. matches table exists, has expected columns
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = %s AND table_name = 'matches'
        """, (SCHEMA,))
        cols = {r[0] for r in cur.fetchall()}
        missing_cols = EXPECTED_MATCHES_COLS - cols
        extra_cols = cols - EXPECTED_MATCHES_COLS
        if missing_cols:
            fails.append(f"matches missing columns: {missing_cols}")
        if extra_cols:
            fails.append(f"matches has unexpected columns: {extra_cols}")
        print(f"  matches columns ({len(cols)}): OK" if not (missing_cols or extra_cols)
              else f"  matches columns mismatch")

        # 2. wyscout_match_stats has match_id
        cur.execute("""
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = %s AND table_name = 'wyscout_match_stats'
              AND column_name = 'match_id'
        """, (SCHEMA,))
        if cur.fetchone() is None:
            fails.append("wyscout_match_stats.match_id missing")
        else:
            print("  wyscout_match_stats.match_id: OK")

        # 3. Expected indexes on matches
        cur.execute("""
            SELECT indexname FROM pg_indexes
            WHERE schemaname = %s AND tablename = 'matches'
        """, (SCHEMA,))
        idxs = {r[0] for r in cur.fetchall()}
        missing_idx = EXPECTED_INDEXES - idxs
        if missing_idx:
            fails.append(f"matches missing indexes: {missing_idx}")
        else:
            print(f"  matches indexes: OK ({len(idxs)} total — includes pkey + UNIQUE constraint)")

        # 4. matches is empty
        cur.execute("SELECT COUNT(*) FROM matches")
        n = cur.fetchone()[0]
        if n != 0:
            fails.append(f"matches not empty: {n} rows")
        else:
            print("  matches row count: 0 (expected — schema.sql is fresh-install only)")

        # 5. wyscout_match_stats is empty (no data in schema.sql)
        cur.execute("SELECT COUNT(*) FROM wyscout_match_stats")
        n = cur.fetchone()[0]
        if n != 0:
            fails.append(f"wyscout_match_stats not empty: {n} rows")
        else:
            print("  wyscout_match_stats row count: 0 (expected)")

        # 6. FK from wyscout_match_stats.match_id to matches.id with ON DELETE SET NULL
        cur.execute("""
            SELECT con.conname, con.confdeltype
            FROM pg_constraint con
            JOIN pg_class       rel  ON rel.oid = con.conrelid
            JOIN pg_namespace   nsp  ON nsp.oid = rel.relnamespace
            JOIN pg_attribute   att  ON att.attrelid = rel.oid AND att.attnum = ANY(con.conkey)
            WHERE nsp.nspname = %s
              AND rel.relname = 'wyscout_match_stats'
              AND att.attname = 'match_id'
              AND con.contype = 'f'
        """, (SCHEMA,))
        fk = cur.fetchone()
        if not fk:
            fails.append("FK wyscout_match_stats.match_id → matches missing")
        elif fk[1] != 'n':  # 'n' = SET NULL
            fails.append(f"FK delete behaviour wrong: confdeltype={fk[1]!r} (expected 'n' for SET NULL)")
        else:
            print(f"  FK match_id → matches with ON DELETE SET NULL: OK")

    if fails:
        print("\nFAILS:")
        for f in fails:
            print(f"  ! {f}")
        exit_code = 2
    else:
        print("\nThrowaway-schema convergence confirmed.")
        print("Fresh `flask init-db` reproduces matches table + match_id column + FK semantics.")
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
