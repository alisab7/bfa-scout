"""
Wyscout XLSX parser.

Reads a Wyscout player-stats export and returns a list of dicts, one per
match row, keyed by wyscout_match_stats columns.

Wyscout exports use a paired-column layout: a slash-header like
"Passes / accurate" means column N holds the first value (passes) and the
next column N+1 holds the second value (passes_accurate) under a blank
header. We map by column INDEX, not header text, because pandas/dict-keyed
approaches drop the blank-header columns silently.
"""
import re
import json
import logging
from datetime import date, datetime

from openpyxl import load_workbook

log = logging.getLogger(__name__)


# 1-based column index → wyscout_match_stats DB field.
# Columns not listed (26, 28, 30, 31, 51-72) are preserved in raw_row only.
_COLUMN_MAP: dict[int, str] = {
    1:  "match_label",
    2:  "competition",
    3:  "match_date",
    4:  "position_raw",
    5:  "minutes_played",
    6:  "total_actions",
    7:  "total_actions_successful",
    8:  "goals",
    9:  "assists",
    10: "shots",
    11: "shots_on_target",
    12: "xg",
    13: "passes",
    14: "passes_accurate",
    15: "long_passes",
    16: "long_passes_accurate",
    17: "crosses",
    18: "crosses_accurate",
    19: "dribbles",
    20: "dribbles_successful",
    21: "duels",
    22: "duels_won",
    23: "aerial_duels",
    24: "aerial_duels_won",
    25: "interceptions",
    # 26: "Losses / own half" total — not in schema, raw_row only
    27: "losses_own_half",
    # 28: "Recoveries / opp. half" total — not in schema, raw_row only
    29: "recoveries_opp_half",
    # 30, 31: "Yellow card" / "Red card" = minute of first card; different
    # semantics from the count columns (40, 41), so we skip these.
    32: "defensive_duels",
    33: "defensive_duels_won",
    34: "loose_ball_duels",
    35: "loose_ball_duels_won",
    36: "sliding_tackles",
    37: "sliding_tackles_successful",
    38: "clearances",
    39: "fouls",
    40: "yellow_cards",
    41: "red_cards",
    42: "shot_assists",
    43: "offensive_duels",
    44: "offensive_duels_won",
    45: "touches_in_box",
    46: "offsides",
    47: "progressive_runs",
    48: "fouls_suffered",
    49: "through_passes",
    50: "through_passes_accurate",
}

_FLOAT_FIELDS = {"xg"}
_STRING_FIELDS = {"match_label", "competition", "position_raw"}
_DATE_FIELD = "match_date"

# "Home Team - Away Team H:A"  (apostrophes and other punctuation in team
# names are fine — the lazy quantifiers stop at " - " and the H:A suffix.)
_MATCH_RE = re.compile(r'^(.+?)\s+-\s+(.+?)\s+(\d+):(\d+)\s*$')

_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%m/%d/%Y")


def _coerce_int(val) -> int | None:
    if val is None or val == "":
        return None
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


def _coerce_float(val) -> float | None:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _coerce_str(val) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def _coerce_date(val) -> date | None:
    if val is None or val == "":
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    s = str(val).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _parse_match_label(label: str) -> dict:
    """Extract home_team, away_team, home_score, away_score from the label."""
    out = {
        "home_team":  None,
        "away_team":  None,
        "home_score": None,
        "away_score": None,
    }
    m = _MATCH_RE.match(label)
    if m:
        out["home_team"]  = m.group(1).strip()
        out["away_team"]  = m.group(2).strip()
        out["home_score"] = int(m.group(3))
        out["away_score"] = int(m.group(4))
    return out


def _resolve_is_home(home_team: str | None, away_team: str | None,
                     player_team: str | None) -> bool | None:
    """
    Bidirectional case-insensitive substring match. Handles the common case
    where player.current_club is "Muharraq Club" but the fixture lists
    "Muharraq" — neither is a substring of the other in a single direction,
    so we try both.
    """
    if not player_team:
        return None
    pt = player_team.lower()
    if home_team:
        ht = home_team.lower()
        if ht in pt or pt in ht:
            return True
    if away_team:
        at = away_team.lower()
        if at in pt or pt in at:
            return False
    return None


def _serialize(val):
    """JSON-safe representation for raw_row preservation."""
    if val is None:
        return None
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    if isinstance(val, (bool, int, float, str)):
        return val
    return str(val)


def parse_wyscout_xlsx(file_path: str,
                       player_team: str | None = None) -> list[dict]:
    """
    Parse a Wyscout player-stats XLSX export.

    Args:
        file_path:   absolute path to the .xlsx file.
        player_team: optional player club name; used to derive is_home via
                     case-insensitive substring match against home/away.
                     If omitted, is_home stays None and the ingest layer
                     can fill it later.

    Returns:
        A list of row dicts whose keys correspond to wyscout_match_stats
        columns. Each dict also includes a 'raw_row' key (JSON string)
        preserving every column from the original sheet, keyed col_1..col_N.

    Raises:
        ValueError: file cannot be read or contains no data rows.
    """
    try:
        wb = load_workbook(file_path, data_only=True)
    except Exception as exc:
        raise ValueError(f"Cannot read XLSX: {exc}") from exc

    ws = wb.active
    if ws is None or ws.max_row < 2:
        wb.close()
        raise ValueError("XLSX file contains no data rows.")

    rows: list[dict] = []

    for r_idx, raw in enumerate(
        ws.iter_rows(min_row=2, values_only=True), start=2
    ):
        # Skip rows with no match label
        match_cell = raw[0] if len(raw) >= 1 else None
        if match_cell is None or str(match_cell).strip() == "":
            continue

        # Preserve full row (every column, including blank-header ones)
        raw_dict = {f"col_{i + 1}": _serialize(raw[i]) for i in range(len(raw))}
        row: dict = {"raw_row": json.dumps(raw_dict, default=str)}

        # Initialize match-label-derived fields (filled below if regex matches)
        row["home_team"]  = None
        row["away_team"]  = None
        row["home_score"] = None
        row["away_score"] = None
        row["is_home"]    = None

        # Map columns by index
        for col_idx, db_field in _COLUMN_MAP.items():
            val = raw[col_idx - 1] if col_idx <= len(raw) else None

            if db_field in _STRING_FIELDS:
                row[db_field] = _coerce_str(val)
            elif db_field == _DATE_FIELD:
                row[db_field] = _coerce_date(val)
            elif db_field in _FLOAT_FIELDS:
                row[db_field] = _coerce_float(val)
            else:
                row[db_field] = _coerce_int(val)

        # Parse match_label → home/away teams + scores; if it doesn't match
        # the expected pattern, we keep match_label verbatim and leave the
        # derived fields NULL rather than dropping the row.
        match_label = row.get("match_label")
        if match_label:
            parsed = _parse_match_label(match_label)
            row.update(parsed)
            row["is_home"] = _resolve_is_home(
                parsed["home_team"], parsed["away_team"], player_team
            )
        else:
            log.warning("Row %d: missing match_label after coercion.", r_idx)

        rows.append(row)

    wb.close()

    if not rows:
        raise ValueError("No valid match rows found after parsing.")

    return rows
