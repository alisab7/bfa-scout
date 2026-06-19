"""
Evaluation form helpers — pure DB queries, no Flask-context state.

Phase 5c-1 scope:
  - get_form_criteria(position_group_id) → list of criteria + category info
  - get_recent_matches(limit) → match dropdown source
  - get_or_create_draft(player_id, match_id, scout_id) → reuse-or-create
  - get_evaluation(eval_id) → full evaluation row
  - get_evaluation_scores(eval_id) → {criterion_id: {score, is_NA}} prefill
  - save_evaluation_scores(eval_id, scores) → DELETE-then-INSERT (5c-1.1)
  - update_evaluation_meta(eval_id, fields) → write summary, NT fields, etc.
  - submit_draft(eval_id, scout_id) → validate + status transition
  - resolve_position_group_for_player(player_id) → position_group_id or None

Phase 5c-2 additions:
  - get_player_evaluations(player_id, status_filter=None) — history cards
  - nt_readiness_summary(player_id, last_n=3) — eligibility-card summary line
  - lock_evaluation(eval_id, locker_id) — admin/TD lock workflow
  - unlock_evaluation(eval_id, unlocker_id, reason) — reversal with reason
  - admin_edit_evaluation(eval_id, admin_id, meta) — overwrite while
    preserving original evaluator_id; sets last_edited_by/at

Phase 5c-2 also exposes Arabic translation dicts (NT_LEVEL_LABEL_AR,
RECOMMENDATION_LABEL_AR, ELIGIBILITY_STATUS_LABEL_AR) used by templates
and registered as Jinja globals.

Phase 7 — NT VISIBILITY INVARIANT
─────────────────────────────────
Every evaluation read helper accepts an optional
`requesting_user_role` kwarg. When the value is `'scout'`, the query
filters `AND created_by_role != 'nt_staff'`, hiding NT-staff
evaluations from scouts. Any other value (or None) applies no
additional filter — admin, TD, nt_staff, viewer see everything.

Routes that call these helpers MUST pass `current_user.role` through.
The kwarg defaults to None (no filter) so existing positional callers
keep working for admin-class views; scout-context routes that
forget to thread the param are caught by the synthetic E2E in
`migrations/_e2e_phase_7.py`.

Soft-delete invariant (Phase 5c-3) and NT visibility invariant
(Phase 7) compose — both apply independently to the same WHERE clause.
"""
import logging
from datetime import datetime
from app.db import _get_pool

log = logging.getLogger(__name__)


# Phase 7: SQL fragment for the NT visibility filter. Lives in one
# place so a future change to the policy (e.g. also filter viewer
# role) is a one-line edit. Returns "" when the requester is allowed
# to see NT evals, or the AND-clause when they're not.
def _nt_visibility_clause(requesting_user_role: str | None,
                          alias: str = "e") -> str:
    """Return the SQL fragment that hides nt_staff-created evaluations
    from the requesting user, or empty string if they're allowed to
    see them. Use with f-string composition (no parameter binding;
    the value is a literal known good column comparison).

    Phase 7.1: viewer role widened into the filtered set. Both
    'scout' and 'viewer' are frontline-only roles that should NOT
    see NT scratchpad evals. admin/TD/nt_staff still see everything.
    To narrow or widen the filtered set, edit this set literal —
    that's the single switch the rest of the codebase keys off."""
    if requesting_user_role in ('scout', 'viewer'):
        return f" AND {alias}.created_by_role != 'nt_staff'"
    return ""


# ───────── Arabic translation dicts (Phase 5c-2 — verbatim from spec) ─────────

NT_LEVEL_LABEL_AR = {
    "senior":    "المنتخب الأول",
    "u23":       "تحت 23",
    "u20":       "تحت 20",
    "u17":       "تحت 17",
    "not_ready": "غير جاهز حالياً",
}

RECOMMENDATION_LABEL_AR = {
    "call_up":      "استدعاء فوري",
    "shortlist":    "اضافة الى قائمة الترشحيات للفترة القادمة",
    "monitor":      "متابعة",
    "not_at_level": "لا يصل للمستوى",
    "release":      "لا يوجد اهتمام",
}

ELIGIBILITY_STATUS_LABEL_AR = {
    "bahraini":           "مواطن بحريني",
    "foreign_residency":  "مؤهل (إقامة)",
    "foreign_ancestry":   "مؤهل (نسب)",
    "foreign_other":      "مؤهل (أخرى)",
    "not_eligible":       "غير مؤهل",
    "unknown":            "غير معروف",
}

# Phase 5c-2.1: route label, used on the "Route:" supplementary line on the
# eligibility card after the redundant "Status:" line was removed.
NATIONALITY_ROUTE_LABEL_EN = {
    "bahraini":          "Bahraini citizen",
    "foreign_residency": "Foreign — residency",
    "foreign_ancestry":  "Foreign — ancestry",
    "foreign_other":     "Foreign — other route",
    "not_eligible":      "Not eligible",
    "unknown":           "Unknown",
}

# Display-friendly EN labels (mirror of the AR dicts so view templates can
# show "Senior NT" instead of raw "senior" without having to maintain a
# parallel mapping in templates).
NT_LEVEL_LABEL_EN = {
    "senior":    "Senior NT",
    "u23":       "U23",
    "u20":       "U20",
    "u17":       "U17",
    "not_ready": "Not yet ready",
}

RECOMMENDATION_LABEL_EN = {
    "call_up":      "Call up immediately",
    "shortlist":    "Shortlist for next window",
    "monitor":      "Monitor",
    "not_at_level": "Not at level",
    "release":      "Release / no further interest",
}

# Phase 5d: category labels for the scout-assessment section on /compare/view.
# Keys are UPPERCASE to match criteria_categories.code (TECH/TACT/PHYS/MENT).
CATEGORY_LABEL_EN = {
    "TECH": "Technical",
    "TACT": "Tactical",
    "PHYS": "Physical",
    "MENT": "Mentality",
}


