"""
Phase 6 data aggregator. Returns the full nested dict the passport
template consumes. Pure read-only — composes existing helpers across
players, evaluations, and Wyscout modules. No new SQL helpers below.

Public-mode redaction rules (mode='public'):
  - scout/evaluator names → 'Scout N' (stable per passport rendering;
    same human keeps the same number across latest panel + history)
  - player.eligibility_notes_admin → None
  - player.bahrain_residency_notes → None
  - latest_eval.summary still shown (it's scout's own writeup,
    not an admin note)

Returns None if the player doesn't exist or is_active=FALSE
(deactivated). Locked evaluations are INCLUDED in the page-2 panels;
soft-deleted ones are EXCLUDED (Phase 5c-3 invariant honoured by the
underlying helpers, no extra filtering needed here).
"""
import os
from datetime import date, datetime, timezone
from pathlib import Path

from flask import current_app

from app.db import get_db
from app.evaluations.helpers import (
    get_player_evaluations, get_evaluation_count_active,
    get_player_evaluation_aggregate, get_player_bio_counts,
)
from app.players.eligibility import (
    compute_suggested_eligibility, age_at_eligibility as _age_at_eligibility,
    compute_eligibility_status,
)
from app.players.nationalities import NATIONALITY_LABEL, ALPHA3_TO_ALPHA2
from app.players.helpers import age as _age_of
from app.wyscout.aggregations import (
    get_player_summary, get_player_radar_scores,
)


# ─── Phase 6.1: passport-specific eligibility wording ──────────────
# `compute_eligibility_status` in app/players/eligibility.py is the source
# of truth for the live profile page UI. The PDF passport needs different
# wording — "Eligible from 2027-08-15 (in 1 year, 3 months)" instead of
# "Eligible in 1y 3m / Suggested 2027-08-15 (Article 5; admin to confirm)"
# — because committee readers don't want FIFA-regulation jargon and the
# PDF is a formal document where "y/m" abbreviations look casual.
#
# Lives in this module rather than app/players/eligibility.py because it's
# strictly a PDF-rendering concern; the live UI's wording is fine as-is.

def _humanize_duration(years: int, months: int) -> str:
    """'1 year, 3 months' (not '1y 3m'). Returns 'less than 1 month' if both
    are zero — only reachable if `delta_days` < 30 AND < 365, i.e. < 30 days
    — defensive for the day-of crossover."""
    parts = []
    if years > 0:
        parts.append(f"{years} year{'' if years == 1 else 's'}")
    if months > 0:
        parts.append(f"{months} month{'' if months == 1 else 's'}")
    if not parts:
        return "less than 1 month"
    return ", ".join(parts)


