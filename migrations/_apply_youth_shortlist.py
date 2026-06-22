"""
Apply youth_shortlist.sql against the live DB. Same transaction semantics
as the other _apply_*.py scripts — COMMITs on success.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import psycopg2

load_dotenv()

sql_path = Path(__file__).parent / "youth_shortlist.sql"
raw = sql_path.read_text(encoding="utf-8")
lines = [ln for ln in raw.splitlines() if not ln.lstrip().startswith("\\")]
sql = "\n".join(lines)
sql = sql.replace("BEGIN;",  "-- BEGIN; (psycopg2 manages txn)")
sql = sql.replace("COMMIT;", "-- COMMIT; (issued by _apply script after run)")

conn = psycopg2.connect(os.environ["DATABASE_URL"])
conn.autocommit = False
try:
    cur = conn.cursor()
    cur.execute(sql)
    conn.commit()
    print("COMMIT OK -- youth_shortlist table is live.")
except Exception as exc:
    conn.rollback()
    print(f"FAILED -- rolled back. Error: {exc}", file=sys.stderr)
    sys.exit(1)
finally:
    conn.close()
