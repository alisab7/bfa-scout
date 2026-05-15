"""
Bahrain Premier League season derivation (Phase 4.2).

The BPL season runs Aug–May. A match played on 2025-09-12 belongs to
season '2025-26'; a match played on 2026-04-16 also belongs to season
'2025-26'. This single helper is the source of truth for both the Python
ingest path (`app/wyscout/ingest.py`) and the historical backfill
(`migrations/phase_4_2_season_column.sql` — which mirrors this logic in
pure SQL but must produce identical strings).

Phase 4.2.1 (deferred until a second season of data exists) will add UI
toggles that filter on this column.
"""
from datetime import date


# Cutoff month: matches in this month or later belong to the NEXT season
# (e.g. Aug 2025 → '2025-26'). Mirrors the Bahrain Premier League calendar.
SEASON_START_MONTH = 8


def derive_season(match_date: date) -> str:
    """
    Bahrain Premier League season label for `match_date`.

    Returns the '<startYear>-<endYearLast2>' form (e.g. '2025-26' for
    matches in Aug-2025 through May-2026 inclusive).

    >>> derive_season(date(2025, 9, 12))
    '2025-26'
    >>> derive_season(date(2026, 4, 16))
    '2025-26'
    >>> derive_season(date(2025, 7, 31))
    '2024-25'
    >>> derive_season(date(2025, 8, 1))
    '2025-26'
    >>> derive_season(date(2026, 8, 15))
    '2026-27'
    """
    if match_date.month >= SEASON_START_MONTH:
        start_year = match_date.year
    else:
        start_year = match_date.year - 1
    end_year_last2 = (start_year + 1) % 100
    return f"{start_year}-{end_year_last2:02d}"
