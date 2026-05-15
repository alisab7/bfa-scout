"""
Apply phase_4_2_season_column.sql against the live DB.

Same transaction semantics as _dryrun_4_2.py — but COMMITs on success.
The migration's pre-flight + audit DO-blocks RAISE on any drift, which
propagates through psycopg2 and triggers our rollback path.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import psycopg2

load_dotenv()

sql_path = Path(__file__).parent / "phase_4_2_season_column.sql"
raw = sql_path.read_text(encoding="utf-8")
lines = [ln for ln in raw.splitlines() if not ln.lstrip().startswith("\\")]
sql = "\n".join(lines)
sql = sql.replace("BEGIN;",  "-- BEGIN; (psycopg2 manages txn)")
sql = sql.replace("COMMIT;", "-- COMMIT; (issued by _apply_4_2.py after audit pass)")

conn = psycopg2.connect(os.environ["DATABASE_URL"])
conn.autocommit = False
try:
    cur = conn.cursor()
    cur.execute(sql)

    # Capture the final eyeball SELECT (season-by-season breakdown).
    audit_rows = cur.fetchall() if cur.description else []
    audit_cols = [d.name for d in cur.description] if cur.description else []

    print("Postgres NOTICEs:")
    for n in conn.notices:
        text = n.strip()
        if text:
            print(f"  {text}")

    print(f"\nFinal eyeball table ({len(audit_rows)} rows):")
    print("  " + " | ".join(audit_cols))
    for row in audit_rows:
        print("  " + " | ".join(str(v) for v in row))

    conn.commit()
    print("\nCOMMIT OK — Phase 4.2 season column + backfill is live.")
except Exception as exc:
    conn.rollback()
    print(f"\nFAILED — rolled back. Error: {exc}", file=sys.stderr)
    sys.exit(1)
finally:
    conn.close()