def _build_passport_eligibility(player: dict) -> dict:
    """
    Returns {'icon', 'label', 'note', 'is_eligible_now', 'age_at_eligibility'}
    for the passport eligibility card.

    Wording deliberately reformatted from `compute_eligibility_status` for
    the formal-document context. Branches mirror the 6-priority order from
    Phase 5c-2.1; for each branch the wording is the table in the 6.1
    spec ("Cases to handle"). Seven cases asserted in the E2E.

    `note` is the residency-since line where relevant (foreign_residency
    + bahrain_residency_start_date set), otherwise None.

    Phase 6.2.2: added `is_eligible_now` (bool) and `age_at_eligibility`
    (int | None — only set for foreign_residency players with a future
    eligibility date and known DOB).
    """
    nat = player.get("nationality_status")
    _age_at_elig = _age_at_eligibility(player)

    # Priority 1: explicitly not eligible
    if nat == "not_eligible":
        return {"icon": "❌", "label": "Not eligible", "note": None,
                "is_eligible_now": False, "age_at_eligibility": None}

    # Priority 2: birthright (eligible regardless of date)
    if nat == "bahraini":
        # Passport holder (naturalized): Bahraini by passport with an origin
        # country kept. NT eligibility runs the 5-year residency clock — reuse
        # `compute_eligibility_status` verbatim so the PDF's label/countdown is
        # IDENTICAL to the player profile (no new date math; only mapped to the
        # passport dict shape). Born citizens (no origin) fall through to the
        # plain-citizen line below, unchanged.
        if player.get("origin_country"):
            es = compute_eligibility_status(player)
            return {"icon": es["icon"], "label": es["label"], "note": es["note"],
                    "is_eligible_now": es["is_eligible_now"],
                    "age_at_eligibility": es["age_at_eligibility"]}
        return {"icon": "✅", "label": "Eligible now",
                "note": "Bahraini citizen",
                "is_eligible_now": True, "age_at_eligibility": None}
    if nat == "foreign_ancestry":
        return {"icon": "✅", "label": "Eligible now",
                "note": "Foreign-eligible (ancestry)",
                "is_eligible_now": True, "age_at_eligibility": None}

    # Residency-since line (only meaningful for foreign_residency
    # players with a recorded start date — for other branches we return
    # None and the template omits the second line entirely).
    rstart = player.get("bahrain_residency_start_date")
    if isinstance(rstart, str):
        try:
            rstart = date.fromisoformat(rstart)
        except ValueError:
            rstart = None
    residency_line = (
        f"Bahrain residency since {rstart.strftime('%Y-%m-%d')}"
        if nat == "foreign_residency" and rstart else None
    )

    # Priority 3: explicit eligible_from_date present (overrides residency-derived)
    edate = player.get("eligible_from_date")
    if isinstance(edate, str):
        try:
            edate = date.fromisoformat(edate)
        except ValueError:
            edate = None

    today = date.today()

    if edate:
        if edate <= today:
            return {"icon": "✅",
                    "label": f"Eligible from {edate.strftime('%Y-%m-%d')}",
                    "note": residency_line,
                    "is_eligible_now": True, "age_at_eligibility": None}
        delta_days = (edate - today).days
        years  = delta_days // 365
        months = (delta_days % 365) // 30
        return {"icon": "⏳",
                "label": (f"Eligible from {edate.strftime('%Y-%m-%d')} "
                          f"(in {_humanize_duration(years, months)})"),
                "note": residency_line,
                "is_eligible_now": False, "age_at_eligibility": _age_at_elig}

    # Priority 4: residency-route, derive suggested from start date
    if nat == "foreign_residency":
        if rstart:
            suggested = compute_suggested_eligibility(rstart)
            if suggested:
                if suggested <= today:
                    return {"icon": "✅",
                            "label": (f"Eligible from "
                                      f"{suggested.strftime('%Y-%m-%d')}"),
                            "note": residency_line,
                            "is_eligible_now": True, "age_at_eligibility": None}
                delta_days = (suggested - today).days
                years  = delta_days // 365
                months = (delta_days % 365) // 30
                return {"icon": "⏳",
                        "label": (f"Eligible from {suggested.strftime('%Y-%m-%d')} "
                                  f"(in {_humanize_duration(years, months)})"),
                        "note": residency_line,
                        "is_eligible_now": False, "age_at_eligibility": _age_at_elig}
        # foreign_residency with NO start date = pending
        return {"icon": "⏳",
                "label": "Pending — residency start not set",
                "note": None,
                "is_eligible_now": False, "age_at_eligibility": None}

    # Priority 5: foreign-eligible by 'other' route — admin must set date
    if nat == "foreign_other":
        return {"icon": "?",
                "label": "Foreign-eligible (other route)",
                "note": None,
                "is_eligible_now": False, "age_at_eligibility": None}

    # Priority 6: unknown
    return {"icon": "?", "label": "Status unknown", "note": None,
            "is_eligible_now": False, "age_at_eligibility": None}


# ─── Phase 6.1: flag SVG loader ─────────────────────────────────────

def _flag_svg_inline(nationality_code: str | None) -> str | None:
    """Return the inline SVG content for a flag, or None if unknown.
    File path: app/static/flags/<alpha2>.svg. Source: flag-icons project
    (https://github.com/lipis/flag-icons), MIT-licensed, vendored as
    static assets in Phase 6.1 — avoids emoji-font rendering fragility
    in WeasyPrint."""
    if not nationality_code or len(nationality_code) != 3:
        return None
    alpha2 = ALPHA3_TO_ALPHA2.get(nationality_code.upper(), '').lower()
    if not alpha2:
        return None
    flag_path = (
        Path(current_app.static_folder) / 'flags' / f'{alpha2}.svg'
    )
    if not flag_path.exists():
        return None
    try:
        return flag_path.read_text(encoding='utf-8')
    except OSError:
        return None


# ─── Phase 6.1: Wyscout season subtitle ─────────────────────────────