def _conn():
    return _get_pool().getconn()


def _putconn(conn):
    _get_pool().putconn(conn)


# Required fields for submit (per locked decision)
_REQUIRED_ON_SUBMIT = ("nt_readiness_level", "recommendation")


def resolve_position_group_for_player(player_id: int) -> int | None:
    """Player → position_group_id via primary_position_id. None if neither set."""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.position_group_id
                FROM   players pl
                JOIN   positions p ON p.id = pl.primary_position_id
                WHERE  pl.id = %s
                """,
                (player_id,)
            )
            row = cur.fetchone()
        return row["position_group_id"] if row else None
    finally:
        _putconn(conn)


def get_form_criteria(position_group_id: int) -> list[dict]:
    """
    Every criterion that applies to this position group, plus category info,
    ordered by (category sort_order, criterion sort_order).
    """
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.id          AS criterion_id,
                       c.code        AS criterion_code,
                       c.name_en, c.name_ar,
                       cc.id         AS category_id,
                       cc.code       AS category_code,
                       cc.name_en    AS category_name_en,
                       cc.name_ar    AS category_name_ar,
                       cc.sort_order AS category_sort,
                       c.scale_min, c.scale_max, c.allow_half,
                       c.sort_order
                FROM   position_group_criteria pgc
                JOIN   criteria c             ON c.id = pgc.criterion_id
                JOIN   criteria_categories cc ON cc.id = c.category_id
                WHERE  pgc.position_group_id = %s
                  AND  c.is_active = TRUE
                ORDER  BY cc.sort_order, c.sort_order
                """,
                (position_group_id,)
            )
            return cur.fetchall() or []
    finally:
        _putconn(conn)


def get_recent_matches(limit: int = 50) -> list[dict]:
    """Most-recent-first match list for the dropdown."""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, match_date, home_team, away_team,
                       home_score, away_score, competition,
                       age_group, match_type, source
                FROM   matches
                ORDER  BY match_date DESC, id DESC
                LIMIT  %s
                """,
                (limit,)
            )
            return cur.fetchall() or []
    finally:
        _putconn(conn)


def get_or_create_draft(player_id: int, match_id: int, scout_id: int,
                        position_group_id: int,
                        creator_role: str = 'scout') -> dict:
    """
    Returns existing draft for (player, match, scout) if one exists,
    else creates a new evaluations row with status='draft'.

    DOES NOT include soft-deleted evaluations (Phase 5c-3 invariant) —
    a soft-deleted draft for the same tuple won't be reused; a fresh
    draft is created instead.

    `creator_role` (Phase 7): role of the user creating the draft.
    Stamped onto the row's `created_by_role`. Defaults to 'scout' to
    match the DB-side default; callers that may run as nt_staff
    (the evaluation form route in particular) MUST pass
    `current_user.role` explicitly.
    """
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM   evaluations
                WHERE  player_id    = %s
                  AND  match_id     = %s
                  AND  evaluator_id = %s
                  AND  status       = 'draft'
                  AND  deleted_at IS NULL
                ORDER  BY id DESC
                LIMIT  1
                """,
                (player_id, match_id, scout_id)
            )
            existing = cur.fetchone()
            if existing:
                return dict(existing)

            cur.execute(
                """
                INSERT INTO evaluations
                    (player_id, evaluator_id, position_group_id,
                     match_id, status, created_by_role)
                VALUES (%s, %s, %s, %s, 'draft', %s)
                RETURNING *
                """,
                (player_id, scout_id, position_group_id, match_id, creator_role)
            )
            new = cur.fetchone()
        conn.commit()
        return dict(new)
    finally:
        _putconn(conn)


def get_evaluation(eval_id: int, include_deleted: bool = False,
                   requesting_user_role: str | None = None) -> dict | None:
    """
    Single evaluation row joined to player and match for context.

    DOES NOT include soft-deleted evaluations (Phase 5c-3 invariant)
    unless `include_deleted=True` (used only by the admin recovery flow).

    NT VISIBILITY INVARIANT (Phase 7): when requesting_user_role='scout',
    NT-staff-created evaluations return None (same shape as not-found,
    so a scout cannot probe for the existence of an NT eval by id).
    """
    conn = _conn()
    try:
        with conn.cursor() as cur:
            sql = """
                SELECT e.*,
                       pl.full_name        AS player_name,
                       pl.full_name_ar     AS player_name_ar,
                       pl.primary_position_id,
                       pl.age_group        AS age_group,
                       u.full_name         AS evaluator_name,
                       m.match_date        AS m_date,
                       m.home_team         AS m_home,
                       m.away_team         AS m_away,
                       m.home_score        AS m_home_score,
                       m.away_score        AS m_away_score,
                       m.competition       AS m_competition
                FROM   evaluations e
                JOIN   players pl ON pl.id = e.player_id
                JOIN   users   u  ON u.id  = e.evaluator_id
                LEFT JOIN matches m ON m.id = e.match_id
                WHERE  e.id = %s
            """
            if not include_deleted:
                sql += " AND e.deleted_at IS NULL"
            sql += _nt_visibility_clause(requesting_user_role)
            cur.execute(sql, (eval_id,))
            row = cur.fetchone()
        return dict(row) if row else None
    finally:
        _putconn(conn)


