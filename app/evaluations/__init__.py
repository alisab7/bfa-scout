"""
Evaluations blueprint — Phase 5c-1 + 5c-2.

Routes:
  GET  /players/<player_id>/evaluate      — render form / load draft
  POST /players/<player_id>/evaluate      — save draft or submit
  GET  /evaluations/<eval_id>             — view evaluation
  POST /evaluations/<eval_id>             — update own draft
  POST /evaluations/<eval_id>/submit      — explicit draft → submitted
  POST /evaluations/<eval_id>/lock        — admin/TD lock submitted (5c-2)
  POST /evaluations/<eval_id>/unlock      — admin/TD unlock with reason (5c-2)
  POST /evaluations/<eval_id>/admin-edit  — admin/TD overwrite content (5c-2)
  POST /matches/new-inline                — inline match create (JSON)
"""
from datetime import date, datetime
import json
import logging

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, jsonify, abort)
from flask_login import current_user

from app.auth.decorators import (
    scout_or_above, any_authenticated, admin_or_td_required,
    youth_section_access, require_youth_access,
)
from flask_login import login_required
from app.auth.audit import log_audit
from app.db import get_db
from app.evaluations.helpers import (
    resolve_position_group_for_player,
    get_form_criteria,
    get_recent_matches,
    get_or_create_draft,
    get_own_draft_for_player,
    get_evaluation,
    get_evaluation_scores,
    save_evaluation_scores,
    update_evaluation_meta,
    submit_draft,
    lock_evaluation,
    unlock_evaluation,
    admin_edit_evaluation,
    soft_delete_evaluation,
    restore_evaluation,
)
from app.evaluations.forms import parse_score_inputs, parse_meta_fields

bp = Blueprint('evaluations', __name__)
log = logging.getLogger(__name__)

RECENT_MATCH_LIMIT = 50


# ─────────────────────────────────────────────────────────────────────────────
# Helpers reused across routes
# ─────────────────────────────────────────────────────────────────────────────

