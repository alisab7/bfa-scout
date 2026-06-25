"""
National-team eligibility helpers (Phase 5c-2 / 6.2.2).

Pure-Python helpers for the eligibility card on the player profile and
the suggested-date UX on the player edit form. No DB calls — operates on
already-loaded player dicts.

The 5-year residency rule is the FIFA Article 5 default; the platform
treats it as advisory only — the admin always overrides via the
`eligible_from_date` field for any specific case. UI explicitly tells
admins to confirm with the eligibility advisor before relying on it.
"""
from datetime import date

# FIFA Article 5 baseline. DO NOT change without re-reading the spec
# locked-decisions table (Phase 5c-2). Override per-player via
# `eligible_from_date` admin field if a specific case differs.
RESIDENCY_YEARS_REQUIRED = 5


def compute_suggested_eligibility(residency_start) -> date | None:
    """
    `residency_start` + RESIDENCY_YEARS_REQUIRED years.

    Handles the Feb-29 leap-year edge case: if the resulting date doesn't
    exist in the target year (e.g. Feb 29 + 5 → Feb 29 in non-leap year),
    falls back to Feb 28.

    Accepts a `datetime.date`, ISO date string, or None. Returns None if
    input is None or unparseable.
    """
    if residency_start is None:
        return None
    if isinstance(residency_start, str):
        try:
            residency_start = date.fromisoformat(residency_start)
        except ValueError:
            return None
    target_year = residency_start.year + RESIDENCY_YEARS_REQUIRED
    try:
        return date(target_year, residency_start.month, residency_start.day)
    except ValueError:
        # Feb 29 + 5y → Feb 29 in non-leap; fall back to Feb 28.
        return date(target_year, residency_start.month, residency_start.day - 1)


def humanize_time_until(target_date) -> str | None:
    """Return the countdown string "Eligible in Xy Ym" for a FUTURE date,
    or None if `target_date` is missing / today / in the past.

    SINGLE SOURCE of the countdown format: `compute_eligibility_status`
    (the player profile) uses it for pending players, and the
    /nt/residents table reuses the exact same function so the values match
    everywhere — no duplicated date math.
    """
    if not target_date:
        return None
    if isinstance(target_date, str):
        try:
            target_date = date.fromisoformat(target_date)
        except ValueError:
            return None
    delta_days = (target_date - date.today()).days
    if delta_days <= 0:
        return None
    diff_years = delta_days // 365
    diff_months = (delta_days % 365) // 30
    return f"Eligible in {diff_years}y {diff_months}m"


def _resolve_eligibility_date(get_fn) -> date | None:
    """
    Single source of truth for a player's eligibility date.

    Checks explicit `eligible_from_date` first; if absent, derives from
    `bahrain_residency_start_date + RESIDENCY_YEARS_REQUIRED`.

    `get_fn` is a callable(field_name) -> value — avoids coupling to dict
    vs. Row vs. attribute-access objects.
    """
    edate = get_fn("eligible_from_date")
    if isinstance(edate, str):
        try:
            edate = date.fromisoformat(edate)
        except ValueError:
            edate = None
    if edate:
        return edate
    rstart = get_fn("bahrain_residency_start_date")
    if isinstance(rstart, str):
        try:
            rstart = date.fromisoformat(rstart)
        except ValueError:
            rstart = None
    if rstart:
        return compute_suggested_eligibility(rstart)
    return None


def age_at_eligibility(player) -> int | None:
    """
    For a `foreign_residency` player whose eligibility date is in the
    FUTURE and whose DOB is known, returns the integer age they will be
    on that date.  Returns None for all other cases (already eligible,
    no DOB, different nationality_status, etc.).

    Phase 6.2.2 — shown as "Age at eligibility: N" on the profile card
    and passport PDF so the committee can see at a glance how old the
    player will be when first available.
    """
    def _get(field):
        if hasattr(player, "get"):
            return player.get(field)
        return getattr(player, field, None)

    if _get("nationality_status") != "foreign_residency":
        return None

    dob = _get("dob")
    if not dob:
        return None
    if isinstance(dob, str):
        try:
            dob = date.fromisoformat(dob)
        except ValueError:
            return None

    elig_date = _resolve_eligibility_date(_get)
    if not elig_date:
        return None

    today = date.today()
    if elig_date <= today:
        return None  # Already eligible — no future age to show

    years = elig_date.year - dob.year
    if (elig_date.month, elig_date.day) < (dob.month, dob.day):
        years -= 1
    return years


