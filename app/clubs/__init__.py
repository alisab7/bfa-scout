"""
app.clubs — canonical club utilities.

Provides resolve_club_from_team_string(), the single lookup point for
translating a raw wyscout match-team string to a clubs.id. All callers
(match reconciliation, vs-opponent display, league-filter) use this function.
"""

from .resolver import resolve_club_from_team_string         # noqa: F401
from .resolver import enrich_match_history_with_opponent    # noqa: F401

__all__ = ["resolve_club_from_team_string", "enrich_match_history_with_opponent"]