def get_evaluation_scores(eval_id: int) -> dict[int, dict]:
    """
    Returns {criterion_id: {'score': float|None, 'is_not_applicable': bool}}
    for prefilling the tri-state form on draft reload (Phase 5c-1.1).
    """
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT criterion_id, score, is_not_applicable
                FROM   evaluation_scores
                WHERE  evaluation_id = %s
                """,
                (eval_id,)
            )
            return {
                r["criterion_id"]: {
                    "score": float(r["score"]) if r["score"] is not None else None,
                    "is_not_applicable": bool(r["is_not_applicable"]),
                }
                for r in cur.fetchall()
            }
    finally:
        _putconn(conn)


def save_evaluation_scores(eval_id: int, scores: dict[int, dict]) -> int:
    """
    DELETE-then-INSERT all evaluation_scores for this evaluation (Phase 5c-1.1).

    `scores` shape (from forms.parse_score_inputs):
        {criterion_id: {'score': float|None, 'is_not_applicable': bool}}

    Untouched criteria (absent from `scores`) get their existing row removed.
    Rated criteria get a row with score set, is_not_applicable=FALSE.
    N/A criteria get a row with score=NULL, is_not_applicable=TRUE.

    The DB-side CHECK constraint enforces (rated XOR na) per row, so any
    malformed payload would fail the INSERT and roll back the whole save.

    Returns count of rows inserted (i.e. number of decided criteria).
    """
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM evaluation_scores WHERE evaluation_id = %s",
                (eval_id,)
            )
            for crit_id, payload in scores.items():
                cur.execute(
                    """
                    INSERT INTO evaluation_scores
                        (evaluation_id, criterion_id, score, is_not_applicable)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (eval_id, crit_id, payload["score"], payload["is_not_applicable"])
                )
        conn.commit()
        return len(scores)
    finally:
        _putconn(conn)


_META_FIELDS = (
    "summary",
    "recommendation",
    "nt_readiness_level",
    "eligibility_status",
    "eligibility_notes",
    "comparable_player",
    "minutes_observed",
    "match_id",
)


def update_evaluation_meta(eval_id: int, fields: dict) -> None:
    """Write provided meta fields onto an evaluation row. Unknown keys ignored."""
    cols = [k for k in fields if k in _META_FIELDS]
    if not cols:
        return
    set_clauses = ", ".join(f"{c} = %s" for c in cols)
    params = [fields[c] for c in cols] + [eval_id]
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE evaluations SET {set_clauses}, updated_at = NOW() WHERE id = %s",
                params
            )
        conn.commit()
    finally:
        _putconn(conn)


def submit_draft(eval_id: int, scout_id: int) -> tuple[bool, str]:
    """
    Validate required fields and transition draft → submitted.
    Only the original scout can submit their own draft.
    Returns (ok, message).

    DOES NOT include soft-deleted evaluations (Phase 5c-3 invariant) —
    a soft-deleted draft will appear as "not found" here.
    """
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM evaluations WHERE id = %s AND deleted_at IS NULL",
                (eval_id,)
            )
            ev = cur.fetchone()
            if not ev:
                return False, "Evaluation not found."
            if ev["evaluator_id"] != scout_id:
                return False, "Only the original scout can submit this evaluation."
            if ev["status"] != "draft":
                return False, f"Evaluation is already {ev['status']}; cannot submit."
            for f in _REQUIRED_ON_SUBMIT:
                if not ev.get(f):
                    return False, f"Missing required field: {f.replace('_', ' ')}."

            cur.execute(
                """
                UPDATE evaluations
                SET    status = 'submitted',
                       submitted_at = NOW(),
                       updated_at = NOW()
                WHERE  id = %s
                """,
                (eval_id,)
            )
        conn.commit()
        return True, "Submitted."
    finally:
        _putconn(conn)


# ───────────── Phase 5c-2: history, lock, admin-edit, summary ─────────────

