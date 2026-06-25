"""
Wyscout aggregation queries.

All functions return plain dicts/lists — no Flask context required.
They acquire connections directly from the pool so they can be called
from both request and non-request contexts.
"""
import logging
from app.db import _get_pool
from app.wyscout.helpers import RADAR_AXES, normalize_radar_axis

log = logging.getLogger(__name__)


def _season_label(start_year: int) -> str:
    """'<start_year>/<end_year_short>'  e.g. 2024 → '2024/25'."""
    return f"{start_year}/{(start_year + 1) % 100:02d}"


def _conn():
    return _get_pool().getconn()


def _putconn(conn):
    _get_pool().putconn(conn)


# ---------------------------------------------------------------------------
# Summary card — career totals + averages across all uploaded matches
# ---------------------------------------------------------------------------
def get_player_summary(player_id: int) -> dict | None:
    """
    Returns aggregated career stats for a player from wyscout_match_stats.
    Returns None if no data found.
    """
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*)                            AS matches,
                    COALESCE(SUM(minutes_played), 0)    AS total_minutes,
                    COALESCE(SUM(goals), 0)             AS total_goals,
                    COALESCE(SUM(assists), 0)           AS total_assists,
                    COALESCE(SUM(shots), 0)             AS total_shots,
                    COALESCE(SUM(passes), 0)            AS total_passes,
                    COALESCE(SUM(passes_accurate), 0)   AS total_passes_accurate,
                    COALESCE(SUM(dribbles_successful), 0) AS total_dribbles_successful,
                    COALESCE(SUM(duels_won), 0)         AS total_duels_won,
                    COALESCE(SUM(duels), 0)             AS total_duels,
                    COALESCE(SUM(interceptions), 0)     AS total_interceptions,
                    COALESCE(SUM(yellow_cards), 0)      AS total_yellow_cards,
                    COALESCE(SUM(red_cards), 0)         AS total_red_cards,
                    -- xG may be null for older imports
                    COALESCE(SUM(xg), 0)                AS total_xg,
                    MIN(match_date)                     AS first_match,
                    MAX(match_date)                     AS last_match
                FROM wyscout_match_stats
                WHERE player_id = %s
                """,
                (player_id,)
            )
            row = cur.fetchone()
        if not row or row["matches"] == 0:
            return None

        matches = row["matches"]
        mins    = row["total_minutes"] or 0

        summary = dict(row)
        # Per-90 derived metrics
        p90 = lambda stat: round((stat / mins * 90), 2) if mins > 0 else 0.0
        summary["goals_p90"]       = p90(row["total_goals"])
        summary["assists_p90"]     = p90(row["total_assists"])
        summary["pass_accuracy"]   = (
            round(row["total_passes_accurate"] / row["total_passes"] * 100, 1)
            if row["total_passes"] > 0 else 0.0
        )
        summary["duel_win_rate"]   = (
            round(row["total_duels_won"] / row["total_duels"] * 100, 1)
            if row["total_duels"] > 0 else 0.0
        )
        return summary
    finally:
        _putconn(conn)


# ---------------------------------------------------------------------------
# Match history — for table display (last N matches)
# ---------------------------------------------------------------------------
def get_player_match_history(player_id: int, limit: int = 20) -> list[dict]:
    """
    Returns list of recent matches ordered desc by match_date.
    """
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id, match_label, competition, match_date,
                    home_team, away_team, home_score, away_score, is_home,
                    position_raw, minutes_played,
                    goals, assists, shots, passes, passes_accurate,
                    dribbles_successful, duels_won, duels,
                    interceptions, yellow_cards, red_cards
                FROM wyscout_match_stats
                WHERE player_id = %s
                ORDER BY match_date DESC
                LIMIT %s
                """,
                (player_id, limit)
            )
            return cur.fetchall() or []
    finally:
        _putconn(conn)