def _build_season_subtitle(player_id: int) -> str | None:
    """
    'YYYY-YY season · N matches' for one season, or
    'YYYY-YY to YYYY-YY · N matches' for a range.
    Returns None if the player has no Wyscout matches.

    Format choice: keeps the DB column's `'YYYY-YY'` hyphen format
    (set by Phase 4.2's `derive_season`) — the same string the rest of
    the system stores and (eventually) filters on. The 4.1 helper
    `season_label_for_date` returns slash-format but is currently
    unused in the codebase; aligning that helper to the DB format is
    a separate cleanup (flagged at end of 4.2, follow-up file).
    """
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT season
            FROM   wyscout_match_stats
            WHERE  player_id = %s AND season IS NOT NULL
            ORDER  BY season
            """,
            (player_id,)
        )
        seasons = [r['season'] for r in cur.fetchall() or []]
        cur.execute(
            "SELECT COUNT(*) AS n FROM wyscout_match_stats WHERE player_id = %s",
            (player_id,)
        )
        match_count = (cur.fetchone() or {}).get('n', 0)

    if not seasons:
        return None
    matches_word = "match" if match_count == 1 else "matches"
    if len(seasons) == 1:
        return f"{seasons[0]} season · {match_count} {matches_word}"
    return f"{seasons[0]} to {seasons[-1]} · {match_count} {matches_word}"


def _fetch_player_bio(player_id: int) -> dict | None:
    """One row with all the bio + eligibility + position + club fields the
    passport needs. Mirrors the SELECT in players.player_profile() but
    inlined here so the passport package doesn't depend on the players
    blueprint internals."""
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT pl.id, pl.full_name, pl.full_name_ar, pl.national_id,
                   pl.primary_position_id, pl.dob, pl.current_club,
                   pl.nationality, pl.height_cm, pl.weight_kg, pl.notes,
                   pl.is_active,
                   pl.nationality_status, pl.eligible_from_date,
                   pl.eligibility_notes_admin,
                   pl.bahrain_residency_start_date, pl.bahrain_residency_notes,
                   pl.nationality_code, pl.club_id,
                   -- Passport holders: origin country (mirrors the profile SELECT)
                   pl.origin_country, pl.origin_country_code,
                   p.code  AS position_code, p.name AS position_name,
                   pg.code AS position_group_code,
                   pg.name_en AS position_group_name,
                   c.name AS club_name, c.division AS club_division
            FROM   players pl
            LEFT JOIN positions p        ON p.id  = pl.primary_position_id
            LEFT JOIN position_groups pg ON pg.id = p.position_group_id
            LEFT JOIN clubs c            ON c.id  = pl.club_id
            WHERE  pl.id = %s
            """,
            (player_id,)
        )
        row = cur.fetchone()
    return dict(row) if row else None


def _aerial_won_pct(player_id: int) -> float | None:
    """Compute career aerial duel win rate. `get_player_summary` doesn't
    include this metric; the passport stat table needs it per spec."""
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(SUM(aerial_duels), 0)     AS d,
                   COALESCE(SUM(aerial_duels_won), 0) AS w
            FROM   wyscout_match_stats
            WHERE  player_id = %s
            """,
            (player_id,)
        )
        r = cur.fetchone()
    d = r["d"] or 0
    w = r["w"] or 0
    if d <= 0:
        return None
    return round(w / d * 100, 1)


def _build_redaction_map(history: list[dict]) -> dict[str, str]:
    """For public mode: scout name → 'Scout N' assigned in
    first-appearance order, so the same human keeps the same number in
    both the latest panel and the history table.
    Drops None/empty names — they're handled separately in the redactor."""
    seen: dict[str, str] = {}
    next_num = 1
    for ev in history:
        name = (ev or {}).get('evaluator_name') or ''
        if name and name not in seen:
            seen[name] = f"Scout {next_num}"
            next_num += 1
    return seen


def _redact_eval(ev: dict, redaction: dict[str, str]) -> dict:
    """Return a copy of an evaluation row with `evaluator_name` replaced
    via the redaction map. Other fields untouched."""
    if not ev:
        return ev
    out = dict(ev)
    name = out.get('evaluator_name')
    if name and name in redaction:
        out['evaluator_name'] = redaction[name]
    elif name:
        out['evaluator_name'] = 'Scout ?'  # unknown human; defensive
    return out


def _match_label_from_eval(ev: dict) -> str:
    """Compose 'Home vs Away' from joined match columns or fall back to
    e.match_label (the denormalised label written at evaluation save).
    Returns '—' if neither is available."""
    if ev.get('m_home') and ev.get('m_away'):
        return f"{ev['m_home']} vs {ev['m_away']}"
    if ev.get('match_label'):
        return ev['match_label']
    return '—'


