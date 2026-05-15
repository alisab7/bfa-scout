"""
Dry-run phase_4_2_season_column.sql against the live DB inside a
transaction that is then ROLLED BACK. Verifies SQL syntax, that the
pre-flight gate passes, that the audit gate fires correctly, and shows
the eyeball SELECT — without leaving any state behind.

Same shape as _dryrun_5b.py — only the SQL filename differs.
"""
import os
from pathlib import Path
from dotenv import load_dotenv
import psycopg2

load_dotenv()

sql_path = Path(__file__).parent / "phase_4_2_season_column.sql"
raw = sql_path.read_text(encoding="utf-8")

# Strip psql meta-commands (\set, \timing) and turn the script's own
# BEGIN/COMMIT into no-ops — psycopg2 manages the outer transaction
# and we want to rollback at the end no matter what.
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
    print("\nRolled back — DB unchanged.")
finally:
    conn.close()