def get_player_evaluations(player_id: int,
                           status_filter: list[str] | None = None,
                           requesting_user_role: str | None = None) -> list[dict]:
    """
    Returns evaluations for a player, ordered most-recent-first.
    Joins evaluator + last_edited_by user names and (optional) match info.
    Each row also gets a `scores` list of {criterion_id, score,
    is_not_applicable, name_en, name_ar, category_code} for the expand-
    detail render in the history card.

    `status_filter` (optional): list of statuses to include; default is
    ['submitted','locked'] — drafts are excluded from the public history
    view since they're scout-private.

    DOES NOT include soft-deleted evaluations (Phase 5c-3 invariant) —
    use the admin recovery page for that.

    Each returned row also contains `created_by_role` so templates can
    render the NT badge (Phase 7).

    NT VISIBILITY INVARIANT (Phase 7): when requesting_user_role='scout',
    nt_staff-authored evaluations are filtered out at the SQL layer.
    """
    if status_filter is None:
        status_filter = ["submitted", "locked"]

    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT e.id, e.player_id, e.status,
                       e.evaluator_id, e.position_group_id,
                       e.match_id, e.match_label, e.match_date, e.competition,
                       e.minutes_observed, e.summary, e.recommendation,
                       e.nt_readiness_level, e.eligibility_status,
                       e.eligibility_notes, e.comparable_player,
                       e.submitted_at, e.locked_at, e.locked_by, e.locked_reason,
                       e.last_edited_by, e.last_edited_at,
                       e.created_by_role,
                       e.created_at, e.updated_at,
                       u.full_name        AS evaluator_name,
                       le.full_name       AS last_edited_by_name,
                       lk.full_name       AS locked_by_name,
                       m.match_date       AS m_date,
                       m.home_team        AS m_home,
                       m.away_team        AS m_away,
                       m.competition      AS m_competition
                FROM   evaluations e
                JOIN   users u  ON u.id  = e.evaluator_id
                LEFT JOIN users le ON le.id = e.last_edited_by
                LEFT JOIN users lk ON lk.id = e.locked_by
                LEFT JOIN matches m ON m.id = e.match_id
                WHERE  e.player_id = %s
                  AND  e.status = ANY(%s)
                  AND  e.deleted_at IS NULL
                  {_nt_visibility_clause(requesting_user_role)}
                ORDER  BY COALESCE(e.submitted_at, e.created_at) DESC, e.id DESC
                """,
                (player_id, status_filter)
            )
            evals = [dict(r) for r in cur.fetchall() or []]

            if not evals:
                return []

            eval_ids = [e["id"] for e in evals]
            cur.execute(
                """
                SELECT es.evaluation_id, es.criterion_id, es.score,
                       es.is_not_applicable,
                       c.name_en, c.name_ar, c.sort_order,
                       cc.code        AS category_code,
                       cc.name_en     AS category_name_en,
                       cc.name_ar     AS category_name_ar,
                       cc.sort_order  AS category_sort_order
                FROM   evaluation_scores es
                JOIN   criteria c ON c.id = es.criterion_id
                JOIN   criteria_categories cc ON cc.id = c.category_id
                WHERE  es.evaluation_id = ANY(%s)
                ORDER  BY cc.sort_order, c.sort_order
                """,
                (eval_ids,)
            )
            scores_by_eval: dict[int, list[dict]] = {}
            for r in cur.fetchall() or []:
                d = dict(r)
                if d["score"] is not None:
                    d["score"] = float(d["score"])
                scores_by_eval.setdefault(d["evaluation_id"], []).append(d)
            for e in evals:
                e["scores"] = scores_by_eval.get(e["id"], [])
        return evals
    finally:
        _putconn(conn)


def nt_readiness_summary(player_id: int, last_n: int = 3,
                         requesting_user_role: str | None = None) -> dict:
    """
    Pulls the last N submitted-or-locked evaluations and tallies the
    nt_readiness_level votes. Returns:
        {'total': int, 'breakdown': {'Senior NT': 1, 'U23': 2, ...}}

    Breakdown keys are display labels (EN); use NT_LEVEL_LABEL_AR if the
    template needs the Arabic version.

    DOES NOT include soft-deleted evaluations (Phase 5c-3 invariant).
    NT VISIBILITY INVARIANT (Phase 7): when requesting_user_role='scout',
    NT-staff-authored votes are excluded from the breakdown.
    """
    # Bare-table query (no alias); inline the literal clause manually.
    nt_clause = (" AND created_by_role != 'nt_staff'"
                 if requesting_user_role in ('scout', 'viewer') else "")

    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT nt_readiness_level
                FROM   evaluations
                WHERE  player_id = %s
                  AND  status IN ('submitted','locked')
                  AND  nt_readiness_level IS NOT NULL
                  AND  deleted_at IS NULL
                  {nt_clause}
                ORDER  BY COALESCE(submitted_at, created_at) DESC, id DESC
                LIMIT  %s
                """,
                (player_id, last_n)
            )
            rows = cur.fetchall() or []

        breakdown: dict[str, int] = {}
        for r in rows:
            label = NT_LEVEL_LABEL_EN.get(r["nt_readiness_level"], r["nt_readiness_level"])
            breakdown[label] = breakdown.get(label, 0) + 1
        return {"total": len(rows), "breakdown": breakdown}
    finally:
        _putconn(conn)


def lock_evaluation(eval_id: int, locker_id: int) -> tuple[bool, str]:
    """
    Transition status submitted → locked. admin/TD only (route enforces).
    Returns (ok, message).
    """
    conn = _conn()
    try:
        with conn.cursor() as cur:
            # DOES NOT include soft-deleted evaluations (Phase 5c-3 invariant)
            cur.execute("SELECT status FROM evaluations WHERE id = %s AND deleted_at IS NULL", (eval_id,))
            r = cur.fetchone()
            if not r:
                return False, "Evaluation not found."
            if r["status"] != "submitted":
                return False, f"Cannot lock — current status is {r['status']}."
            cur.execute(
                """
                UPDATE evaluations
                SET    status = 'locked',
                       locked_at = NOW(),
                       locked_by = %s,
                       locked_reason = NULL,
                       updated_at = NOW()
                WHERE  id = %s
                """,
                (locker_id, eval_id)
            )
        conn.commit()
        return True, "Evaluation locked."
    finally:
        _putconn(conn)


def unlock_evaluation(eval_id: int, unlocker_id: int, reason: str) -> tuple[bool, str]:
    """
    Reverse a lock. Requires `reason` (>= 10 chars). Returns (ok, message).
    Stored on `locked_reason` so the audit trail is durable even after
    re-lock; the audit_log row also captures it.
    """
    if not reason or len(reason.strip()) < 10:
        return False, "Unlock reason must be at least 10 characters."
    conn = _conn()
    try:
        with conn.cursor() as cur:
            # DOES NOT include soft-deleted evaluations (Phase 5c-3 invariant)
            cur.execute("SELECT status FROM evaluations WHERE id = %s AND deleted_at IS NULL", (eval_id,))
            r = cur.fetchone()
            if not r:
                return False, "Evaluation not found."
            if r["status"] != "locked":
                return False, f"Cannot unlock — current status is {r['status']}."
            cur.execute(
                """
                UPDATE evaluations
                SET    status = 'submitted',
                       locked_at = NULL,
                       locked_by = NULL,
                       locked_reason = %s,
                       updated_at = NOW()
                WHERE  id = %s
                """,
                (reason.strip(), eval_id)
            )
        conn.commit()
        return True, "Evaluation unlocked."
    finally:
        _putconn(conn)


