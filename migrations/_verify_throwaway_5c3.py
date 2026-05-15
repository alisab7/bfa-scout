"""
Throwaway-namespace verification for Phase 5c-3.

Asserts:
  - clubs table exists with 24 seeded rows (12 premier + 12 first)
  - players has nationality_code (CHAR(3)) + club_id (FK SET NULL)
  - evaluations has deleted_at + deleted_by + deleted_reason
  - evaluations_soft_delete_consistency CHECK present, blocks malformed
  - players references clubs (FK resolvable on fresh install)
"""
import os, sys, secrets
from pathlib import Path
from dotenv import load_dotenv
import psycopg2
import psycopg2.errors as PgErr

load_dotenv()
SCHEMA = f"phase5c3_check_{secrets.token_hex(4)}"
schema_sql = (Path(__file__).parent.parent / "schema.sql").read_text(encoding="utf-8")

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

        # 1. clubs seeded
        cur.execute("SELECT COUNT(*) FROM clubs")
        n_clubs = cur.fetchone()[0]
        if n_clubs != 24:
            fails.append(f"clubs count = {n_clubs} (expected 24)")
        else:
            cur.execute("SELECT division, COUNT(*) FROM clubs GROUP BY division ORDER BY division")
            split = dict(cur.fetchall())
            print(f"  clubs: 24 rows, division split = {split}")
            if split.get('premier') != 12 or split.get('first') != 12:
                fails.append(f"division split wrong: {split}")

        # 2. players new columns
        for col, dtype in [("nationality_code", "character"),
                           ("club_id", "integer")]:
            cur.execute("""
                SELECT data_type FROM information_schema.columns
                WHERE table_schema = %s AND table_name = 'players' AND column_name = %s
            """, (SCHEMA, col))
            r = cur.fetchone()
            if not r:
                fails.append(f"players.{col} missing")
            else:
                print(f"  players.{col}: OK ({r[0]})")

        # 3. players.club_id FK ON DELETE SET NULL
        cur.execute("""
            SELECT con.confdeltype FROM pg_constraint con
            JOIN pg_class rel ON rel.oid = con.conrelid
            JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
            JOIN pg_attribute att ON att.attrelid = rel.oid AND att.attnum = ANY(con.conkey)
            WHERE nsp.nspname = %s AND rel.relname = 'players' AND att.attname = 'club_id'
              AND con.contype = 'f'
        """, (SCHEMA,))
        r = cur.fetchone()
        if not r or r[0] != 'n':
            fails.append(f"players.club_id FK delete-action wrong: {r[0] if r else 'missing'}")
        else:
            print("  players.club_id FK ON DELETE SET NULL: OK")

        # 4. evaluations soft-delete trio + CHECK
        for col in ("deleted_at", "deleted_by", "deleted_reason"):
            cur.execute("""SELECT 1 FROM information_schema.columns
                           WHERE table_schema=%s AND table_name='evaluations' AND column_name=%s""",
                        (SCHEMA, col))
            if cur.fetchone() is None:
                fails.append(f"evaluations.{col} missing")
        cur.execute("""SELECT pg_get_constraintdef(con.oid) FROM pg_constraint con
                       JOIN pg_class rel ON rel.oid = con.conrelid
                       JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
                       WHERE nsp.nspname = %s AND rel.relname = 'evaluations'
                         AND con.conname = 'evaluations_soft_delete_consistency'""", (SCHEMA,))
        chk = cur.fetchone()
        if not chk:
            fails.append("evaluations_soft_delete_consistency CHECK missing")
        else:
            print("  soft-delete CHECK present")

        # 5. CHECK actually rejects half-deleted state
        # Need a real evaluation row to attempt the bad UPDATE; create scaffolding
        cur.execute("INSERT INTO users (email,password_hash,full_name,role) VALUES ('t@t','x','T','admin') RETURNING id")
        u_id = cur.fetchone()[0]
        cur.execute("INSERT INTO players (full_name, national_id) VALUES ('TestP','TX9') RETURNING id")
        p_id = cur.fetchone()[0]
        cur.execute("""INSERT INTO evaluations (player_id, evaluator_id, position_group_id)
                       SELECT %s, %s, id FROM position_groups LIMIT 1 RETURNING id""",
                    (p_id, u_id))
        ev_id = cur.fetchone()[0]

        cur.execute("SAVEPOINT t1")
        try:
            cur.execute("UPDATE evaluations SET deleted_at = NOW() WHERE id = %s", (ev_id,))
            fails.append("CHECK should have rejected half-deleted state (deleted_at only)")
        except PgErr.CheckViolation:
            print("  CHECK rejects half-deleted (deleted_at only): OK")
        cur.execute("ROLLBACK TO SAVEPOINT t1")

        cur.execute("SAVEPOINT t2")
        try:
            cur.execute("""UPDATE evaluations SET deleted_at = NOW(), deleted_by = %s,
                                                  deleted_reason = 'short' WHERE id = %s""",
                        (u_id, ev_id))
            fails.append("CHECK should have rejected reason < 10 chars")
        except PgErr.CheckViolation:
            print("  CHECK rejects reason < 10 chars: OK")
        cur.execute("ROLLBACK TO SAVEPOINT t2")

        # Valid path
        cur.execute("""UPDATE evaluations SET deleted_at = NOW(), deleted_by = %s,
                                              deleted_reason = 'valid reason here' WHERE id = %s""",
                    (u_id, ev_id))
        print("  CHECK accepts full delete with valid reason: OK")

    conn.commit()

    if fails:
        print("\nFAILS:"); [print(f"  ! {f}") for f in fails]
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