def get_passport_data(player_id: int, mode: str = 'full',
                      requesting_user_role: str | None = None) -> dict | None:
    """
    Aggregate everything the passport template needs.

    Returns:
        dict with keys:
            player, eligibility, wyscout, latest_eval, evaluation_history,
            meta
        OR None if player not found / not active.

    `mode`:
        'full'   → admin/TD/scout view; everything visible
        'public' → redacted (scout names, admin notes)

    `requesting_user_role` (Phase 7): role of the user generating the
    passport. When 'scout', NT-staff-authored evaluations are hidden
    from the page-2 history and from the latest-eval aggregate. The
    passport route ALWAYS passes current_user.role; callers in tests
    or admin tooling can leave it None for "see everything".
    """
    if mode not in ('full', 'public'):
        raise ValueError(f"mode must be 'full' or 'public', got {mode!r}")

    player = _fetch_player_bio(player_id)
    if not player or not player.get('is_active'):
        return None

    # ── Bio enrichments ──────────────────────────────────────────────
    player['age']                = _age_of(player.get('dob'))
    player['nationality_label']  = NATIONALITY_LABEL.get(
        player.get('nationality_code') or '', None
    )
    # Phase 6.1: inline SVG instead of emoji — emoji fonts in WeasyPrint
    # are unreliable across systems. flag_svg is None if no flag available.
    player['flag_svg']           = _flag_svg_inline(player.get('nationality_code'))
    # Passport holders: origin label + flag (profile-parity; only surfaced in
    # the template when nationality_status='bahraini' AND origin_country set).
    player['origin_label']       = NATIONALITY_LABEL.get(
        player.get('origin_country_code') or '', None
    ) or player.get('origin_country')
    player['origin_flag_svg']    = _flag_svg_inline(player.get('origin_country_code'))

    # ── Eligibility card (Phase 6.1: passport-specific wording) ─────
    eligibility = _build_passport_eligibility(player)

    # ── Wyscout aggregates (None if no match data) ───────────────────
    summary = get_player_summary(player_id)
    wyscout = None
    if summary:
        wyscout = {
            'matches':         int(summary.get('matches') or 0),
            'minutes':         int(summary.get('total_minutes') or 0),
            'goals':           int(summary.get('total_goals') or 0),
            'assists':         int(summary.get('total_assists') or 0),
            'shots':           int(summary.get('total_shots') or 0),
            'xg':              float(summary.get('total_xg') or 0),
            'pass_pct':        summary.get('pass_accuracy'),
            'duels_won_pct':   summary.get('duel_win_rate'),
            'aerial_won_pct':  _aerial_won_pct(player_id),
            'yellows':         int(summary.get('total_yellow_cards') or 0),
            'reds':            int(summary.get('total_red_cards') or 0),
            'radar_scores':    get_player_radar_scores(player_id),
            # Phase 6.1: season + match-count subtitle under the h3
            'season_subtitle': _build_season_subtitle(player_id),
        }

    # ── Evaluations (page 2) ─────────────────────────────────────────
    # Phase 7: hide nt_staff evals from scout viewers in both history
    # and the latest-eval aggregate.
    raw_history = get_player_evaluations(player_id,
                                         requesting_user_role=requesting_user_role)

    # Build redaction map BEFORE we shape evaluations for the template
    # so latest_eval + history both use the same mapping.
    redaction = _build_redaction_map(raw_history) if mode == 'public' else {}

    evaluation_history: list[dict] = []
    for ev in raw_history:
        ev_out = {
            'submitted_at':       ev.get('submitted_at') or ev.get('created_at'),
            'evaluator_name':     ev.get('evaluator_name') or 'Unknown',
            'match_label':        _match_label_from_eval(ev),
            'nt_readiness_level': ev.get('nt_readiness_level'),
            'recommendation':     ev.get('recommendation'),
            # Phase 7: role badge driver
            'created_by_role':    ev.get('created_by_role'),
        }
        if mode == 'public':
            ev_out = _redact_eval(ev_out, redaction)
        evaluation_history.append(ev_out)

    # Latest evaluation aggregate — for the big panel on page 2.
    latest_eval = None
    if get_evaluation_count_active(player_id,
                                   requesting_user_role=requesting_user_role) > 0:
        agg = get_player_evaluation_aggregate(
            player_id, mode='latest',
            requesting_user_role=requesting_user_role)
        if agg:
            latest_eval = {
                'evaluator_name':      agg.get('evaluator_name') or 'Unknown',
                'submitted_at':        agg.get('submitted_at'),
                'match_label':         agg.get('match_label') or '—',
                'nt_readiness_level':  agg.get('nt_readiness_level'),
                'recommendation':      agg.get('recommendation'),
                'category_averages':   agg.get('category_averages') or {},
                'summary':             agg.get('summary'),
                'created_by_role':     agg.get('created_by_role'),
            }
            if mode == 'public':
                latest_eval = _redact_eval(latest_eval, redaction)

    # ── Public-mode admin-note scrub ────────────────────────────────
    if mode == 'public':
        player = dict(player)
        player['eligibility_notes_admin'] = None
        player['bahrain_residency_notes'] = None

    # ── Meta ────────────────────────────────────────────────────────
    bio_counts = get_player_bio_counts(player_id,
                                       requesting_user_role=requesting_user_role)

    return {
        'player':              player,
        'eligibility':         eligibility,
        'wyscout':             wyscout,
        'latest_eval':         latest_eval,
        'evaluation_history':  evaluation_history,
        'bio_counts':          bio_counts,
        'meta': {
            'mode':           mode,
            'generated_at':   datetime.now(timezone.utc),
            'generator_name': None,   # filled in by route from current_user
        },
    }
