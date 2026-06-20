"""
Form parsing helpers for the evaluation form (Phase 5c-1).

The form posts both meta fields (NT readiness, summary, etc.) and any number
of `score_<criterion_id>` keys. Untouched sliders simply omit their key from
the submission (handled client-side via Alpine `:disabled`-style binding).
"""
from typing import Iterable

# Whitelist for the radios — keep aligned with evaluations CHECK constraints
NT_READINESS_VALUES = {"senior", "u23", "u20", "u17", "not_ready"}
RECOMMENDATION_VALUES = {"call_up", "shortlist", "monitor", "not_at_level", "release"}
ELIGIBILITY_VALUES = {
    "bahraini", "foreign_residency", "foreign_ancestry",
    "foreign_other", "not_eligible", "unknown",
}


def parse_score_inputs(form: dict) -> dict[int, dict]:
    """
    Returns dict {criterion_id: {'score': float|None, 'is_not_applicable': bool}}
    pulled from the tri-state form (Phase 5c-1.1).

    Per-criterion submission contract:
      - `score_<id>=value` present  → rated     → {score: float, is_not_applicable: False}
      - `na_<id>=1` present         → N/A       → {score: None, is_not_applicable: True}
      - neither present             → untouched → not in dict (DELETE-then-INSERT
                                                  in the DB write removes any prior row)
      - both present                → malformed → N/A wins (last-write-wins on cid)

    Out-of-range / non-numeric scores are dropped silently.
    """
    out: dict[int, dict] = {}
    # First pass — collect rated scores
    for key, raw in form.items():
        if not key.startswith("score_"):
            continue
        suffix = key[len("score_"):]
        if not suffix.isdigit():
            continue
        crit_id = int(suffix)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value < 1 or value > 10:
            continue
        out[crit_id] = {"score": value, "is_not_applicable": False}

    # Second pass — N/A overrides any rated entry for the same criterion
    for key in form.keys():
        if not key.startswith("na_"):
            continue
        suffix = key[len("na_"):]
        if not suffix.isdigit():
            continue
        crit_id = int(suffix)
        out[crit_id] = {"score": None, "is_not_applicable": True}

    return out


def parse_meta_fields(form: dict) -> dict:
    """
    Extract the non-score meta fields the form may post. Unknown / out-of-
    whitelist values are stored as None so the DB CHECK constraints stay safe.
    """
    def pick(key, valid: Iterable[str] | None = None):
        v = (form.get(key) or "").strip() or None
        if v is None:
            return None
        if valid is not None and v not in valid:
            return None
        return v

    minutes_raw = (form.get("minutes_observed") or "").strip()
    try:
        minutes = int(minutes_raw) if minutes_raw else None
        if minutes is not None and (minutes < 0 or minutes > 200):
            minutes = None
    except ValueError:
        minutes = None

    match_id_raw = (form.get("match_id") or "").strip()
    try:
        match_id = int(match_id_raw) if match_id_raw else None
    except ValueError:
        match_id = None

    # Position the player actually played in THIS match (per-evaluation
    # context; does NOT change the player's registered position, and does
    # NOT drive criteria — those still follow position_group_id).
    pos_played_raw = (form.get("position_played_id") or "").strip()
    try:
        position_played_id = int(pos_played_raw) if pos_played_raw else None
    except ValueError:
        position_played_id = None

    return {
        "match_id":            match_id,
        "position_played_id":  position_played_id,
        "summary":             (form.get("summary") or "").strip() or None,
        "recommendation":      pick("recommendation", RECOMMENDATION_VALUES),
        "nt_readiness_level":  pick("nt_readiness_level", NT_READINESS_VALUES),
        "eligibility_status":  pick("eligibility_status", ELIGIBILITY_VALUES),
        "eligibility_notes":   (form.get("eligibility_notes") or "").strip() or None,
        "comparable_player":   (form.get("comparable_player") or "").strip() or None,
        "minutes_observed":    minutes,
    }
