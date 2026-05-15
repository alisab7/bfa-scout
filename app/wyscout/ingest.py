"""
Wyscout ingest pipeline.

ingest_wyscout(player_id, file_path, file_name, uploaded_by_id)
  → dict with keys: import_id, inserted, updated, skipped, status, error
"""
import json
import logging
from datetime import date

from app.db import _get_pool
from app.wyscout.parser import parse_wyscout_xlsx
from app.wyscout.season import derive_season  # Phase 4.2

log = logging.getLogger(__name__)

# DB integer columns in wyscout_match_stats (excludes computed/FK/meta cols)
_INT_COLS = [
    "minutes_played",
    "total_actions", "total_actions_successful",
    "goals", "assists", "shots", "shots_on_target",
    "shot_assists", "touches_in_box", "offsides", "progressive_runs",
    "passes", "passes_accurate",
    "long_passes", "long_passes_accurate",
    "crosses", "crosses_accurate",
    "through_passes", "through_passes_accurate",
    "dribbles", "dribbles_successful",
    "duels", "duels_won",
    "aerial_duels", "aerial_duels_won",
    "defensive_duels", "defensive_duels_won",
    "offensive_duels", "offensive_duels_won",
    "loose_ball_duels", "loose_ball_duels_won",
    "interceptions",
    "sliding_tackles", "sliding_tackles_successful",
    "clearances", "recoveries_opp_half", "losses_own_half",
    "fouls", "fouls_suffered", "yellow_cards", "red_cards",
]


def _resolve_position_id(conn, position_raw: str | None) -> int | None:
    """Lookup positions.id from the first code in position_raw (e.g. 'LCMF, RCMF' → 'LCMF')."""
    if not position_raw:
        return None
    first_code = position_raw.split(",")[0].strip()
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM positions WHERE code = %s", (first_code,))
        row = cur.fetchone()
    return row["id"] if row else None


