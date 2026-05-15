"""
Apply phase_5a_reseed.sql against the live DB.

Same transaction semantics as _dryrun.py — but COMMITs on success.
The migration's own DO-block audit will RAISE if the per-position counts
disagree with the v2-LOCKED expected values; that exception propagates
through psycopg2 and triggers our rollback path.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import psycopg2

load_dotenv()

sql_path = Path(__file__).parent / "phase_5a_reseed.sql"
raw = sql_path.read_text(encoding="utf-8")

# Strip psql meta-commands and the script's own BEGIN/COMMIT (psycopg2 manages txn)
lines = [ln for ln in raw.splitlines() if not ln.lstrip().startswith("\\")]
sql = "\n".join(lines)
sql = sql.replace("BEGIN;",  "-- BEGIN; (psycopg2 manages txn)")
sql = sql.replace("COMMIT;", "-- COMMIT; (issued by _apply.py after audit pass)")

conn = psycopg2.connect(os.environ["DATABASE_URL"])
conn.autocommit = False
try:
    cur = conn.cursor()
    cur.execute(sql)
    # Capture the audit table from the final SELECT
    audit_rows = cur.fetchall() if cur.description else []
    audit_cols = [d.name for d in cur.description] if cur.description else []

    # Print Postgres NOTICEs (audit pass / fail come through here)
    print("Postgres NOTICEs:")
    for n in conn.notices:
        text = n.strip()
        if text:
            print(f"  {text}")

    print("\nFinal eyeball audit table:")
    print("  " + " | ".join(c.rjust(5) for c in audit_cols))
    for row in audit_rows:
        print("  " + " | ".join(str(v).rjust(5) for v in row))

    # All gates passed; commit for real
    conn.commit()
    print("\nCOMMIT OK — Phase 5a reseed is live.")
except Exception as exc:
    conn.rollback()
    print(f"\nFAILED — rolled back. Error: {exc}", file=sys.stderr)
    sys.exit(1)
finally:
    conn.close()