# ---------------------------------------------------------------------------
# Radar scores — 6-axis normalized 0-100
# ---------------------------------------------------------------------------
def get_player_radar_scores(player_id: int) -> dict:
    """
    Returns dict: {axis_label: score_0_to_100, ...} for Chart.js radar.
    Aggregates career totals, then normalizes per RADAR_AXES thresholds.
    """
    conn = _conn()
    try:
        # Fetch sums of all radar-relevant columns + total minutes
        radar_cols = [col for _, col, _, _ in RADAR_AXES]
        select_parts = [f"COALESCE(SUM({c}), 0) AS {c}" for c in radar_cols]
        select_parts.append("COALESCE(SUM(minutes_played), 0) AS total_minutes")

        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {", ".join(select_parts)}
                FROM wyscout_match_stats
                WHERE player_id = %s
                """,
                (player_id,)
            )
            row = cur.fetchone()

        if not row:
            return {label: 0.0 for label, *_ in RADAR_AXES}

        total_minutes = float(row["total_minutes"] or 0)
        scores = {}
        for label, col, use_per90, max_val in RADAR_AXES:
            raw_val = row.get(col, 0) or 0
            scores[label] = normalize_radar_axis(raw_val, use_per90, total_minutes, max_val)

        return scores
    finally:
        _putconn(conn)


# ---------------------------------------------------------------------------
# Per-season aggregates — Career-by-Season table
# ---------------------------------------------------------------------------
def get_player_seasons(player_id: int) -> list[dict]:
    """
    Aggregate a player's matches grouped by football season (Aug 1 → May 31).

    Returns a list ordered most-recent-first. Percentage columns are NULL
    when the underlying denominator is zero (never divides by zero).
    """
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    CASE WHEN EXTRACT(MONTH FROM match_date) >= 8
                         THEN EXTRACT(YEAR FROM match_date)::int
                         ELSE EXTRACT(YEAR FROM match_date)::int - 1
                    END                                       AS season_start_year,
                    COUNT(*)                                  AS matches,
                    COALESCE(SUM(minutes_played), 0)          AS total_minutes,
                    COALESCE(SUM(goals), 0)                   AS goals,
                    COALESCE(SUM(assists), 0)                 AS assists,
                    COALESCE(SUM(shots), 0)                   AS shots,
                    COALESCE(SUM(shots_on_target), 0)         AS shots_on_target,
                    COALESCE(SUM(xg), 0)::numeric(8,2)        AS xg_total,
                    COALESCE(SUM(passes), 0)                  AS passes_total,
                    COALESCE(SUM(passes_accurate), 0)         AS passes_accurate,
                    COALESCE(SUM(duels), 0)                   AS duels_total,
                    COALESCE(SUM(duels_won), 0)               AS duels_won,
                    COALESCE(SUM(aerial_duels), 0)            AS aerial_duels,
                    COALESCE(SUM(aerial_duels_won), 0)        AS aerial_duels_won,
                    COALESCE(SUM(defensive_duels), 0)         AS defensive_duels,
                    COALESCE(SUM(defensive_duels_won), 0)     AS defensive_duels_won,
                    COALESCE(SUM(yellow_cards), 0)            AS yellow_cards,
                    COALESCE(SUM(red_cards), 0)               AS red_cards
                FROM   wyscout_match_stats
                WHERE  player_id = %s AND match_date IS NOT NULL
                GROUP  BY season_start_year
                ORDER  BY season_start_year DESC
                """,
                (player_id,)
            )
            rows = cur.fetchall() or []

        out = []
        for r in rows:
            d = dict(r)
            sy = int(d["season_start_year"])
            matches = int(d["matches"]) or 0
            mins    = int(d["total_minutes"]) or 0
            d["season_start_year"]      = sy
            d["season_label"]           = _season_label(sy)
            d["goals_plus_assists"]     = int(d["goals"]) + int(d["assists"])
            d["xg_total"]               = float(d["xg_total"]) if d["xg_total"] is not None else 0.0
            d["avg_minutes_per_match"]  = round(mins / matches, 1) if matches > 0 else 0.0
            d["pass_accuracy_pct"]      = (
                round(d["passes_accurate"] * 100.0 / d["passes_total"], 1)
                if d["passes_total"] and d["passes_total"] > 0 else None
            )
            d["duels_won_pct"]          = (
                round(d["duels_won"] * 100.0 / d["duels_total"], 1)
                if d["duels_total"] and d["duels_total"] > 0 else None
            )
            d["aerial_duels_won_pct"]   = (
                round(d["aerial_duels_won"] * 100.0 / d["aerial_duels"], 1)
                if d["aerial_duels"] and d["aerial_duels"] > 0 else None
            )
            d["defensive_duels_won_pct"] = (
                round(d["defensive_duels_won"] * 100.0 / d["defensive_duels"], 1)
                if d["defensive_duels"] and d["defensive_duels"] > 0 else None
            )
            out.append(d)
        return out
    finally:
        _putconn(conn)


