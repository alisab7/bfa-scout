"""
Apply eval_position_played.sql against the live DB. Same transaction
semantics as the other _apply_*.py scripts — COMMITs on success.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import psycopg2

load_dotenv()

sql_path = Path(__file__).parent / "eval_position_played.sql"
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
    print("Postgres NOTICEs:")
    for n in conn.notices:
        t = n.strip()
        if t:
            print(f"  {t}")
    conn.commit()
    print("\nCOMMIT OK -- position_played_id wired + backfilled.")
except Exception as exc:
    conn.rollback()
    print(f"\nFAILED -- rolled back. Error: {exc}", file=sys.stderr)
    sys.exit(1)
finally:
    conn.close()
