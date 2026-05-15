"""Apply phase_5c2_lock_and_eligibility.sql against the live DB."""
import os, sys
from pathlib import Path
from dotenv import load_dotenv
import psycopg2

load_dotenv()
raw = Path(__file__).parent.joinpath("phase_5c2_lock_and_eligibility.sql").read_text(encoding="utf-8")
lines = [ln for ln in raw.splitlines() if not ln.lstrip().startswith("\\")]
sql = "\n".join(lines).replace("BEGIN;", "-- BEGIN;").replace("COMMIT;", "-- COMMIT;")

conn = psycopg2.connect(os.environ["DATABASE_URL"])
conn.autocommit = False
try:
    cur = conn.cursor(); cur.execute(sql)
    rows = cur.fetchall() if cur.description else []
    print("NOTICEs:")
    for n in conn.notices: print(" ", n.strip())
    print(f"\nFinal SELECT ({len(rows)} rows):")
    for r in rows: print(" ", r)
    conn.commit()
    print("\nCOMMIT OK — Phase 5c-2 schema migration is live.")
except Exception as exc:
    conn.rollback()
    print(f"FAILED: {exc}", file=sys.stderr); sys.exit(1)
finally:
    conn.close()