def group_scores_by_category(scores: list[dict]) -> list[dict]:
    """
    Group a flat list of score rows (from get_player_evaluations) by category
    for the section-collapsible expanded view (Phase 5c-2.1).

    Each input row must include: criterion_id, score, is_not_applicable,
    name_en, name_ar, category_code, category_name_en, category_name_ar,
    category_sort_order.

    Returns list of dicts:
        {'code', 'name_en', 'name_ar', 'sort_order',
         'rated_count', 'na_count', 'avg_score' (None if 0 rated),
         'items': [<original score dicts in this category>]}

    Empty categories (0 rated AND 0 N/A) are omitted entirely. Untouched
    criteria simply don't have rows; nothing to count.
    """
    by_cat: dict = {}
    for s in scores:
        code = s.get("category_code")
        if code not in by_cat:
            by_cat[code] = {
                "code":        code,
                "name_en":     s.get("category_name_en"),
                "name_ar":     s.get("category_name_ar"),
                "sort_order":  s.get("category_sort_order")
                              or s.get("category_sort")  # back-compat alias
                              or 99,
                "rated_count": 0,
                "na_count":    0,
                "avg_score":   None,
                "items":       [],
                "_score_sum":  0.0,
            }
        by_cat[code]["items"].append(s)
        if s.get("is_not_applicable"):
            by_cat[code]["na_count"] += 1
        elif s.get("score") is not None:
            by_cat[code]["rated_count"] += 1
            by_cat[code]["_score_sum"]  += float(s["score"])

    out = []
    for cat in by_cat.values():
        if cat["rated_count"] > 0:
            cat["avg_score"] = round(cat["_score_sum"] / cat["rated_count"], 1)
        del cat["_score_sum"]
        out.append(cat)
    return sorted(out, key=lambda c: c["sort_order"])


def soft_delete_evaluation(eval_id: int, deleter_id: int, reason: str,
                           is_admin_or_td: bool) -> tuple[bool, str]:
    """
    Soft-delete (Phase 5c-3). Permission rules:
      - Scout: can delete own DRAFT evaluations only
      - Admin/TD: can delete any evaluation EXCEPT locked ones
      - Locked evaluations cannot be deleted (must unlock first)
    Reason: min 10 chars; enforced both here AND by the DB CHECK.

    Returns (ok, message).
    """
    if not reason or len(reason.strip()) < 10:
        return False, "Reason must be at least 10 characters."
    reason = reason.strip()

    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT status, evaluator_id, deleted_at
                   FROM   evaluations WHERE id = %s""",
                (eval_id,)
            )
            r = cur.fetchone()
            if not r:
                return False, "Evaluation not found."
            if r["deleted_at"] is not None:
                return False, "Evaluation is already deleted."
            if r["status"] == "locked":
                return False, "Cannot delete a locked evaluation; unlock first."
            if not is_admin_or_td:
                # Scout: own drafts only
                if r["evaluator_id"] != deleter_id:
                    return False, "You can only delete your own drafts."
                if r["status"] != "draft":
                    return False, "Scouts can only delete their own draft evaluations."

            cur.execute(
                """UPDATE evaluations
                   SET    deleted_at = NOW(), deleted_by = %s, deleted_reason = %s,
                          updated_at = NOW()
                   WHERE  id = %s""",
                (deleter_id, reason, eval_id)
            )
        conn.commit()
        return True, "Evaluation deleted."
    finally:
        _putconn(conn)


def restore_evaluation(eval_id: int, restorer_id: int) -> tuple[bool, str]:
    """
    Reverse a soft-delete (admin/TD only — route enforces).
    Clears all three deleted_* columns atomically (CHECK constraint
    requires all-three-or-none).
    """
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT deleted_at FROM evaluations WHERE id = %s",
                (eval_id,)
            )
            r = cur.fetchone()
            if not r:
                return False, "Evaluation not found."
            if r["deleted_at"] is None:
                return False, "Evaluation is not deleted."

            cur.execute(
                """UPDATE evaluations
                   SET    deleted_at = NULL, deleted_by = NULL, deleted_reason = NULL,
                          updated_at = NOW()
                   WHERE  id = %s""",
                (eval_id,)
            )
        conn.commit()
        return True, "Evaluation restored."
    finally:
        _putconn(conn)


def list_deleted_evaluations() -> list[dict]:
    """
    Admin recovery view — explicitly returns ONLY soft-deleted evaluations.
    The one place in the codebase where the deleted_at IS NULL invariant
    is intentionally inverted.
    """
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT e.id, e.player_id, e.status,
                       e.evaluator_id, e.deleted_at, e.deleted_reason,
                       u_ev.full_name  AS evaluator_name,
                       u_del.full_name AS deleted_by_name,
                       pl.full_name    AS player_name,
                       pl.full_name_ar AS player_name_ar,
                       e.match_label, e.match_date,
                       m.match_date AS m_date,
                       m.home_team  AS m_home,
                       m.away_team  AS m_away
                FROM   evaluations e
                JOIN   users u_ev   ON u_ev.id  = e.evaluator_id
                JOIN   users u_del  ON u_del.id = e.deleted_by
                JOIN   players pl   ON pl.id    = e.player_id
                LEFT JOIN matches m ON m.id     = e.match_id
                WHERE  e.deleted_at IS NOT NULL
                ORDER  BY e.deleted_at DESC
            """)
            return [dict(r) for r in cur.fetchall() or []]
    finally:
        _putconn(conn)


def get_player_bio_counts(player_id: int,
                          requesting_user_role: str | None = None) -> dict:
    """
    Bio counts for the player profile header (Phase 5c-3):
      - wyscout_match_count: rows in wyscout_match_stats
      - evaluation_count: non-deleted evaluations (any status)

    Both filters honor the soft-delete invariant.
    NT VISIBILITY INVARIANT (Phase 7): when requesting_user_role='scout',
    the evaluation_count excludes nt_staff-authored rows.
    """
    nt_clause = (" AND created_by_role != 'nt_staff'"
                 if requesting_user_role in ('scout', 'viewer') else "")
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS n FROM wyscout_match_stats WHERE player_id = %s",
                (player_id,)
            )
            wms = cur.fetchone()["n"]
            cur.execute(
                f"""SELECT COUNT(*) AS n FROM evaluations
                    WHERE player_id = %s AND deleted_at IS NULL {nt_clause}""",
                (player_id,)
            )
            evc = cur.fetchone()["n"]
        return {"wyscout_match_count": int(wms), "evaluation_count": int(evc)}
    finally:
        _putconn(conn)


