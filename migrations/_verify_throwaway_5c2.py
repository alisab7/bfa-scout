"""
Throwaway-namespace verification for Phase 5c-2.

Replays the updated schema.sql in an isolated schema and asserts:
  - players has bahrain_residency_start_date + bahrain_residency_notes
  - evaluations has locked_reason, last_edited_by, last_edited_at
  - locked_by FK = ON DELETE SET NULL
  - last_edited_by FK = ON DELETE SET NULL
  - status CHECK still includes 'locked'
"""
import os, sys, secrets
from pathlib import Path
from dotenv import load_dotenv
import psycopg2

load_dotenv()
SCHEMA = f"phase5c2_check_{secrets.token_hex(4)}"
schema_sql = (Path(__file__).parent.parent / "schema.sql").read_text(encoding="utf-8")

EXPECTED_NEW_COLS = {
    ("players", "bahrain_residency_start_date"),
    ("players", "bahrain_residency_notes"),
    ("evaluations", "locked_reason"),
    ("evaluations", "last_edited_by"),
    ("evaluations", "last_edited_at"),
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

        # 1. New columns present
        for tbl, col in EXPECTED_NEW_COLS:
            cur.execute("""
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s AND column_name = %s
            """, (SCHEMA, tbl, col))
            if cur.fetchone() is None:
                fails.append(f"{tbl}.{col} missing")
            else:
                print(f"  {tbl}.{col}: OK")

        # 2. Both FKs ON DELETE SET NULL
        for col_name in ("locked_by", "last_edited_by"):
            cur.execute("""
                SELECT con.confdeltype
                FROM pg_constraint con
                JOIN pg_class       rel ON rel.oid = con.conrelid
                JOIN pg_namespace   nsp ON nsp.oid = rel.relnamespace
                JOIN pg_attribute   att ON att.attrelid = rel.oid AND att.attnum = ANY(con.conkey)
                WHERE nsp.nspname = %s AND rel.relname = 'evaluations'
                  AND att.attname = %s AND con.contype = 'f'
            """, (SCHEMA, col_name))
            r = cur.fetchone()
            if not r:
                fails.append(f"FK on evaluations.{col_name} missing")
            elif r[0] != 'n':
                fails.append(f"FK on {col_name} confdeltype={r[0]!r} (expected 'n')")
            else:
                print(f"  evaluations.{col_name} FK ON DELETE SET NULL: OK")

        # 3. status CHECK still includes 'locked'
        cur.execute("""
            SELECT pg_get_constraintdef(con.oid)
            FROM pg_constraint con
            JOIN pg_class rel ON rel.oid = con.conrelid
            JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
            WHERE nsp.nspname = %s AND rel.relname = 'evaluations'
              AND con.conname = 'evaluations_status_check'
        """, (SCHEMA,))
        r = cur.fetchone()
        if not r or 'locked' not in r[0]:
            fails.append("status CHECK missing 'locked' value")
        else:
            print("  status CHECK includes 'locked': OK")

    if fails:
        print("\nFAILS:")
        for f in fails: print(f"  ! {f}")
        exit_code = 2
    else:
        print("\nThrowaway-schema convergence confirmed.")
finally:
    try: conn.rollback()
    except Exception: pass
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
        print(f"Dropped throwaway schema {SCHEMA!r}.")
    finally:
        conn.close()

sys.exit(exit_code)