def compute_eligibility_status(player) -> dict:
    """
    Returns a dict for the eligibility card template:
        {'icon':              '✅' | '⏳' | '❌' | '?',
         'label':             str,
         'note':              str | None,
         'is_eligible_now':   bool,
         'age_at_eligibility': int | None}

    Priority order (Phase 5c-2.1 — first match wins):
      1. nationality_status == 'not_eligible'        → ❌ Not eligible
      2. nationality_status in (bahraini, foreign_ancestry) → ✅ Eligible now
                                                              (birthright; date irrelevant)
      3. eligible_from_date set                      → ✅/⏳ based on date
      4. nationality_status == 'foreign_residency'   → use bahrain_residency_start_date
                                                       to derive suggested eligibility
                                                       OR ⏳ Pending if residency_start
                                                       is not set
      5. nationality_status == 'foreign_other'       → ? Foreign-eligible
                                                       (admin to set date)
      6. otherwise                                   → ? Status unknown

    Phase 6.2.2: all return dicts now include `is_eligible_now` (bool)
    and `age_at_eligibility` (int | None).
    """
    # Accept dict, RealDictRow, or attribute-access Row.
    def get(field):
        if hasattr(player, "get"):
            return player.get(field)
        return getattr(player, field, None)

    nat = get("nationality_status")
    _age_at_elig = age_at_eligibility(player)

    # Priority 1: explicitly not eligible
    if nat == "not_eligible":
        return {"icon": "❌", "label": "Not eligible", "note": None,
                "is_eligible_now": False, "age_at_eligibility": None,
                "status_code": "not_eligible"}

    # Priority 2: bahraini.
    if nat == "bahraini":
        origin = get("origin_country")
        if origin:
            # PASSPORT HOLDER (naturalized): Bahraini by passport, original
            # country kept as origin. NT eligibility runs the SAME 5-year
            # residency clock as foreign_residency — reuse the exact date
            # logic (`_resolve_eligibility_date`) + countdown
            # (`humanize_time_until`); only the LABEL changes. No new math.
            today = date.today()
            target = _resolve_eligibility_date(get)
            # Note shows the origin + residency context. The "Passport holder"
            # wording was dropped (v1.7.3) — origin + countdown convey it; the
            # is_passport_holder flag below is kept for template conditions.
            note_base = f"Origin: {origin}"
            if target is None:
                return {"icon": "⏳",
                        "label": "Pending — residency start not set",
                        "note": note_base + " — set Bahrain residency start date",
                        "is_eligible_now": False, "age_at_eligibility": None,
                        "status_code": "unknown",
                        "is_passport_holder": True, "origin_country": origin}
            if target <= today:
                return {"icon": "✅", "label": "Eligible now",
                        "note": note_base + " · 5-year residency complete",
                        "is_eligible_now": True, "age_at_eligibility": None,
                        "status_code": "eligible_now",
                        "is_passport_holder": True, "origin_country": origin}
            return {"icon": "⏳", "label": humanize_time_until(target),
                    "note": note_base + f" · eligible {target.strftime('%Y-%m-%d')}",
                    "is_eligible_now": False, "age_at_eligibility": _age_at_elig,
                    "status_code": "eligible_future",
                    "is_passport_holder": True, "origin_country": origin}
        # Born citizen (no origin) — birthright, eligible regardless of date.
        # Badge reads "Citizen" (NOT "Eligible now", reserved for residency
        # players past their date). is_eligible_now=True; only LABEL differs.
        return {"icon": "✅", "label": "Citizen",
                "note": "Bahraini citizen · مواطن",
                "is_eligible_now": True, "age_at_eligibility": None,
                "status_code": "citizen"}
    if nat == "foreign_ancestry":
        return {"icon": "✅", "label": "Citizen",
                "note": "Foreign-eligible (ancestry) · مواطن",
                "is_eligible_now": True, "age_at_eligibility": None,
                "status_code": "citizen"}

    # Priority 3: explicit eligible_from_date present (overrides residency-derived)
    edate = get("eligible_from_date")
    if isinstance(edate, str):
        try:
            edate = date.fromisoformat(edate)
        except ValueError:
            edate = None

    if edate:
        today = date.today()
        if edate <= today:
            return {"icon": "✅", "label": "Eligible now",
                    "note": f"From {edate.strftime('%Y-%m-%d')}",
                    "is_eligible_now": True, "age_at_eligibility": None,
                    "status_code": "eligible_now"}
        return {"icon":  "⏳",
                "label": humanize_time_until(edate),
                "note":  f"From {edate.strftime('%Y-%m-%d')}",
                "is_eligible_now": False, "age_at_eligibility": _age_at_elig,
                "status_code": "eligible_future"}

    # Priority 4: residency-route with start date but no eligible_from_date
    if nat == "foreign_residency":
        rstart = get("bahrain_residency_start_date")
        if isinstance(rstart, str):
            try:
                rstart = date.fromisoformat(rstart)
            except ValueError:
                rstart = None
        if rstart:
            suggested = compute_suggested_eligibility(rstart)
            if suggested:
                today = date.today()
                if suggested <= today:
                    return {
                        "icon":  "✅",
                        "label": "Eligible now",
                        "note":  (f"5-year residency complete "
                                  f"(suggested {suggested.strftime('%Y-%m-%d')}; "
                                  f"admin to confirm)"),
                        "is_eligible_now": True,
                        "age_at_eligibility": None,
                        "status_code": "eligible_now",
                    }
                return {
                    "icon":  "⏳",
                    "label": humanize_time_until(suggested),
                    "note":  (f"Suggested {suggested.strftime('%Y-%m-%d')} "
                              f"(Article 5; admin to confirm)"),
                    "is_eligible_now": False,
                    "age_at_eligibility": _age_at_elig,
                    "status_code": "eligible_future",
                }
        return {"icon":  "⏳",
                "label": "Pending — residency start not set",
                "note":  "Admin to set Bahrain residency start date",
                "is_eligible_now": False, "age_at_eligibility": None,
                "status_code": "unknown"}

    # Priority 5: foreign-eligible by 'other' route — admin must set date
    if nat == "foreign_other":
        return {"icon":  "?",
                "label": "Foreign-eligible (other route)",
                "note":  "Admin to set eligible-from date",
                "is_eligible_now": False, "age_at_eligibility": None,
                "status_code": "unknown"}

    # Priority 6: truly unknown
    return {"icon": "?", "label": "Status unknown", "note": None,
            "is_eligible_now": False, "age_at_eligibility": None,
            "status_code": "unknown"}


# ─── Orphaned-scores helpers (used by players edit position-change flow) ──

def count_orphan_scores(conn, player_id: int, new_position_group_id: int) -> int:
    """
    Number of evaluation_scores rows attached to this player whose
    criterion_id is NOT mapped to the new position group.

    These are the rows the admin must explicitly choose to delete or keep
    when changing primary_position_id.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS n
            FROM   evaluation_scores es
            JOIN   evaluations e ON e.id = es.evaluation_id
            WHERE  e.player_id = %s
              AND  es.criterion_id NOT IN (
                    SELECT criterion_id
                    FROM   position_group_criteria
                    WHERE  position_group_id = %s
              )
            """,
            (player_id, new_position_group_id)
        )
        return cur.fetchone()["n"]


def delete_orphan_scores(conn, player_id: int, new_position_group_id: int) -> int:
    """Delete the orphan rows. Returns deleted count."""
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM evaluation_scores
            WHERE  evaluation_id IN (
                SELECT id FROM evaluations WHERE player_id = %s
            )
            AND  criterion_id NOT IN (
                SELECT criterion_id
                FROM   position_group_criteria
                WHERE  position_group_id = %s
            )
            """,
            (player_id, new_position_group_id)
        )
        return cur.rowcount or 0
