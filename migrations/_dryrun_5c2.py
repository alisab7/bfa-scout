"""Dry-run phase_5c2_lock_and_eligibility.sql with rollback wrapper."""
import os
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
    print("statusmessage:", cur.statusmessage)
    print("\nNOTICEs:")
    for n in conn.notices: print(" ", n.strip())
    if cur.description:
        print("\nFinal SELECT:")
        cols = [d.name for d in cur.description]
        print(" ", " | ".join(cols))
        for row in cur.fetchall(): print(" ", " | ".join(str(v) for v in row))
    conn.rollback()
    print("\nRolled back — DB unchanged.")
finally:
    conn.close()
