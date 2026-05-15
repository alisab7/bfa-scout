"""
Throwaway-namespace verification for Phase 5c-1.

Replays the updated schema.sql in an isolated schema and asserts:
  - players has the 3 NT-eligibility columns
  - evaluations has match_id with FK to matches(id) ON DELETE SET NULL
  - idx_evaluations_match_id present
  - nationality_status CHECK matches the spec values
  - matches table still exists (Phase 5b state preserved)
"""
import os
import sys
import secrets
from pathlib import Path
from dotenv import load_dotenv
import psycopg2

load_dotenv()
SCHEMA = f"phase5c1_check_{secrets.token_hex(4)}"
schema_path = Path(__file__).parent.parent / "schema.sql"
schema_sql  = schema_path.read_text(encoding="utf-8")

EXPECTED_PLAYER_COLS = {"nationality_status", "eligible_from_date", "eligibility_notes_admin"}

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

        # 1. players has the 3 NT-eligibility columns
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = %s AND table_name = 'players'
              AND column_name IN ('nationality_status','eligible_from_date','eligibility_notes_admin')
        """, (SCHEMA,))
        cols = {r[0] for r in cur.fetchall()}
        missing = EXPECTED_PLAYER_COLS - cols
        if missing:
            fails.append(f"players missing eligibility cols: {missing}")
        else:
            print(f"  players NT-eligibility cols: OK ({sorted(cols)})")

        # 2. evaluations.match_id present
        cur.execute("""
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = %s AND table_name = 'evaluations' AND column_name = 'match_id'
        """, (SCHEMA,))
        if cur.fetchone() is None:
            fails.append("evaluations.match_id missing")
        else:
            print("  evaluations.match_id: OK")

        # 3. FK exists with ON DELETE SET NULL
        cur.execute("""
            SELECT con.confdeltype
            FROM pg_constraint con
            JOIN pg_class       rel ON rel.oid = con.conrelid
            JOIN pg_namespace   nsp ON nsp.oid = rel.relnamespace
            JOIN pg_attribute   att ON att.attrelid = rel.oid AND att.attnum = ANY(con.conkey)
            WHERE nsp.nspname = %s
              AND rel.relname = 'evaluations'
              AND att.attname = 'match_id'
              AND con.contype = 'f'
        """, (SCHEMA,))
        fk = cur.fetchone()
        if not fk:
            fails.append("FK evaluations.match_id → matches missing")
        elif fk[0] != 'n':
            fails.append(f"FK delete behaviour wrong: {fk[0]!r} (expected 'n' for SET NULL)")
        else:
            print("  FK match_id → matches with ON DELETE SET NULL: OK")

        # 4. Index on match_id present
        cur.execute("""
            SELECT 1 FROM pg_indexes
            WHERE schemaname = %s AND indexname = 'idx_evaluations_match_id'
        """, (SCHEMA,))
        if cur.fetchone() is None:
            fails.append("idx_evaluations_match_id missing")
        else:
            print("  idx_evaluations_match_id: OK")

        # 5. nationality_status CHECK values
        cur.execute("""
            SELECT pg_get_constraintdef(con.oid)
            FROM pg_constraint con
            JOIN pg_class rel ON rel.oid = con.conrelid
            JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
            WHERE nsp.nspname = %s AND rel.relname = 'players'
              AND con.contype = 'c'
              AND pg_get_constraintdef(con.oid) ILIKE '%%nationality_status%%'
        """, (SCHEMA,))
        chk = cur.fetchone()
        if not chk:
            fails.append("players nationality_status CHECK missing")
        else:
            for v in ('bahraini','foreign_ancestry','foreign_residency','not_eligible','unknown'):
                if v not in chk[0]:
                    fails.append(f"CHECK missing value {v!r}: {chk[0]}")
            print("  nationality_status CHECK: OK")

        # 6. matches table still exists
        cur.execute("""
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = %s AND table_name = 'matches'
        """, (SCHEMA,))
        if cur.fetchone() is None:
            fails.append("matches table missing — Phase 5b regression")
        else:
            print("  matches table: OK (Phase 5b state preserved)")

    if fails:
        print("\nFAILS:")
        for f in fails:
            print(f"  ! {f}")
        exit_code = 2
    else:
        print("\nThrowaway-schema convergence confirmed.")
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
