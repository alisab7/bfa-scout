"""
Throwaway-namespace verification for Phase 7:

1. Create a fresh schema, set search_path so unqualified refs land in it.
2. Run the updated schema.sql top-to-bottom.
3. Verify:
   - evaluations.created_by_role exists; VARCHAR(32); NOT NULL; default 'scout'
   - idx_evaluations_created_by_role index exists on (created_by_role)
   - users_role_check constraint allows the 5 roles
     (admin, technical_director, scout, viewer, nt_staff) AND
     rejects an unknown role
   - evaluations table is empty in a fresh install (no seed data)
4. DROP SCHEMA CASCADE in finally:, no matter what.

Confirms a fresh `flask init-db` reproduces the column shape +
constraint widening without needing ALTERs.
"""
import os
import sys
import secrets
from pathlib import Path
from dotenv import load_dotenv
import psycopg2

load_dotenv()

SCHEMA = f"phase7_check_{secrets.token_hex(4)}"
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

        # 1. evaluations.created_by_role shape
        cur.execute("""
            SELECT data_type, character_maximum_length, is_nullable, column_default
            FROM   information_schema.columns
            WHERE  table_schema = %s
              AND  table_name   = 'evaluations'
              AND  column_name  = 'created_by_role'
        """, (SCHEMA,))
        r = cur.fetchone()
        if not r:
            fails.append("evaluations.created_by_role column missing")
        else:
            dtype, maxlen, nullable, default = r
            if dtype != 'character varying':
                fails.append(f"created_by_role data_type = {dtype!r}, expected 'character varying'")
            if maxlen != 32:
                fails.append(f"created_by_role max length = {maxlen}, expected 32")
            if nullable != 'NO':
                fails.append(f"created_by_role is_nullable = {nullable!r}, expected 'NO'")
            if not (default and "'scout'" in default):
                fails.append(f"created_by_role default = {default!r}, expected to include 'scout'")
            if not fails:
                print(f"  evaluations.created_by_role: VARCHAR({maxlen}), NOT NULL, default {default!r} -- OK")

        # 2. Index present
        cur.execute("""
            SELECT indexdef FROM pg_indexes
            WHERE schemaname = %s
              AND tablename = 'evaluations'
              AND indexname = 'idx_evaluations_created_by_role'
        """, (SCHEMA,))
        r = cur.fetchone()
        if not r:
            fails.append("idx_evaluations_created_by_role missing")
        elif "(created_by_role)" not in r[0]:
            fails.append(f"idx_evaluations_created_by_role wrong cols: {r[0]!r}")
        else:
            print(f"  idx_evaluations_created_by_role exists on (created_by_role) -- OK")

        # 3. users_role_check allows all 5 roles (additive widening)
        cur.execute("""
            SELECT pg_get_constraintdef(c.oid)
            FROM   pg_constraint c
            JOIN   pg_class rel ON rel.oid = c.conrelid
            JOIN   pg_namespace n ON n.oid = rel.relnamespace
            WHERE  n.nspname = %s AND rel.relname = 'users' AND c.conname = 'users_role_check'
        """, (SCHEMA,))
        r = cur.fetchone()
        if not r:
            fails.append("users_role_check constraint missing")
        else:
            cdef = r[0]
            expected_roles = {'admin', 'technical_director', 'scout', 'viewer', 'nt_staff'}
            seen = {role for role in expected_roles if f"'{role}'" in cdef}
            missing = expected_roles - seen
            if missing:
                fails.append(f"users_role_check missing roles {missing}; def={cdef}")
            else:
                print(f"  users_role_check allows all 5 roles ({sorted(expected_roles)}) -- OK")

        # 4. Insert a row to actually exercise the constraint
        # (constraint test, no impact on the live DB — we're in a throwaway schema)
        cur.execute("""
            INSERT INTO users (email, password_hash, full_name, role)
            VALUES ('test@example.com', 'x', 'Test', 'nt_staff')
            RETURNING id
        """)
        uid = cur.fetchone()[0]
        if uid:
            print(f"  INSERT users (role='nt_staff') succeeded -- OK")
        # And a rejection test
        try:
            cur.execute("""
                INSERT INTO users (email, password_hash, full_name, role)
                VALUES ('bad@example.com', 'x', 'Bad', 'not_a_real_role')
            """)
            fails.append("users_role_check accepted bogus role 'not_a_real_role'")
        except psycopg2.errors.CheckViolation:
            print(f"  users_role_check rejects unknown role -- OK")
            conn.rollback()  # release the failed savepoint
            cur.execute(f'SET search_path TO "{SCHEMA}"')

        # 5. evaluations empty in fresh install
        cur.execute("SELECT COUNT(*) FROM evaluations")
        n = cur.fetchone()[0]
        if n != 0:
            fails.append(f"evaluations not empty in fresh schema: {n} rows")
        else:
            print("  evaluations row count: 0 (expected -- fresh install)")

    if fails:
        print("\nFAILS:")
        for f in fails:
            print(f"  ! {f}")
        exit_code = 2
    else:
        print("\nThrowaway-schema convergence confirmed.")
        print("Fresh `flask init-db` reproduces created_by_role + widened role constraint, no ALTER required.")
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