def admin_edit_evaluation(eval_id: int, admin_id: int,
                          meta: dict, scores: dict | None = None
                          ) -> tuple[bool, str, list[str]]:
    """
    Admin/TD overwrites scout content on a SUBMITTED (not locked)
    evaluation. Original evaluator_id is preserved. Sets
    last_edited_by = admin_id and last_edited_at = NOW().

    Returns (ok, message, fields_changed) — fields_changed is a list of
    metadata field names actually written (so audit_log can record what
    was touched, not just "edit happened").

    If scores is provided (a dict from forms.parse_score_inputs), runs
    the same DELETE-then-INSERT as a normal save. Pass None to leave
    scores untouched.
    """
    conn = _conn()
    fields_changed: list[str] = []
    try:
        with conn.cursor() as cur:
            # DOES NOT include soft-deleted evaluations (Phase 5c-3 invariant)
            cur.execute("SELECT status FROM evaluations WHERE id = %s AND deleted_at IS NULL", (eval_id,))
            r = cur.fetchone()
            if not r:
                return False, "Evaluation not found.", []
            if r["status"] != "submitted":
                return False, ("Cannot admin-edit — only submitted evaluations are "
                               f"editable; current status is {r['status']}."), []

            # Apply meta updates via the existing _META_FIELDS whitelist
            cols = [k for k in meta if k in _META_FIELDS and meta[k] is not None]
            if cols:
                set_parts = ", ".join(f"{c} = %s" for c in cols)
                params = [meta[c] for c in cols] + [admin_id, eval_id]
                cur.execute(
                    f"""
                    UPDATE evaluations
                    SET {set_parts},
                        last_edited_by = %s,
                        last_edited_at = NOW(),
                        updated_at     = NOW()
                    WHERE id = %s
                    """,
                    params
                )
                fields_changed = cols
            else:
                # Even with no meta change, mark the edit so the badge appears
                cur.execute(
                    """
                    UPDATE evaluations
                    SET    last_edited_by = %s,
                           last_edited_at = NOW(),
                           updated_at     = NOW()
                    WHERE  id = %s
                    """,
                    (admin_id, eval_id)
                )

            if scores is not None:
                # Same DELETE-then-INSERT pattern as save_evaluation_scores
                cur.execute(
                    "DELETE FROM evaluation_scores WHERE evaluation_id = %s",
                    (eval_id,)
                )
                for crit_id, payload in scores.items():
                    cur.execute(
                        """
                        INSERT INTO evaluation_scores
                            (evaluation_id, criterion_id, score, is_not_applicable)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (eval_id, crit_id, payload["score"], payload["is_not_applicable"])
                    )
                fields_changed.append("scores")
        conn.commit()
        return True, "Edit applied.", fields_changed
    finally:
        _putconn(conn)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 5d: scout dimension on the comparison page
# ─────────────────────────────────────────────────────────────────────────────

def compute_category_averages(scores: list[dict]) -> dict[str, float]:
    """
    Returns {category_code: avg_score} for the rated criteria in `scores`.

    Excludes N/A and untouched (score IS NULL) entries from the average.
    Categories with zero rated criteria are omitted entirely.

    Each input row should have at least 'score', 'is_not_applicable',
    and 'category_code' keys (matching what get_player_evaluations and
    get_evaluation_scores produce).
    """
    by_cat: dict[str, dict] = {}
    for s in scores:
        if s.get("is_not_applicable") or s.get("score") is None:
            continue
        cat = s.get("category_code")
        if not cat:
            continue
        if cat not in by_cat:
            by_cat[cat] = {"sum": 0.0, "count": 0}
        by_cat[cat]["sum"]   += float(s["score"])
        by_cat[cat]["count"] += 1
    return {
        cat: round(d["sum"] / d["count"], 1)
        for cat, d in by_cat.items()
        if d["count"] > 0
    }


def group_criteria_by_category(criteria: list[dict]) -> list[dict]:
    """
    Phase 5d patch: pre-group a flat list of criterion rows (from
    `get_form_criteria`) by category, preserving the (category sort,
    criterion sort) order. Mirror of `group_scores_by_category` but for
    criteria-only rows (no score data).

    Built in Python because the original drilldown template tried to do
    this with `{% set _ = list.append(...) %}` — Jinja2's set inside a
    for loop didn't carry the mutation across iterations, so only the
    first category rendered. Pre-grouping in Python sidesteps it.

    Returns: [{'code', 'name_en', 'name_ar', 'sort_order', 'items'}, ...]
    """
    by_cat: dict = {}
    cat_order: list[str] = []
    for c in criteria:
        code = c.get("category_code")
        if code not in by_cat:
            by_cat[code] = {
                "code":       code,
                "name_en":    c.get("category_name_en"),
                "name_ar":    c.get("category_name_ar"),
                "sort_order": c.get("category_sort_order")
                              or c.get("category_sort")
                              or 99,
                "items":      [],
            }
            cat_order.append(code)
        by_cat[code]["items"].append(c)
    return [by_cat[code] for code in cat_order]


def get_evaluation_count_active(player_id: int,
                                requesting_user_role: str | None = None) -> int:
    """
    Count submitted+locked, non-deleted evaluations for a player.
    DOES NOT include drafts or soft-deleted (Phase 5c-3 invariant).
    NT VISIBILITY INVARIANT (Phase 7): when requesting_user_role='scout',
    nt_staff-authored rows are excluded from the count.
    """
    nt_clause = (" AND created_by_role != 'nt_staff'"
                 if requesting_user_role in ('scout', 'viewer') else "")
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""SELECT COUNT(*) AS n FROM evaluations
                    WHERE player_id = %s
                      AND status IN ('submitted','locked')
                      AND deleted_at IS NULL
                      {nt_clause}""",
                (player_id,)
            )
            return int(cur.fetchone()["n"])
    finally:
        _putconn(conn)


