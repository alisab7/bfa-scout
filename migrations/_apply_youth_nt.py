"""
Apply phase_youth_nt.sql against the live DB. Same transaction
semantics as _apply_7.py — COMMITs on success, rolls back on any
RAISE from the pre-flight / audit DO-blocks.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import psycopg2

load_dotenv()

sql_path = Path(__file__).parent / "phase_youth_nt.sql"
raw = sql_path.read_text(encoding="utf-8")
lines = [ln for ln in raw.splitlines() if not ln.lstrip().startswith("\\")]
sql = "\n".join(lines)
sql = sql.replace("BEGIN;",  "-- BEGIN; (psycopg2 manages txn)")
sql = sql.replace("COMMIT;", "-- COMMIT; (issued by _apply_youth_nt.py after audit pass)")

conn = psycopg2.connect(os.environ["DATABASE_URL"])
conn.autocommit = False
try:
    cur = conn.cursor()
    cur.execute(sql)

    # Drain result sets from the two trailing SELECTs (eyeball tables).
    print("Postgres NOTICEs:")
    for n in conn.notices:
        text = n.strip()
        if text:
            print(f"  {text}")

    conn.commit()
    print("\nCOMMIT OK -- players.age_group + youth_nt role are live.")
except Exception as exc:
    conn.rollback()
    print(f"\nFAILED -- rolled back. Error: {exc}", file=sys.stderr)
    sys.exit(1)
finally:
    conn.close()
