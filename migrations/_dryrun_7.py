"""
Dry-run phase_7_nt_role.sql against the live DB inside a transaction
that is then ROLLED BACK. Verifies SQL syntax, pre-flight gate,
backfill correctness, audit gate, and constraint widening — all
without leaving any state behind.

Mirrors the 4.2 dry-run wrapper.
"""
import os
from pathlib import Path
from dotenv import load_dotenv
import psycopg2

load_dotenv()

sql_path = Path(__file__).parent / "phase_7_nt_role.sql"
raw = sql_path.read_text(encoding="utf-8")

# Strip psql meta-commands (\set, \timing) and neutralise the script's
# own BEGIN/COMMIT so psycopg2's outer transaction owns the rollback.
lines = [ln for ln in raw.splitlines() if not ln.lstrip().startswith("\\")]
sql = "\n".join(lines)
sql = sql.replace("BEGIN;",  "-- BEGIN; (psycopg2 manages txn)")
sql = sql.replace("COMMIT;", "-- COMMIT; (rolled back by dry-run wrapper)")

conn = psycopg2.connect(os.environ["DATABASE_URL"])
conn.autocommit = False
try:
    cur = conn.cursor()
    cur.execute(sql)
    print(f"cursor.statusmessage: {cur.statusmessage}")

    print("\nNOTICE messages:")
    for n in conn.notices:
        text = n.strip()
        if text:
            print(f"  {text}")

    if cur.description:
        cols = [d.name for d in cur.description]
        rows = cur.fetchall()
        print(f"\nFinal SELECT ({len(rows)} rows):")
        print("  " + " | ".join(c for c in cols))
        for row in rows:
            print("  " + " | ".join(str(v) for v in row))

    conn.rollback()
    print("\nRolled back -- DB unchanged.")
finally:
    conn.close()