def _fetch_eval_scores_with_categories(conn, eval_id: int) -> list[dict]:
    """Internal: scores for one evaluation + category metadata."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT es.criterion_id, es.score, es.is_not_applicable,
                   c.code  AS criterion_code,
                   c.name_en, c.name_ar,
                   cc.code AS category_code,
                   cc.name_en AS category_name_en,
                   cc.name_ar AS category_name_ar,
                   cc.sort_order AS category_sort_order,
                   c.sort_order
            FROM   evaluation_scores es
            JOIN   criteria c             ON c.id  = es.criterion_id
            JOIN   criteria_categories cc ON cc.id = c.category_id
            WHERE  es.evaluation_id = %s
            ORDER  BY cc.sort_order, c.sort_order
            """,
            (eval_id,)
        )
        rows = cur.fetchall() or []
    out = []
    for r in rows:
        d = dict(r)
        if d.get("score") is not None:
            d["score"] = float(d["score"])
        out.append(d)
    return out


def build_scout_radar_data(data: dict, grouped_criteria: list[dict]) -> dict:
    """
    Phase 5d-1: shape Chart.js-ready radar configs for the scout-assessment
    section on /compare/view. Pure data transform — no DB hits; consumes
    `data['players']` (each with `scout_data` and `scores_by_criterion`,
    populated by `_enrich_for_scout_section` in app.players) and
    `grouped_criteria` (the criteria union grouped by category).

    Returns:
        {
          'category':      {'axes': [...], 'datasets': [...]},
          'per_category':  {cat_code: {'category_label', 'axes', 'datasets'}, ...}
        }

    Each dataset shape (uniform across all 5 radars):
        {'label': <player first name>,
         'values': [float, ...],          # always numeric for plotting
         'annotations': [str, ...]}       # parallel: 'rated' | 'na' | 'absent'

    annotation values drive tooltip text in scout_radars.js:
      - 'rated':  values[i] is the real score; tooltip shows it
      - 'na':     values[i] is 0; tooltip says "N/A"
      - 'absent': values[i] is 0; tooltip says "—" (criterion doesn't
                  apply to this player's position OR untouched)

    Why parallel arrays instead of nullable values? Chart.js's radar type
    treats nulls as gaps that break the polygon — visually messy when one
    player has 12/16 axes filled and another has 9/16. Plotting 0 with
    an annotation overlay keeps the polygons closed and the truth in
    the tooltip.
    """
    CAT_ORDER  = ['TECH', 'TACT', 'PHYS', 'MENT']
    CAT_LABELS = {'TECH': 'Technical', 'TACT': 'Tactical',
                  'PHYS': 'Physical', 'MENT': 'Mentality'}

    # ── Top "category averages" radar (4 fixed axes) ──────────────────
    cat_axes = [CAT_LABELS[c] for c in CAT_ORDER]
    cat_datasets = []
    for p in data.get('players') or []:
        first = ((p.get('full_name') or '').split(' ') or [''])[0]
        avgs  = ((p.get('scout_data') or {}).get('category_averages') or {})
        values, annotations = [], []
        for c in CAT_ORDER:
            v = avgs.get(c)
            if v is None:
                values.append(0.0)
                annotations.append('absent')
            else:
                values.append(float(v))
                annotations.append('rated')
        cat_datasets.append({
            'label':       first,
            'values':      values,
            'annotations': annotations,
        })

    # ── Per-category drill-down radars ────────────────────────────────
    per_category: dict[str, dict] = {}
    for cat in grouped_criteria or []:
        items = cat.get('items') or []
        axes  = [(c.get('name_en') or c.get('criterion_code') or '?') for c in items]
        datasets = []
        for p in data.get('players') or []:
            first = ((p.get('full_name') or '').split(' ') or [''])[0]
            sbc   = p.get('scores_by_criterion') or {}
            values, annotations = [], []
            for c in items:
                row = sbc.get(c.get('criterion_id'))
                if row is None:
                    values.append(0.0); annotations.append('absent')
                elif row.get('is_not_applicable'):
                    values.append(0.0); annotations.append('na')
                elif row.get('score') is not None:
                    values.append(float(row['score'])); annotations.append('rated')
                else:
                    values.append(0.0); annotations.append('absent')
            datasets.append({
                'label':       first,
                'values':      values,
                'annotations': annotations,
            })
        per_category[cat.get('code')] = {
            'category_label': CAT_LABELS.get(cat.get('code'), cat.get('name_en')),
            'axes':           axes,
            'datasets':       datasets,
        }

    return {'category': {'axes': cat_axes, 'datasets': cat_datasets},
            'per_category': per_category}


