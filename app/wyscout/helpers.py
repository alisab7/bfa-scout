"""
Wyscout helper utilities — radar normalization.

RADAR_THRESHOLDS maps each of the 6 radar axes to a (metric, max_value) tuple.
max_value is the value considered "world-class / top-10%", used for 0-100 normalization.
These are generic across positions for v1 (position-specific in v1.1).
"""

# ---------------------------------------------------------------------------
# 6-axis radar configuration
# Each key is the display label; value is (db_column, per_90_divisor, max_val)
# per_90_divisor: set to None to use raw value; set to True to scale per 90 min
# ---------------------------------------------------------------------------
RADAR_AXES = [
    # (axis_label, db_column, use_per90, max_val_at_100)
    ("Scoring",     "goals",              True,  0.7),
    ("Passing",     "passes_accurate",    True,  70.0),
    ("Dribbling",   "dribbles_successful",True,  5.0),
    ("Defending",   "defensive_duels_won",True,  6.0),
    ("Aerial",      "aerial_duels_won",   True,  4.0),
    ("Work Rate",   "total_actions",      True,  90.0),
]

# Convenience dict for normalization lookups: label → (db_column, use_per90, max_val)
RADAR_THRESHOLDS = {label: (col, per90, max_val) for label, col, per90, max_val in RADAR_AXES}


def season_label_for_date(d):
    """
    Football season label (Aug 1 → May 31) for a given date.

    Examples:
      date(2024, 8, 1)  → '2024/25'
      date(2025, 5, 31) → '2024/25'
      date(2025, 7, 31) → '2024/25'
      date(2025, 8, 1)  → '2025/26'

    Args:
        d: datetime.date, datetime.datetime, or ISO 'YYYY-MM-DD' string.

    Returns:
        '<start_year>/<end_short>' string, or None if d is None/unparseable.
    """
    if d is None:
        return None
    if isinstance(d, str):
        from datetime import date
        try:
            d = date.fromisoformat(d)
        except ValueError:
            return None
    start_year = d.year if d.month >= 8 else d.year - 1
    end_short  = (start_year + 1) % 100
    return f"{start_year}/{end_short:02d}"


def normalize_radar_axis(value: float | None, use_per90: bool, minutes: float | None,
                         max_val: float) -> float:
    """
    Normalize a raw stat value to 0–100 for radar display.

    - If use_per90 and minutes > 0, converts to per-90 first.
    - Clamps result to [0, 100].
    - Returns 0 if value or minutes are missing/zero.
    """
    if value is None or max_val <= 0:
        return 0.0
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0

    if use_per90:
        try:
            mins = float(minutes or 0)
        except (TypeError, ValueError):
            mins = 0.0
        if mins <= 0:
            return 0.0
        v = (v / mins) * 90.0

    normalized = (v / max_val) * 100.0
    return max(0.0, min(100.0, normalized))