def _load_player(player_id: int):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT pl.id, pl.full_name, pl.full_name_ar, pl.dob,
                   pl.primary_position_id, pl.is_active,
                   pl.nationality_code, pl.age_group,
                   pl.club_id,
                   p.code  AS position_code, p.name AS position_name,
                   pg.id   AS position_group_id, pg.code AS group_code,
                   pg.name_en AS group_name
            FROM   players pl
            LEFT JOIN positions p        ON p.id  = pl.primary_position_id
            LEFT JOIN position_groups pg ON pg.id = p.position_group_id
            WHERE  pl.id = %s
            """,
            (player_id,)
        )
        return cur.fetchone()


def _criteria_grouped(criteria_rows: list[dict]) -> list[dict]:
    """
    Group flat criteria rows by category, preserving order.
    Returns [{ category: {...}, criteria: [...] }, ...].
    """
    out: list[dict] = []
    by_id: dict[int, dict] = {}
    for r in criteria_rows:
        cid = r["category_id"]
        if cid not in by_id:
            section = {
                "category": {
                    "id":   cid,
                    "code": r["category_code"],
                    "name_en": r["category_name_en"],
                    "name_ar": r["category_name_ar"],
                },
                "criteria": [],
            }
            by_id[cid] = section
            out.append(section)
        by_id[cid]["criteria"].append(r)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Form: GET (render) + POST (save draft / submit)
# ─────────────────────────────────────────────────────────────────────────────

@bp.route('/players/<int:player_id>/evaluate', methods=['GET', 'POST'])
@youth_section_access
def evaluate(player_id):
    player = _load_player(player_id)
    if not player or not player["is_active"]:
        abort(404)

    # Youth NT: youth_nt may only evaluate youth players (object-scoped).
    require_youth_access(player)

    pos_group_id = player["position_group_id"]
    if pos_group_id is None:
        flash("Set the player's primary position before evaluating.", "error")
        return redirect(url_for('players.edit_player', player_id=player_id))

    if request.method == 'POST':
        return _handle_form_post(player, pos_group_id)

    return _render_form(player, pos_group_id)


def _render_form(player, pos_group_id, draft=None, scores=None,
                 errors=None, form_values=None):
    criteria  = get_form_criteria(pos_group_id)
    sections  = _criteria_grouped(criteria)
    # Reuse the players blueprint's position picker so the match-position
    # dropdown offers the exact same grouped options as the player forms.
    from app.players import _load_position_picker
    from app.clubs.resolver import enrich_match_history_with_opponent
    position_groups = _load_position_picker()

    # Enrich all recent matches with opponent + own_match via club_aliases resolver.
    # Filter to own-club matches ONLY when the player has a resolvable club and
    # that filter yields ≥1 match — otherwise fall back to ALL matches so the
    # evaluator is never left with an empty dropdown.
    all_matches   = get_recent_matches(RECENT_MATCH_LIMIT)
    enriched      = enrich_match_history_with_opponent(all_matches, player.get("club_id"))
    own_club_only = False
    if player.get("club_id"):
        own_club_matches = [m for m in enriched if m["own_match"]]
        if own_club_matches:
            matches      = own_club_matches
            own_club_only = True
        else:
            matches = enriched
    else:
        matches = enriched

    # Optional ?match_id=... selects a draft to pre-load
    selected_match_id = request.args.get('match_id', type=int)
    if draft is None and selected_match_id is not None:
        # Phase 7: stamp creator's role so NT-staff drafts get
        # created_by_role='nt_staff' and stay hidden from scouts.
        draft = get_or_create_draft(player["id"], selected_match_id,
                                    current_user.id, pos_group_id,
                                    creator_role=current_user.role)
        scores = get_evaluation_scores(draft["id"])

    return render_template(
        'evaluations/form.html',
        player=player,
        sections=sections,
        criteria=criteria,
        matches=matches,
        position_groups=position_groups,
        recent_match_limit=RECENT_MATCH_LIMIT,
        selected_match_id=selected_match_id,
        own_club_only=own_club_only,
        draft=draft,
        scores=scores or {},
        errors=errors or {},
        form_values=form_values or {},
    )


def _handle_form_post(player, pos_group_id):
    form   = request.form
    action = form.get("action") or "save_draft"

    meta   = parse_meta_fields(form)
    scores = parse_score_inputs(form)

    if not meta.get("match_id"):
        flash("Please pick a match before saving.", "error")
        return _render_form(player, pos_group_id,
                            errors={"match_id": "Match is required."},
                            form_values=form)

    # Position played is only required on submit (not on save_draft).
    # Drafts are explicitly allowed to be incomplete.
    if action == "submit" and not meta.get("position_played_id"):
        flash("Please select the position the player played in this match.", "error")
        return _render_form(player, pos_group_id,
                            errors={"position_played_id": "Position played is required."},
                            form_values=form)

    # Phase 7: pass current_user.role so the draft is stamped
    # 'nt_staff' / 'admin' / 'scout' on first create.
    draft = get_or_create_draft(player["id"], meta["match_id"],
                                current_user.id, pos_group_id,
                                creator_role=current_user.role)
    save_evaluation_scores(draft["id"], scores)
    update_evaluation_meta(draft["id"], meta)

    if action == "submit":
        ok, msg = submit_draft(draft["id"], current_user.id)
        if not ok:
            flash(f"Cannot submit yet — {msg}", "error")
            return redirect(url_for('evaluations.evaluate',
                                    player_id=player["id"],
                                    match_id=meta["match_id"]))
        flash("Evaluation submitted.", "success")
        return redirect(url_for('evaluations.view', eval_id=draft["id"]))

    flash("Draft saved.", "success")
    return redirect(url_for('evaluations.evaluate',
                            player_id=player["id"],
                            match_id=meta["match_id"]))


# ─────────────────────────────────────────────────────────────────────────────
# View an evaluation
# ─────────────────────────────────────────────────────────────────────────────

@bp.route('/evaluations/<int:eval_id>')
@login_required
def view(eval_id):
    # @login_required (not @any_authenticated) so youth_nt can reach this
    # for THEIR youth players; require_youth_access then 403s youth_nt on
    # any non-youth player's evaluation. No existing role is weakened —
    # login_required is a superset of any_authenticated's role set.
    #
    # Phase 7: scout role can't read NT evaluations even by direct ID.
    # `get_evaluation` returns None for scout-viewing-NT, same shape
    # as not-found — so a scout cannot probe for the existence of an
    # NT eval via 200 vs 404.
    ev = get_evaluation(eval_id, requesting_user_role=current_user.role,
                        requesting_user_id=current_user.id)
    if not ev:
        abort(404)

    # Youth NT: object-scope youth_nt to youth players' evaluations only.
    require_youth_access(ev)
    scores   = get_evaluation_scores(eval_id)
    criteria = get_form_criteria(ev["position_group_id"])
    sections = _criteria_grouped(criteria)
    is_own_draft = (ev["status"] == "draft"
                    and ev["evaluator_id"] == current_user.id)
    return render_template(
        'evaluations/view.html',
        ev=ev,
        sections=sections,
        scores=scores,
        is_own_draft=is_own_draft,
    )


@bp.route('/evaluations/<int:eval_id>', methods=['POST'])
@scout_or_above
def update_draft(eval_id):
    # Phase 7: defense in depth. evaluator_id check below already
    # prevents a scout from updating an nt_staff draft (different
    # owners), but threading the role keeps the policy uniform.
    # Draft privacy: requesting_user_id filters out other users' drafts at
    # query level — returns None (404) instead of leaking the draft exists.
    ev = get_evaluation(eval_id, requesting_user_role=current_user.role,
                        requesting_user_id=current_user.id)
    if not ev:
        abort(404)
    if ev["evaluator_id"] != current_user.id:
        abort(403)
    if ev["status"] != "draft":
        flash("Submitted evaluations cannot be edited.", "error")
        return redirect(url_for('evaluations.view', eval_id=eval_id))

    form = request.form
    meta = parse_meta_fields(form)
    # Position played is required (same rule as the main form path).
    if not meta.get("position_played_id"):
        flash("Please select the position the player played in this match.", "error")
        return redirect(url_for('evaluations.evaluate',
                                player_id=ev["player_id"],
                                match_id=ev.get("match_id")))
    save_evaluation_scores(eval_id, parse_score_inputs(form))
    update_evaluation_meta(eval_id, meta)

    if (form.get("action") or "save_draft") == "submit":
        ok, msg = submit_draft(eval_id, current_user.id)
        if not ok:
            flash(f"Cannot submit yet — {msg}", "error")
            return redirect(url_for('evaluations.view', eval_id=eval_id))
        flash("Evaluation submitted.", "success")
    else:
        flash("Draft saved.", "success")
    return redirect(url_for('evaluations.view', eval_id=eval_id))


@bp.route('/evaluations/<int:eval_id>/submit', methods=['POST'])
@scout_or_above
def submit(eval_id):
    ok, msg = submit_draft(eval_id, current_user.id)
    if not ok:
        flash(f"Cannot submit — {msg}", "error")
    else:
        flash("Evaluation submitted.", "success")
    return redirect(url_for('evaluations.view', eval_id=eval_id))


# ─────────────────────────────────────────────────────────────────────────────
# Lock workflow (admin/TD only — Phase 5c-2)
# ─────────────────────────────────────────────────────────────────────────────

@bp.route('/evaluations/<int:eval_id>/lock', methods=['POST'])
@admin_or_td_required
def lock(eval_id):
    ok, msg = lock_evaluation(eval_id, current_user.id)
    if not ok:
        flash(msg, "error")
    else:
        log_audit(current_user.id, 'evaluation.locked', 'evaluation', eval_id,
                  {'locker_id': current_user.id, 'target_status': 'locked'})
        flash("Evaluation locked.", "success")
    return redirect(url_for('evaluations.view', eval_id=eval_id))


@bp.route('/evaluations/<int:eval_id>/unlock', methods=['POST'])
@admin_or_td_required
def unlock(eval_id):
    reason = (request.form.get('reason') or '').strip()
    ok, msg = unlock_evaluation(eval_id, current_user.id, reason)
    if not ok:
        flash(msg, "error")
    else:
        log_audit(current_user.id, 'evaluation.unlocked', 'evaluation', eval_id,
                  {'unlocker_id': current_user.id, 'reason': reason})
        flash("Evaluation unlocked.", "success")
    return redirect(url_for('evaluations.view', eval_id=eval_id))


# ─────────────────────────────────────────────────────────────────────────────
# Soft-delete + restore (Phase 5c-3)
# ─────────────────────────────────────────────────────────────────────────────

@bp.route('/evaluations/<int:eval_id>/delete', methods=['POST'])
@scout_or_above
def delete_evaluation(eval_id):
    """
    Soft-delete the evaluation. Permission rules enforced in helper:
      - Scout: own DRAFT only
      - Admin/TD: any non-locked evaluation
    Reason text required (min 10 chars). Audit-logged.
    """
    reason = (request.form.get('reason') or '').strip()
    is_admin_td = current_user.has_role('admin', 'technical_director')
    ok, msg = soft_delete_evaluation(eval_id, current_user.id, reason, is_admin_td)
    if not ok:
        flash(msg, "error")
        return redirect(request.referrer or url_for('players.list_players'))
    log_audit(current_user.id, 'evaluation.deleted', 'evaluation', eval_id,
              {'deleter_id': current_user.id, 'reason': reason})
    flash("Evaluation deleted.", "success")
    return redirect(request.referrer or url_for('players.list_players'))


@bp.route('/evaluations/<int:eval_id>/restore', methods=['POST'])
@admin_or_td_required
def restore(eval_id):
    """Restore a soft-deleted evaluation. Admin/TD only. Audit-logged."""
    ok, msg = restore_evaluation(eval_id, current_user.id)
    if not ok:
        flash(msg, "error")
    else:
        log_audit(current_user.id, 'evaluation.restored', 'evaluation', eval_id,
                  {'restorer_id': current_user.id})
        flash("Evaluation restored.", "success")
    return redirect(url_for('admin.deleted_evaluations'))


@bp.route('/evaluations/<int:eval_id>/admin-edit', methods=['POST'])
@admin_or_td_required
def admin_edit(eval_id):
    form = request.form
    meta = parse_meta_fields(form)
    # If any score inputs are present, treat as score overwrite too
    raw_scores = parse_score_inputs(form)
    scores = raw_scores if raw_scores else None

    ok, msg, fields_changed = admin_edit_evaluation(
        eval_id, current_user.id, meta, scores=scores
    )
    if not ok:
        flash(msg, "error")
    else:
        log_audit(current_user.id, 'evaluation.admin_edited', 'evaluation', eval_id,
                  {'admin_id': current_user.id, 'fields_changed': fields_changed})
        flash("Edit applied.", "success")
    return redirect(url_for('evaluations.view', eval_id=eval_id))


# ─────────────────────────────────────────────────────────────────────────────
# Inline match creation (modal in form)
# ─────────────────────────────────────────────────────────────────────────────

_MATCH_REQUIRED   = ("match_date", "home_team", "away_team", "age_group", "match_type")
_AGE_GROUP_VALUES = {"senior", "u23", "u20", "u17"}
_MATCH_TYPE_VALUES = {"league", "cup", "friendly", "tournament", "national_team"}


@bp.route('/matches/new-inline', methods=['POST'])
@scout_or_above
def new_match_inline():
    form = request.form
    errors: dict[str, str] = {}

    raw_date = (form.get("match_date") or "").strip()
    try:
        m_date = date.fromisoformat(raw_date) if raw_date else None
    except ValueError:
        m_date = None
        errors["match_date"] = "Invalid date."
    if not m_date:
        errors.setdefault("match_date", "Match date is required.")

    home = (form.get("home_team") or "").strip()
    away = (form.get("away_team") or "").strip()
    if not home:
        errors["home_team"] = "Home team is required."
    if not away:
        errors["away_team"] = "Away team is required."

    age_group = (form.get("age_group") or "").strip() or None
    if age_group and age_group not in _AGE_GROUP_VALUES:
        errors["age_group"] = "Invalid age group."
    if not age_group:
        errors.setdefault("age_group", "Age group is required.")

    match_type = (form.get("match_type") or "").strip() or None
    if match_type and match_type not in _MATCH_TYPE_VALUES:
        errors["match_type"] = "Invalid match type."
    if not match_type:
        errors.setdefault("match_type", "Match type is required.")

    def _opt_int(name):
        v = (form.get(name) or "").strip()
        if not v:
            return None
        try:
            return int(v)
        except ValueError:
            errors[name] = "Must be a whole number."
            return None

    home_score  = _opt_int("home_score")
    away_score  = _opt_int("away_score")
    competition = (form.get("competition") or "").strip() or None
    notes       = (form.get("notes") or "").strip() or None

    if errors:
        return jsonify({"ok": False, "errors": errors}), 400

    conn = get_db()
    with conn.cursor() as cur:
        # Reuse Wyscout's case-insensitive identity check
        cur.execute(
            """
            SELECT id FROM matches
            WHERE match_date = %s
              AND LOWER(BTRIM(home_team)) = LOWER(BTRIM(%s))
              AND LOWER(BTRIM(away_team)) = LOWER(BTRIM(%s))
            LIMIT 1
            """,
            (m_date, home, away)
        )
        existing = cur.fetchone()
        if existing:
            match_id = existing["id"]
            created  = False
        else:
            cur.execute(
                """
                INSERT INTO matches
                    (match_date, home_team, away_team, home_score, away_score,
                     competition, age_group, match_type, notes,
                     source, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'manual', %s)
                RETURNING id
                """,
                (m_date, home, away, home_score, away_score,
                 competition, age_group, match_type, notes, current_user.id)
            )
            match_id = cur.fetchone()["id"]
            created  = True
    conn.commit()

    label = f"{m_date.isoformat()} · {home} vs {away}"
    return jsonify({"ok": True, "id": match_id, "label": label, "created": created})
