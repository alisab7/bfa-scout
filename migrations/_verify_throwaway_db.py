"""
Throwaway-namespace verification (the bfa role can't CREATE DATABASE,
so we isolate inside a per-run schema instead of a per-run database).

1. CREATE SCHEMA phase5a_check_<random> in the live DB
2. SET search_path so unqualified table names land inside it
3. Run schema.sql top-to-bottom — every CREATE TABLE / INSERT / VIEW
   resolves entirely within the new schema, leaving live `public` alone
4. Run the same audit query the migration uses
5. Assert per-position counts match the v2-LOCKED expected values
6. DROP SCHEMA ... CASCADE in finally:, no matter what

This proves the declarative schema.sql converges to the same final state
as the imperative migration. If both agree, `flask init-db` on a fresh
DB (created by an admin) reproduces the live DB exactly.
"""
import os
import sys
import secrets
from pathlib import Path
from dotenv import load_dotenv
import psycopg2

load_dotenv()

SCHEMA_NAME = f"phase5a_check_{secrets.token_hex(4)}"
EXPECTED = {
    "GK": (10,  5, 3, 6, 24),
    "CB": ( 9, 18, 9, 6, 42),
    "FB": (10, 18, 8, 6, 42),
    "DM": ( 9, 18, 7, 6, 40),
    "CM": (10, 16, 5, 6, 37),
    "AM": (14, 16, 6, 6, 42),
    "W":  ( 9, 16, 7, 6, 38),
    "ST": ( 9, 15, 8, 6, 38),
}

schema_path = Path(__file__).parent.parent / "schema.sql"
schema_sql  = schema_path.read_text(encoding="utf-8")

conn = psycopg2.connect(os.environ["DATABASE_URL"])
conn.autocommit = False
exit_code = 0
try:
    with conn.cursor() as cur:
        cur.execute(f'CREATE SCHEMA "{SCHEMA_NAME}"')
        # search_path = our schema, then public (so any reference to e.g. uuid
        # functions in pg_catalog still resolves). Live `public` tables would
        # shadow ours, so we put our schema FIRST — every CREATE TABLE goes
        # into our schema and resolution within the script stays internal.
        cur.execute(f'SET search_path TO "{SCHEMA_NAME}", public')
        # Run the entire declarative schema in one shot
        cur.execute(schema_sql)
    conn.commit()
    print(f"schema.sql applied cleanly to throwaway schema {SCHEMA_NAME!r}.")

    # Run the audit query inside the same schema
    with conn.cursor() as cur:
        cur.execute(f'SET search_path TO "{SCHEMA_NAME}"')
        cur.execute("""
            SELECT pg.code AS grp,
                   COUNT(*) FILTER (WHERE c.code LIKE 'tech_%') AS tech,
                   COUNT(*) FILTER (WHERE c.code LIKE 'tact_%') AS tact,
                   COUNT(*) FILTER (WHERE c.code LIKE 'phys_%') AS phys,
                   COUNT(*) FILTER (WHERE c.code LIKE 'ment_%') AS ment,
                   COUNT(*)                                     AS total
            FROM   position_groups pg
            LEFT JOIN position_group_criteria pgc ON pgc.position_group_id = pg.id
            LEFT JOIN criteria c                  ON c.id = pgc.criterion_id
            GROUP BY pg.code, pg.sort_order
            ORDER BY pg.sort_order
        """)
        rows = cur.fetchall()

    print("\nFresh-schema audit table:")
    print("     grp |  tech |  tact |  phys |  ment | total")
    diffs = []
    for grp, tech, tact, phys, ment, total in rows:
        actual = (tech, tact, phys, ment, total)
        ok = actual == EXPECTED.get(grp)
        mark = "   " if ok else " ! "
        print(f"  {mark}{grp:>3} | {tech:>5} | {tact:>5} | {phys:>5} | {ment:>5} | {total:>5}")
        if not ok:
            diffs.append((grp, actual, EXPECTED.get(grp)))

    if diffs:
        print("\nMISMATCH vs v2-LOCKED:")
        for grp, got, want in diffs:
            print(f"  {grp}: got {got} expected {want}")
        exit_code = 2
    else:
        print("\nFresh-schema counts match the v2-LOCKED spec exactly.")
        print("schema.sql and the live-DB state converge.")
finally:
    # Always drop the throwaway schema (autocommit so it survives any txn abort)
    try:
        conn.rollback()
    except Exception:
        pass
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA_NAME}" CASCADE')
        print(f"Dropped throwaway schema {SCHEMA_NAME!r}.")
    finally:
        conn.close()

sys.exit(exit_code)