def _resolve_match_id(conn, row: dict, uploaded_by_id: int) -> int | None:
    """
    Find or create a matches row for a parsed Wyscout stat row (Phase 5b).
    Returns matches.id, or None if the row lacks match_date or both teams.

    Identity: case-insensitive + trimmed (date, home, away). Existing
    matches are reused regardless of source ('manual' or 'wyscout').
    Newly-inserted rows are tagged source='wyscout'. The UNIQUE constraint
    on raw values is best-effort; the lookup below is the actual identity
    check, which means a manual match created with slightly different team
    casing will still get linked instead of duplicated.
    """
    if not row.get("match_date"):
        return None
    home = row.get("home_team")
    away = row.get("away_team")
    if not home and not away:
        return None

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM matches
            WHERE match_date = %s
              AND LOWER(BTRIM(home_team)) = LOWER(BTRIM(%s))
              AND LOWER(BTRIM(away_team)) = LOWER(BTRIM(%s))
            LIMIT 1
            """,
            (row["match_date"], home or "", away or "")
        )
        existing = cur.fetchone()
        if existing:
            return existing["id"]

        cur.execute(
            """
            INSERT INTO matches
                (match_date, home_team, away_team, home_score, away_score,
                 competition, source, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, 'wyscout', %s)
            ON CONFLICT (match_date, home_team, away_team) DO UPDATE
                SET updated_at = NOW()
            RETURNING id
            """,
            (
                row["match_date"],
                home or "Unknown",
                away or "Unknown",
                row.get("home_score"),
                row.get("away_score"),
                row.get("competition"),
                uploaded_by_id,
            )
        )
        return cur.fetchone()["id"]


def ingest_wyscout(player_id: int, file_path: str, file_name: str,
                   uploaded_by_id: int) -> dict:
    """
    Parse xlsx, UPSERT rows into wyscout_match_stats, record import.

    Returns:
        {import_id, inserted, updated, skipped, status, error}
    """
    # 1. Parse ---------------------------------------------------------------
    try:
        rows = parse_wyscout_xlsx(file_path)
    except ValueError as exc:
        return _fail(None, str(exc), uploaded_by_id, file_name, player_id, 0)

    pool = _get_pool()
    conn = pool.getconn()
    try:

        # 2. Create import record (status=pending) ---------------------------
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO wyscout_imports
                    (uploaded_by, file_name, player_id, row_count, status)
                VALUES (%s, %s, %s, %s, 'pending')
                RETURNING id
                """,
                (uploaded_by_id, file_name, player_id, len(rows))
            )
            import_id = cur.fetchone()["id"]

        # 3. UPSERT rows -----------------------------------------------------
        inserted = updated = skipped = 0

        for row in rows:
            match_label = row.get("match_label")
            match_date  = row.get("match_date")

            if not match_label or not match_date:
                skipped += 1
                continue

            # Resolve position FK + matches FK (Phase 5b auto-link)
            position_primary_id = _resolve_position_id(conn, row.get("position_raw"))
            match_id = _resolve_match_id(conn, row, uploaded_by_id)

            # Phase 4.2: derive season at ingest time so UPSERT writes it.
            # The pre-check above ensures match_date is non-None when we get
            # here, but defend anyway for parser-path changes.
            season = derive_season(match_date) if match_date else None

            # Build per-row values
            vals = {
                "player_id":            player_id,
                "import_id":            import_id,
                "match_id":             match_id,
                "match_label":          match_label,
                "competition":          row.get("competition"),
                "match_date":           match_date,
                "season":               season,   # Phase 4.2
                "home_team":            row.get("home_team"),
                "away_team":            row.get("away_team"),
                "home_score":           row.get("home_score"),
                "away_score":           row.get("away_score"),
                "is_home":              row.get("is_home"),
                "position_raw":         row.get("position_raw"),
                "position_primary_id":  position_primary_id,
                "raw_row":              row.get("raw_row"),
            }
            for col in _INT_COLS:
                vals[col] = row.get(col)
            vals["xg"] = row.get("xg")

            # Build column lists for INSERT
            cols   = list(vals.keys())
            ph     = ["%s"] * len(cols)
            params = [vals[c] for c in cols]

            # UPDATE SET (everything except the conflict key cols)
            update_cols = [c for c in cols
                           if c not in ("player_id", "match_label", "match_date")]
            update_set  = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)

            sql = f"""
                INSERT INTO wyscout_match_stats ({", ".join(cols)})
                VALUES ({", ".join(ph)})
                ON CONFLICT (player_id, match_label, match_date)
                DO UPDATE SET {update_set}
                RETURNING (xmax = 0) AS was_inserted
            """
            with conn.cursor() as cur:
                cur.execute(sql, params)
                result_row = cur.fetchone()
                if result_row and result_row["was_inserted"]:
                    inserted += 1
                else:
                    updated += 1

        # 4. Mark import success --------------------------------------------
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE wyscout_imports
                SET status = 'success', row_count = %s
                WHERE id = %s
                """,
                (inserted + updated, import_id)
            )

        # 5. Audit log -------------------------------------------------------
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audit_log (user_id, action, entity_type, entity_id, details)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    uploaded_by_id,
                    "wyscout_import",
                    "wyscout_imports",
                    import_id,
                    json.dumps({
                        "player_id": player_id,
                        "file_name": file_name,
                        "inserted":  inserted,
                        "updated":   updated,
                        "skipped":   skipped,
                    })
                )
            )

        conn.commit()
        return {
            "import_id": import_id,
            "inserted":  inserted,
            "updated":   updated,
            "skipped":   skipped,
            "status":    "success",
            "error":     None,
        }

    except Exception as exc:
        conn.rollback()
        log.exception("Wyscout ingest failed: %s", exc)
        # Try to mark import as failed
        try:
            with conn.cursor() as cur:
                if "import_id" in locals():
                    cur.execute(
                        """
                        UPDATE wyscout_imports
                        SET status = 'failed', error_message = %s
                        WHERE id = %s
                        """,
                        (str(exc)[:1000], import_id)
                    )
                    conn.commit()
        except Exception:
            pass
        return {
            "import_id": locals().get("import_id"),
            "inserted":  0,
            "updated":   0,
            "skipped":   0,
            "status":    "failed",
            "error":     str(exc),
        }
    finally:
        pool.putconn(conn)


def _fail(import_id, error_msg, uploaded_by_id, file_name, player_id, row_count):
    """Record a failed import (parse error before DB transaction)."""
    pool = _get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO wyscout_imports
                    (uploaded_by, file_name, player_id, row_count, status, error_message)
                VALUES (%s, %s, %s, %s, 'failed', %s)
                RETURNING id
                """,
                (uploaded_by_id, file_name, player_id, row_count, error_msg[:1000])
            )
            import_id = cur.fetchone()["id"]
        conn.commit()
    except Exception:
        import_id = None
    finally:
        pool.putconn(conn)
    return {
        "import_id": import_id,
        "inserted":  0,
        "updated":   0,
        "skipped":   0,
        "status":    "failed",
        "error":     error_msg,
    }
