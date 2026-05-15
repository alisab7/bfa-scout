"""
Throwaway-namespace verification for Phase 5c-1.1.

Replays the updated schema.sql in an isolated schema and asserts:
  - evaluation_scores has is_not_applicable column (BOOL, NOT NULL, default FALSE)
  - score column is nullable
  - evaluation_scores_score_or_na CHECK constraint exists
  - The CHECK actually rejects malformed inserts:
      (score=5, is_not_applicable=TRUE)   → must reject
      (score=NULL, is_not_applicable=FALSE) → must reject
      (score=5, is_not_applicable=FALSE)  → accept
      (score=NULL, is_not_applicable=TRUE) → accept
"""
import os
import sys
import secrets
from pathlib import Path
from dotenv import load_dotenv
import psycopg2

load_dotenv()
SCHEMA = f"phase5c1_1_check_{secrets.token_hex(4)}"
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

        # 1. is_not_applicable column with right type + default + NOT NULL
        cur.execute("""
            SELECT data_type, column_default, is_nullable
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = 'evaluation_scores'
              AND column_name = 'is_not_applicable'
        """, (SCHEMA,))
        r = cur.fetchone()
        if not r:
            fails.append("is_not_applicable column missing")
        else:
            dtype, default, nullable = r
            print(f"  is_not_applicable: type={dtype} default={default} nullable={nullable}")
            if dtype != 'boolean': fails.append(f"is_not_applicable type wrong: {dtype}")
            if 'false' not in (default or '').lower(): fails.append(f"is_not_applicable default wrong: {default}")
            if nullable != 'NO': fails.append("is_not_applicable should be NOT NULL")

        # 2. score column nullable
        cur.execute("""
            SELECT is_nullable FROM information_schema.columns
            WHERE table_schema = %s AND table_name = 'evaluation_scores'
              AND column_name = 'score'
        """, (SCHEMA,))
        r = cur.fetchone()
        if r is None:
            fails.append("score column missing")
        elif r[0] != 'YES':
            fails.append(f"score should be nullable; got is_nullable={r[0]}")
        else:
            print("  score: nullable OK")

        # 3. CHECK constraint present
        cur.execute("""
            SELECT pg_get_constraintdef(con.oid)
            FROM pg_constraint con
            JOIN pg_class rel ON rel.oid = con.conrelid
            JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
            WHERE nsp.nspname = %s AND rel.relname = 'evaluation_scores'
              AND con.conname = 'evaluation_scores_score_or_na'
        """, (SCHEMA,))
        r = cur.fetchone()
        if not r:
            fails.append("evaluation_scores_score_or_na CHECK missing")
        else:
            print(f"  CHECK constraint: {r[0]}")

        # 4. Functional CHECK test — try to insert each combo, see what's rejected
        # First seed an evaluation row to attach scores to (matches/players already created in fresh schema)
        cur.execute("INSERT INTO position_groups (code, name_en, name_ar) VALUES ('TST','Test','اختبار') RETURNING id")
        pg_id = cur.fetchone()[0]
        cur.execute("INSERT INTO criteria_categories (code, name_en, name_ar) VALUES ('TST','Test','اختبار') RETURNING id")
        cc_id = cur.fetchone()[0]
        cur.execute("INSERT INTO criteria (category_id, code, name_en, name_ar) VALUES (%s, 'tst_x', 'X', 'اكس') RETURNING id", (cc_id,))
        crit_id = cur.fetchone()[0]
        cur.execute("INSERT INTO users (email, password_hash, full_name, role) VALUES ('t@t', 'x', 'T', 'admin') RETURNING id")
        u_id = cur.fetchone()[0]
        cur.execute("INSERT INTO players (full_name, national_id) VALUES ('TestP', 'TX1') RETURNING id")
        p_id = cur.fetchone()[0]
        cur.execute("INSERT INTO evaluations (player_id, evaluator_id, position_group_id) VALUES (%s, %s, %s) RETURNING id",
                    (p_id, u_id, pg_id))
        ev_id = cur.fetchone()[0]

        # Test matrix: each insert in its own savepoint so a failure doesn't taint the txn
        cases = [
            # (score, is_not_applicable, should_succeed, label)
            (7.5,  False, True,  "rated (score=7.5, na=FALSE)"),
            (None, True,  True,  "N/A (score=NULL, na=TRUE)"),
            (7.5,  True,  False, "malformed (score=7.5, na=TRUE)"),
            (None, False, False, "malformed (score=NULL, na=FALSE)"),
        ]
        for i, (sc, na, expect_ok, label) in enumerate(cases):
            cur.execute(f"SAVEPOINT sp_{i}")
            # Each test uses a unique criterion via dummy, but we only have 1 criterion.
            # So we DELETE the prior row inside the savepoint to retry.
            cur.execute("DELETE FROM evaluation_scores WHERE evaluation_id = %s", (ev_id,))
            try:
                cur.execute("""
                    INSERT INTO evaluation_scores (evaluation_id, criterion_id, score, is_not_applicable)
                    VALUES (%s, %s, %s, %s)
                """, (ev_id, crit_id, sc, na))
                if expect_ok:
                    print(f"  CHECK: {label} → accepted (expected)")
                else:
                    fails.append(f"CHECK should have rejected: {label}")
                cur.execute(f"RELEASE SAVEPOINT sp_{i}")
            except psycopg2.errors.CheckViolation:
                cur.execute(f"ROLLBACK TO SAVEPOINT sp_{i}")
                if not expect_ok:
                    print(f"  CHECK: {label} → rejected (expected)")
                else:
                    fails.append(f"CHECK should have accepted: {label}")

    conn.commit()

    if fails:
        print("\nFAILS:")
        for f in fails: print(f"  ! {f}")
        exit_code = 2
    else:
        print("\nThrowaway-schema convergence + CHECK enforcement confirmed.")
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