# ---------------------------------------------------------------------------
# Multi-season radar — last N seasons of normalized 0-100 scores
# ---------------------------------------------------------------------------
def get_player_radar_seasons(player_id: int, n_seasons: int = 2) -> list[dict]:
    """
    Returns up to N seasons of radar scores ordered most-recent-first.

    Each entry:
        {
          'season_label':      '2024/25',
          'season_start_year': 2024,
          'matches':           int,
          'total_minutes':     int,
          'scores':            {axis_label: 0-100, ...}  # axis labels per RADAR_AXES
        }

    Returns [] if the player has no matches.
    """
    if n_seasons <= 0:
        return []

    radar_cols = [col for _, col, _, _ in RADAR_AXES]
    select_parts = ", ".join(f"COALESCE(SUM({c}), 0) AS {c}" for c in radar_cols)

    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    CASE WHEN EXTRACT(MONTH FROM match_date) >= 8
                         THEN EXTRACT(YEAR FROM match_date)::int
                         ELSE EXTRACT(YEAR FROM match_date)::int - 1
                    END                                       AS season_start_year,
                    COUNT(*)                                  AS matches,
                    COALESCE(SUM(minutes_played), 0)          AS total_minutes,
                    {select_parts}
                FROM   wyscout_match_stats
                WHERE  player_id = %s AND match_date IS NOT NULL
                GROUP  BY season_start_year
                ORDER  BY season_start_year DESC
                LIMIT  %s
                """,
                (player_id, n_seasons)
            )
            rows = cur.fetchall() or []

        out = []
        for r in rows:
            sy   = int(r["season_start_year"])
            mins = float(r["total_minutes"] or 0)
            scores = {}
            for label, col, use_per90, max_val in RADAR_AXES:
                raw = r.get(col, 0) or 0
                scores[label] = normalize_radar_axis(raw, use_per90, mins, max_val)
            out.append({
                "season_label":      _season_label(sy),
                "season_start_year": sy,
                "matches":           int(r["matches"]),
                "total_minutes":     int(r["total_minutes"] or 0),
                "scores":            scores,
            })
        return out
    finally:
        _putconn(conn)


# ---------------------------------------------------------------------------
# Player comparison — validation + side-by-side data assembly
# ---------------------------------------------------------------------------
def validate_comparison(player_ids: list[int]) -> None:
    """
    Validates a comparison set. Raises ValueError on:
      - Fewer than 2 or more than 3 players
      - Duplicate ids
      - Any player not found / inactive
      - Mix of GK with non-GK (the only cross-position restriction)
    """
    if not player_ids or len(player_ids) < 2:
        raise ValueError("Pick at least 2 players to compare.")
    if len(player_ids) > 3:
        raise ValueError("You can compare at most 3 players at once.")
    if len(set(player_ids)) != len(player_ids):
        raise ValueError("Each player can only be picked once.")

    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT pl.id, pl.full_name, pl.is_active,
                       pg.code AS group_code
                FROM   players pl
                LEFT JOIN positions p        ON p.id  = pl.primary_position_id
                LEFT JOIN position_groups pg ON pg.id = p.position_group_id
                WHERE  pl.id = ANY(%s)
                """,
                (player_ids,)
            )
            rows = cur.fetchall() or []
    finally:
        _putconn(conn)

    found_ids = {r["id"] for r in rows}
    missing   = [pid for pid in player_ids if pid not in found_ids]
    if missing:
        raise ValueError(f"Player not found: {missing[0]}")

    inactive = [r["full_name"] for r in rows if not r["is_active"]]
    if inactive:
        raise ValueError(f"Inactive player cannot be compared: {inactive[0]}")

    has_gk       = any(r["group_code"] == "GK" for r in rows)
    has_outfield = any(r["group_code"] != "GK" and r["group_code"] is not None for r in rows)
    if has_gk and has_outfield:
        raise ValueError("Cannot compare goalkeepers with outfield players.")