def get_player_evaluation_aggregate(player_id: int,
                                    mode: str = "latest",
                                    requesting_user_role: str | None = None) -> dict | None:
    """
    Phase 5d aggregator for the scout-section on the comparison page.

    `mode='latest'`   — returns most-recent submitted+locked, non-deleted eval.
    `mode='averaged'` — averages across ALL submitted+locked, non-deleted evals.

    Returns None if the player has no qualifying evaluations.

    Soft-delete invariant: filters `WHERE deleted_at IS NULL`. Locked evals
    are INCLUDED (locked is workflow protection, not data hiding).
    NT VISIBILITY INVARIANT (Phase 7): when requesting_user_role='scout',
    nt_staff-authored evals are excluded from both modes — so a scout
    viewing a player on the comparison page sees averages computed from
    scout/admin evals only.

    Result shape (both modes):
        {
          'eval_id':              int | None,    # latest only; None for averaged
          'submitted_at':         datetime | None,
          'evaluator_name':       str,           # "N evaluations averaged" in averaged mode
          'nt_readiness_level':   str | None,    # mode (most-frequent) in averaged
          'recommendation':       str | None,    # mode (most-frequent) in averaged
          'summary':              str | None,    # latest only; None in averaged
          'category_averages':    {cat_code: float, ...},
          'scores': [
              {'criterion_id', 'criterion_code', 'name_en', 'name_ar',
               'category_code', 'category_name_en', 'category_name_ar',
               'category_sort_order', 'sort_order',
               'score', 'is_not_applicable',
               'eval_count': int (averaged mode only — # of evals that rated this)},
              ...
          ],
        }
    """
    if mode not in ("latest", "averaged"):
        raise ValueError(f"mode must be 'latest' or 'averaged', got {mode!r}")

    conn = _conn()
    try:
        with conn.cursor() as cur:
            # Phase 5d-patch: LEFT JOIN matches so latest mode can show the
            # match label ("Khalidiya vs Manama" or "Freestanding").
            cur.execute(
                f"""
                SELECT e.id, e.submitted_at, e.locked_at,
                       e.nt_readiness_level, e.recommendation, e.summary,
                       e.created_by_role,
                       u.full_name AS evaluator_name,
                       e.match_id  AS linked_match_id,
                       m.match_date  AS m_date,
                       m.home_team   AS m_home,
                       m.away_team   AS m_away,
                       m.competition AS m_competition
                FROM   evaluations e
                LEFT JOIN users u   ON u.id = e.evaluator_id
                LEFT JOIN matches m ON m.id = e.match_id
                WHERE  e.player_id = %s
                  AND  e.status IN ('submitted','locked')
                  AND  e.deleted_at IS NULL
                  {_nt_visibility_clause(requesting_user_role)}
                ORDER BY COALESCE(e.submitted_at, e.created_at) DESC, e.id DESC
                """,
                (player_id,)
            )
            evals = [dict(r) for r in cur.fetchall() or []]

        if not evals:
            return None

        def _match_label(ev_row):
            if not ev_row.get("linked_match_id"):
                return "Freestanding (no match linked)"
            home = ev_row.get("m_home") or "?"
            away = ev_row.get("m_away") or "?"
            return f"{home} vs {away}"

        if mode == "latest":
            ev = evals[0]
            scores = _fetch_eval_scores_with_categories(conn, ev["id"])
            return {
                "eval_id":            ev["id"],
                "submitted_at":       ev["submitted_at"],
                "evaluator_name":     ev["evaluator_name"],
                "nt_readiness_level": ev["nt_readiness_level"],
                "recommendation":     ev["recommendation"],
                "summary":            ev["summary"],
                "match_label":        _match_label(ev),
                "match_date":         ev["m_date"],
                "category_averages":  compute_category_averages(scores),
                "scores":             scores,
            }

        # ── averaged mode ─────────────────────────────────────────────
        # 1. Pull all scores for all the qualifying evaluations
        # 2. For each criterion: average across rated entries; carry N/A
        #    only if EVERY entry was N/A (otherwise drop — we keep the rated
        #    average); drop untouched entirely.
        per_crit: dict[int, dict] = {}
        for ev in evals:
            for s in _fetch_eval_scores_with_categories(conn, ev["id"]):
                cid = s["criterion_id"]
                slot = per_crit.setdefault(cid, {
                    "criterion_id":        cid,
                    "criterion_code":      s["criterion_code"],
                    "name_en":             s["name_en"],
                    "name_ar":             s["name_ar"],
                    "category_code":       s["category_code"],
                    "category_name_en":    s["category_name_en"],
                    "category_name_ar":    s["category_name_ar"],
                    "category_sort_order": s["category_sort_order"],
                    "sort_order":          s["sort_order"],
                    "_rated_values":       [],
                    "_na_count":           0,
                })
                if s["is_not_applicable"]:
                    slot["_na_count"] += 1
                elif s["score"] is not None:
                    slot["_rated_values"].append(float(s["score"]))

        averaged_scores = []
        for cid, d in per_crit.items():
            rated  = d.pop("_rated_values")
            na_n   = d.pop("_na_count")
            if rated:
                d["score"]              = round(sum(rated) / len(rated), 1)
                d["is_not_applicable"]  = False
                d["eval_count"]         = len(rated)
            elif na_n > 0:
                # Every evaluation that touched this criterion called it N/A.
                d["score"]              = None
                d["is_not_applicable"]  = True
                d["eval_count"]         = na_n
            else:
                continue  # purely untouched — skip
            averaged_scores.append(d)
        averaged_scores.sort(key=lambda s: (s["category_sort_order"], s["sort_order"]))

        # NT level + recommendation: mode (most-frequent), ties broken by recency
        from collections import Counter
        def _mode_with_recency(field):
            values = [(ev["submitted_at"], ev[field]) for ev in evals if ev.get(field)]
            if not values:
                return None
            counts = Counter(v for _, v in values)
            top = max(counts.values())
            tied = {v for v, c in counts.items() if c == top}
            # evals already ordered most-recent-first
            for _, v in values:
                if v in tied:
                    return v
            return None

        return {
            "eval_id":            None,
            "submitted_at":       evals[0]["submitted_at"],  # most-recent reference
            "evaluator_name":     f"{len(evals)} evaluations averaged",
            "nt_readiness_level": _mode_with_recency("nt_readiness_level"),
            "recommendation":     _mode_with_recency("recommendation"),
            "summary":            None,  # not meaningful for averaged
            "match_label":        None,  # multiple matches; template skips when None
            "match_date":         None,
            "category_averages":  compute_category_averages(averaged_scores),
            "scores":             averaged_scores,
        }
    finally:
        _putconn(conn)
