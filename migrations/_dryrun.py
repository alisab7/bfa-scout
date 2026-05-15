"""
Dry-run the phase_5a migration: execute it inside a transaction, then
ROLLBACK so the DB is unchanged. Confirms the SQL parses, the audit DO
block passes, and the COMMIT would have succeeded.
"""
import os
from pathlib import Path
from dotenv import load_dotenv
import psycopg2

load_dotenv()

sql_path = Path(__file__).parent / "phase_5a_reseed.sql"
raw = sql_path.read_text(encoding="utf-8")

# Strip psql meta-commands (\set, \timing) — psycopg2 can't parse them
lines = []
for ln in raw.splitlines():
    stripped = ln.lstrip()
    if stripped.startswith("\\"):
        continue
    lines.append(ln)
sql = "\n".join(lines)

# Also remove the explicit BEGIN/COMMIT — psycopg2 manages its own txn,
# and an explicit COMMIT inside a psycopg2 transaction would commit our
# dry-run for real.
sql = sql.replace("BEGIN;", "-- BEGIN; (psycopg2 manages txn)")
sql = sql.replace("COMMIT;", "-- COMMIT; (rolled back by dry-run wrapper)")

conn = psycopg2.connect(os.environ["DATABASE_URL"])
conn.autocommit = False
try:
    cur = conn.cursor()
    cur.execute(sql)
    print(f"Cursor.statusmessage after final batch: {cur.statusmessage}")
    print("Audit-related NOTICE messages:")
    for n in conn.notices:
        text = n.strip()
        if "AUDIT" in text or "ABORT" in text:
            print(f"  {text}")
    # Also fetch the eyeball audit table that the script SELECTs at the end
    if cur.description:
        print("\nFinal SELECT (audit table):")
        cols = [d.name for d in cur.description]
        print("  " + " | ".join(c.rjust(5) for c in cols))
        for row in cur.fetchall():
            print("  " + " | ".join(str(v).rjust(5) for v in row))
    conn.rollback()
    print("\nRolled back — DB unchanged.")
finally:
    conn.close()