def _compare_summary(player_id: int) -> dict:
    """
    Career totals reshaped to the keys the comparison view expects.
    Percentages are None when the denominator is zero.
    """
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*)                              AS matches_count,
                    COALESCE(SUM(minutes_played), 0)      AS total_minutes,
                    COALESCE(SUM(goals), 0)               AS goals,
                    COALESCE(SUM(assists), 0)             AS assists,
                    COALESCE(SUM(shots), 0)               AS shots,
                    COALESCE(SUM(shots_on_target), 0)     AS shots_on_target,
                    COALESCE(SUM(xg), 0)::numeric(8,2)    AS xg_total,
                    COALESCE(SUM(passes), 0)              AS passes_total,
                    COALESCE(SUM(passes_accurate), 0)     AS passes_accurate,
                    COALESCE(SUM(duels), 0)               AS duels_total,
                    COALESCE(SUM(duels_won), 0)           AS duels_won,
                    COALESCE(SUM(aerial_duels), 0)        AS aerial_duels,
                    COALESCE(SUM(aerial_duels_won), 0)    AS aerial_duels_won,
                    COALESCE(SUM(yellow_cards), 0)        AS yellow_cards,
                    COALESCE(SUM(red_cards), 0)           AS red_cards
                FROM wyscout_match_stats
                WHERE player_id = %s
                """,
                (player_id,)
            )
            r = cur.fetchone()
    finally:
        _putconn(conn)

    if not r:
        r = {"matches_count": 0}

    matches_count = int(r.get("matches_count") or 0)
    pa, pt = (r.get("passes_accurate") or 0), (r.get("passes_total") or 0)
    dw, dt = (r.get("duels_won") or 0),       (r.get("duels_total") or 0)
    aw, at = (r.get("aerial_duels_won") or 0),(r.get("aerial_duels") or 0)

    return {
        "matches_count":          matches_count,
        "total_minutes":          int(r.get("total_minutes") or 0),
        "goals":                  int(r.get("goals") or 0),
        "assists":                int(r.get("assists") or 0),
        "shots":                  int(r.get("shots") or 0),
        "shots_on_target":        int(r.get("shots_on_target") or 0),
        "xg_total":               float(r.get("xg_total") or 0),
        "pass_accuracy_pct":      round(pa * 100.0 / pt, 1) if pt > 0 else None,
        "duels_won_pct":          round(dw * 100.0 / dt, 1) if dt > 0 else None,
        "aerial_duels_won_pct":   round(aw * 100.0 / at, 1) if at > 0 else None,
        "yellow_cards":           int(r.get("yellow_cards") or 0),
        "red_cards":              int(r.get("red_cards") or 0),
    }


def compare_players(player_ids: list[int]) -> dict:
    """
    Build a comparison data dict for 2-3 players.

    Validates first; raises ValueError on any restriction violation.

    Returns:
        {
          'players':          [ <player_dict>, ... ],
          'best_per_metric':  { metric_key: player_id_with_max, ... },
        }

    Each <player_dict>:
        id, full_name, full_name_ar, photo_url, age (int|None),
        nationality, current_club,
        position_code, position_name, position_group_code, position_group_name,
        summary (dict), radar_scores (dict)
    """
    from datetime import date

    validate_comparison(player_ids)

    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT pl.id, pl.full_name, pl.full_name_ar,
                       pl.dob, pl.nationality, pl.current_club,
                       pl.nationality_code,
                       pl.nationality_status,
                       pl.eligible_from_date,
                       pl.bahrain_residency_start_date,
                       -- origin_country: the eligibility_badge macro on the
                       -- comparison cards feeds this to compute_eligibility_status
                       -- (same passport-holder fix as the players list).
                       pl.origin_country,
                       p.code   AS position_code,
                       p.name   AS position_name,
                       pg.id    AS position_group_id,
                       pg.code  AS position_group_code,
                       pg.name_en AS position_group_name
                FROM   players pl
                LEFT JOIN positions p        ON p.id  = pl.primary_position_id
                LEFT JOIN position_groups pg ON pg.id = p.position_group_id
                WHERE  pl.id = ANY(%s)
                """,
                (player_ids,)
            )
            rows = cur.fetchall() or []
    finally:
        _putconn(conn)

    by_id = {r["id"]: r for r in rows}

    today = date.today()
    def _age(dob):
        if not dob:
            return None
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

    # photo URL needs request context (url_for); resolve via helper
    from app.players.helpers import get_player_photo

    players_out = []
    for pid in player_ids:  # preserve picked order
        r = by_id.get(pid)
        if not r:
            continue
        players_out.append({
            "id":                          r["id"],
            "full_name":                   r["full_name"],
            "full_name_ar":                r["full_name_ar"],
            "photo_url":                   get_player_photo(r["id"]),
            "age":                         _age(r["dob"]),
            "nationality":                 r["nationality"],
            "current_club":                r["current_club"],
            # Phase 6.2.3: eligibility fields for badge rendering in compare view
            "nationality_code":            r["nationality_code"],
            "nationality_status":          r["nationality_status"],
            "eligible_from_date":          r["eligible_from_date"],
            "bahrain_residency_start_date": r["bahrain_residency_start_date"],
            # Passport holders: origin drives the countdown vs "Citizen" in
            # compute_eligibility_status (badge on the comparison cards).
            "origin_country":              r["origin_country"],
            "position_code":               r["position_code"],
            "position_name":               r["position_name"],
            "position_group_id":           r["position_group_id"],   # Phase 5d: criteria union
            "position_group_code":         r["position_group_code"],
            "position_group_name":         r["position_group_name"],
            "summary":                     _compare_summary(r["id"]),
            "radar_scores":                get_player_radar_scores(r["id"]),
        })

    # best_per_metric — id of player with max value per stat (None if all None/0)
    best: dict = {}
    metric_keys = [
        "matches_count", "total_minutes", "goals", "assists",
        "shots", "shots_on_target", "xg_total",
        "pass_accuracy_pct", "duels_won_pct", "aerial_duels_won_pct",
        # for cards lower is better, so we don't highlight a "best"
    ]
    for mk in metric_keys:
        best_id, best_val = None, None
        for p in players_out:
            v = p["summary"].get(mk)
            if v is None:
                continue
            if best_val is None or v > best_val:
                best_val, best_id = v, p["id"]
        if best_id is not None and best_val and best_val > 0:
            best[mk] = best_id

    return {
        "players":         players_out,
        "best_per_metric": best,
    }


# ---------------------------------------------------------------------------
# Trend data — time-series for line charts (last 15 matches)
# ---------------------------------------------------------------------------
def get_player_trends(player_id: int, limit: int = 15) -> dict:
    """
    Returns dict with 3 trend series for Chart.js line charts:
      - goals_assists: [{'date': ..., 'value': ...}, ...]
      - pass_accuracy: [...]
      - duel_win_rate: [...]
    Ordered chronologically (oldest first).
    """
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    match_date,
                    COALESCE(goals, 0) + COALESCE(assists, 0)   AS goals_assists,
                    CASE WHEN passes > 0
                         THEN ROUND(passes_accurate::numeric / passes * 100, 1)
                         ELSE NULL END                           AS pass_accuracy,
                    CASE WHEN duels > 0
                         THEN ROUND(duels_won::numeric / duels * 100, 1)
                         ELSE NULL END                           AS duel_win_rate
                FROM (
                    SELECT * FROM wyscout_match_stats
                    WHERE player_id = %s
                    ORDER BY match_date DESC
                    LIMIT %s
                ) sub
                ORDER BY match_date ASC
                """,
                (player_id, limit)
            )
            rows = cur.fetchall() or []

        trends = {
            "goals_assists": [],
            "pass_accuracy": [],
            "duel_win_rate": [],
            "labels": [],
        }
        for r in rows:
            label = r["match_date"].strftime("%d/%m/%y") if r["match_date"] else ""
            trends["labels"].append(label)
            trends["goals_assists"].append(r["goals_assists"])
            trends["pass_accuracy"].append(float(r["pass_accuracy"]) if r["pass_accuracy"] is not None else None)
            trends["duel_win_rate"].append(float(r["duel_win_rate"]) if r["duel_win_rate"] is not None else None)

        return trends
    finally:
        _putconn(conn)
