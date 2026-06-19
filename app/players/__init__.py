import os
from datetime import date

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, current_app, abort,
)
from flask_login import login_required, current_user

from app.auth.decorators import (
    scout_or_above, any_authenticated, youth_section_access,
    deny_youth_nt, require_youth_access, YOUTH_GROUPS,
)
from app.auth.audit import log_audit
from app.db import get_db

bp = Blueprint('players', __name__)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _load_position_picker():
    """
    Returns list of {group_code, group_name, positions:[{pos_id, pos_code, pos_name}]}
    Option values are positions.id (integer), not code strings.
    """
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT pg.code  AS group_code, pg.name_en AS group_name, pg.sort_order,
                   p.id     AS pos_id,     p.code     AS pos_code,   p.name AS pos_name
            FROM   position_groups pg
            JOIN   positions p ON p.position_group_id = pg.id
            ORDER  BY pg.sort_order, p.name
            """
        )
        rows = cur.fetchall()

    groups = {}
    for row in rows:
        gc = row['group_code']
        if gc not in groups:
            groups[gc] = {'group_code': gc, 'group_name': row['group_name'], 'positions': []}
        groups[gc]['positions'].append({
            'pos_id':   row['pos_id'],
            'pos_code': row['pos_code'],
            'pos_name': row['pos_name'],
        })
    return list(groups.values())


# Phase 5c-2.1: eligibility filter values accepted from the list dropdown.
# The SQL clauses keep INTERVAL '5 years' aligned with
# RESIDENCY_YEARS_REQUIRED in app/players/eligibility.py — if you change
# the constant there, mirror it here.
_ELIG_FILTER_CLAUSES = {
    'eligible_now': """(
        pl.nationality_status IN ('bahraini', 'foreign_ancestry')
        OR (pl.eligible_from_date IS NOT NULL AND pl.eligible_from_date <= CURRENT_DATE)
        OR (pl.nationality_status = 'foreign_residency'
            AND pl.bahrain_residency_start_date IS NOT NULL
            AND pl.eligible_from_date IS NULL
            AND pl.bahrain_residency_start_date + INTERVAL '5 years' <= CURRENT_DATE)
    )""",
    'pending': """(
        (pl.eligible_from_date IS NOT NULL AND pl.eligible_from_date > CURRENT_DATE)
        OR (pl.nationality_status = 'foreign_residency'
            AND pl.bahrain_residency_start_date IS NOT NULL
            AND pl.eligible_from_date IS NULL
            AND pl.bahrain_residency_start_date + INTERVAL '5 years' > CURRENT_DATE)
        OR (pl.nationality_status = 'foreign_residency'
            AND pl.bahrain_residency_start_date IS NULL
            AND pl.eligible_from_date IS NULL)
    )""",
    'not_eligible': "pl.nationality_status = 'not_eligible'",
    'unknown': """(
        pl.nationality_status IS NULL
        OR pl.nationality_status = 'unknown'
        OR (pl.nationality_status = 'foreign_other' AND pl.eligible_from_date IS NULL)
    )""",
}


def _search_players(q, pos_id, elig=None, nat=None, club=None):
    """
    Return active player rows matching q (name / national_id), optional
    pos_id, optional eligibility-filter key, optional nationality_code
    (3-letter ISO), and optional club filter.

    `club`: integer club_id, OR the literal string 'other' to match
    players with NULL club_id (free-text club).

    SELECT pulls 5c-1/5c-2 eligibility cols + 5c-3 nationality_code +
    club_id so callers can render the eligibility card / list cards
    without a second query.
    """
    elig_clause = _ELIG_FILTER_CLAUSES.get((elig or '').strip()) if elig else None

    extra_clauses: list[str] = []
    extra_params: list = []
    if nat:
        extra_clauses.append("pl.nationality_code = %s")
        extra_params.append(nat)
    if club:
        if club == 'other':
            extra_clauses.append("pl.club_id IS NULL")
        else:
            try:
                extra_clauses.append("pl.club_id = %s")
                extra_params.append(int(club))
            except ValueError:
                pass  # invalid club id → silently ignore

    conn = get_db()
    with conn.cursor() as cur:
        sql = f"""
            SELECT pl.id, pl.full_name, pl.full_name_ar, pl.national_id,
                   pl.primary_position_id, pl.dob, pl.current_club,
                   pl.nationality_status, pl.eligible_from_date,
                   pl.bahrain_residency_start_date,
                   pl.nationality_code, pl.club_id,
                   p.code AS position_code, p.name AS position_name,
                   pg.code AS group_code,   pg.name_en AS group_name,
                   c.name AS club_name,     c.division AS club_division
            FROM   players pl
            LEFT JOIN positions p       ON p.id  = pl.primary_position_id
            LEFT JOIN position_groups pg ON pg.id = p.position_group_id
            LEFT JOIN clubs c            ON c.id = pl.club_id
            WHERE  pl.is_active = TRUE
              -- Youth NT: youth players (U17/U20/U23) live ONLY in the
              -- /youth section and never appear on the general list.
              -- NULL-safe: senior + legacy-NULL stay visible.
              AND  (pl.age_group = 'senior' OR pl.age_group IS NULL)
              AND  (%s = '' OR pl.full_name    ILIKE %s
                            OR pl.full_name_ar ILIKE %s
                            OR pl.national_id  ILIKE %s)
              AND  (%s IS NULL OR pl.primary_position_id = %s)
              {f"AND {elig_clause}" if elig_clause else ""}
              {(" AND " + " AND ".join(extra_clauses)) if extra_clauses else ""}
            ORDER  BY pl.full_name
        """
        cur.execute(sql,
                    (q, f'%{q}%', f'%{q}%', f'%{q}%', pos_id, pos_id, *extra_params))
        return cur.fetchall()


def _age(dob):
    if not dob:
        return None
    today = date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def _validate_photo(f):
    if not f or not f.filename:
        return None
    allowed_mime = {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}
    if f.mimetype not in allowed_mime:
        return 'Photo must be an image file (JPEG, PNG, GIF, or WebP).'
    f.seek(0, 2)
    size = f.tell()
    f.seek(0)
    if size > 10 * 1024 * 1024:
        return 'Photo must be under 10 MB.'
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@bp.route('/')
@login_required
@deny_youth_nt
def list_players():
    q       = request.args.get('q',    '').strip()
    pos_str = request.args.get('pos',  '').strip()
    pos_id  = int(pos_str) if pos_str.isdigit() else None
    elig    = request.args.get('elig', '').strip() or None
    # Phase 5c-3: nationality + club filters
    nat     = request.args.get('nat',  '').strip() or None
    club    = request.args.get('club', '').strip() or None

    players = _search_players(q, pos_id, elig=elig, nat=nat, club=club)

    if request.headers.get('HX-Request'):
        return render_template('players/_grid.html', players=players, age=_age)

    position_groups = _load_position_picker()
    from app.players.clubs import get_clubs_grouped
    clubs_grouped = get_clubs_grouped()
    return render_template(
        'players/list.html',
        players=players,
        position_groups=position_groups,
        age=_age,
        q=q,
        pos_id=pos_id,
        elig=elig,
        nat=nat,
        club=club,
        clubs_premier=clubs_grouped.get('premier', []),
        clubs_first=clubs_grouped.get('first', []),
    )


@bp.route('/new', methods=['GET', 'POST'])
@scout_or_above
def new_player():
    position_groups = _load_position_picker()
    from app.players.clubs import get_clubs_grouped
    clubs_grouped = get_clubs_grouped()
    errors = {}

    if request.method == 'POST':
        full_name    = request.form.get('full_name', '').strip()
        full_name_ar = request.form.get('full_name_ar', '').strip()
        national_id  = request.form.get('national_id', '').strip()
        dob_str      = request.form.get('dob', '').strip()
        pos_id_str   = request.form.get('primary_position_id', '').strip()
        nationality  = request.form.get('nationality', 'BH').strip()
        height_cm    = request.form.get('height_cm', '').strip() or None
        weight_kg    = request.form.get('weight_kg', '').strip() or None
        notes        = request.form.get('notes', '').strip() or None
        photo        = request.files.get('photo')

        # Phase 5c-3: structured nationality_code (validate against ISO list)
        from app.players.nationalities import NATIONALITY_LABEL
        nationality_code = (request.form.get('nationality_code') or '').strip().upper() or None
        if nationality_code and nationality_code not in NATIONALITY_LABEL:
            errors['nationality_code'] = 'Invalid nationality.'
            nationality_code = None

        # Phase 5c-3: club picker with "other" escape (mirror of edit handler)
        club_choice         = (request.form.get('club_id') or '').strip()
        current_club_other  = (request.form.get('current_club_other') or '').strip() or None
        club_id    = None
        current_club = None
        if club_choice == 'other':
            club_id = None
            current_club = current_club_other
        elif club_choice.isdigit():
            try:
                club_id = int(club_choice)
                conn_lookup = get_db()
                with conn_lookup.cursor() as cur:
                    cur.execute("SELECT name FROM clubs WHERE id = %s", (club_id,))
                    r = cur.fetchone()
                if r:
                    current_club = r['name']
                else:
                    errors['club_id'] = 'Selected club no longer exists.'
                    club_id = None
            except ValueError:
                errors['club_id'] = 'Invalid club selection.'

        # Phase 5c-1 + 5c-2 admin-only eligibility / residency fields
        is_admin_td = current_user.has_role('admin', 'technical_director')
        _NS_VALUES = {'bahraini', 'foreign_ancestry', 'foreign_residency',
                      'not_eligible', 'unknown'}
        nationality_status      = (request.form.get('nationality_status') or '').strip() or None
        eligible_from_date_str  = (request.form.get('eligible_from_date') or '').strip()
        eligibility_notes_admin = (request.form.get('eligibility_notes_admin') or '').strip() or None
        if nationality_status and nationality_status not in _NS_VALUES:
            errors['nationality_status'] = 'Invalid eligibility status.'
        eligible_from_date = None
        if eligible_from_date_str:
            try:
                eligible_from_date = date.fromisoformat(eligible_from_date_str)
            except ValueError:
                errors['eligible_from_date'] = 'Invalid date.'
        residency_start_str     = (request.form.get('bahrain_residency_start_date') or '').strip()
        bahrain_residency_notes = (request.form.get('bahrain_residency_notes') or '').strip() or None
        bahrain_residency_start_date = None
        if residency_start_str:
            try:
                bahrain_residency_start_date = date.fromisoformat(residency_start_str)
            except ValueError:
                errors['bahrain_residency_start_date'] = 'Invalid date.'

        if not full_name:
            errors['full_name'] = 'Full name (English) is required.'

        if not national_id:
            errors['national_id'] = 'National ID is required.'
        elif 'national_id' not in errors:
            conn = get_db()
            with conn.cursor() as cur:
                cur.execute('SELECT id FROM players WHERE national_id = %s', (national_id,))
                if cur.fetchone():
                    errors['national_id'] = 'A player with this National ID already exists.'

        dob = None
        if dob_str:
            try:
                dob = date.fromisoformat(dob_str)
                if dob >= date.today():
                    errors['dob'] = 'Date of birth must be in the past.'
            except ValueError:
                errors['dob'] = 'Invalid date format.'

        primary_position_id = None
        if pos_id_str:
            try:
                primary_position_id = int(pos_id_str)
            except ValueError:
                errors['primary_position_id'] = 'Invalid position selection.'

        try:
            height_cm = int(height_cm) if height_cm else None
        except ValueError:
            errors['height_cm'] = 'Height must be a whole number.'

        try:
            weight_kg = int(weight_kg) if weight_kg else None
        except ValueError:
            errors['weight_kg'] = 'Weight must be a whole number.'

        photo_err = _validate_photo(photo)
        if photo_err:
            errors['photo'] = photo_err

        if not errors:
            conn = get_db()
            with conn.cursor() as cur:
                if is_admin_td:
                    cur.execute(
                        """
                        INSERT INTO players
                            (full_name, full_name_ar, national_id, dob,
                             primary_position_id, nationality, current_club,
                             height_cm, weight_kg, notes,
                             nationality_code, club_id,
                             nationality_status, eligible_from_date,
                             eligibility_notes_admin,
                             bahrain_residency_start_date, bahrain_residency_notes,
                             is_active, created_by)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                                %s, %s,
                                %s, %s, %s, %s, %s,
                                TRUE, %s)
                        RETURNING id
                        """,
                        (full_name, full_name_ar or None, national_id, dob,
                         primary_position_id, nationality, current_club,
                         height_cm, weight_kg, notes,
                         nationality_code, club_id,
                         nationality_status, eligible_from_date, eligibility_notes_admin,
                         bahrain_residency_start_date, bahrain_residency_notes,
                         current_user.id)
                    )
                else:
                    # Non-admin/TD: scout creates basic profile; eligibility fields
                    # silently dropped (admin sets them later via edit form).
                    cur.execute(
                        """
                        INSERT INTO players
                            (full_name, full_name_ar, national_id, dob,
                             primary_position_id, nationality, current_club,
                             height_cm, weight_kg, notes,
                             nationality_code, club_id,
                             is_active, created_by)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                                %s, %s,
                                TRUE, %s)
                        RETURNING id
                        """,
                        (full_name, full_name_ar or None, national_id, dob,
                         primary_position_id, nationality, current_club,
                         height_cm, weight_kg, notes,
                         nationality_code, club_id,
                         current_user.id)
                    )
                player_id = cur.fetchone()['id']
            conn.commit()

            if photo and photo.filename:
                from .photos import save_player_photo
                try:
                    save_player_photo(player_id, photo)
                except Exception as exc:
                    current_app.logger.error(f'Photo save failed for player {player_id}: {exc}')
                    flash('Player created but photo could not be processed.', 'error')

            log_audit(current_user.id, 'player.create', 'player', player_id,
                      {'full_name': full_name, 'national_id': national_id})
            flash(f'Player "{full_name}" created successfully.', 'success')
            return redirect(url_for('players.list_players'))

    return render_template('players/new.html',
                           position_groups=position_groups,
                           clubs_premier=clubs_grouped.get('premier', []),
                           clubs_first=clubs_grouped.get('first', []),
                           errors=errors,
                           form=request.form)


@bp.route('/<int:player_id>')
@login_required
def player_profile(player_id):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT pl.id, pl.full_name, pl.full_name_ar, pl.national_id,
                   pl.primary_position_id, pl.dob, pl.current_club,
                   pl.nationality, pl.height_cm, pl.weight_kg, pl.notes,
                   pl.is_active, pl.created_at, pl.updated_at,
                   pl.age_group,
                   -- Phase 5c-1 + 5c-2 eligibility fields
                   pl.nationality_status, pl.eligible_from_date,
                   pl.eligibility_notes_admin,
                   pl.bahrain_residency_start_date, pl.bahrain_residency_notes,
                   -- Phase 5c-3 structured nationality + club
                   pl.nationality_code, pl.club_id,
                   p.code AS position_code, p.name AS position_name,
                   pg.code AS group_code,   pg.name_en AS group_name,
                   c.name AS club_name,     c.division AS club_division
            FROM   players pl
            LEFT JOIN positions p        ON p.id  = pl.primary_position_id
            LEFT JOIN position_groups pg ON pg.id = p.position_group_id
            LEFT JOIN clubs c            ON c.id  = pl.club_id
            WHERE  pl.id = %s
            """,
            (player_id,)
        )
        player = cur.fetchone()

    if not player:
        abort(404)

    # Youth NT: a youth_nt user may only view youth players' profiles.
    require_youth_access(player)

    # Phase 5c-3: bio counts (filters soft-deleted evaluations)
    # Phase 7: NT-staff evals excluded from the count for scout viewers.
    from app.evaluations.helpers import get_player_bio_counts
    bio_counts = get_player_bio_counts(player_id,
                                       requesting_user_role=current_user.role)

    return render_template('players/profile.html', player=player, age=_age,
                           bio_counts=bio_counts)


@bp.route('/<int:player_id>/edit', methods=['GET', 'POST'])
@youth_section_access
def edit_player(player_id):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT pl.id, pl.full_name, pl.full_name_ar, pl.national_id,
                   pl.primary_position_id, pl.dob, pl.current_club,
                   pl.nationality, pl.height_cm, pl.weight_kg, pl.notes, pl.is_active,
                   pl.age_group,
                   pl.nationality_status, pl.eligible_from_date, pl.eligibility_notes_admin,
                   pl.bahrain_residency_start_date, pl.bahrain_residency_notes,
                   pl.nationality_code, pl.club_id
            FROM   players pl
            WHERE  pl.id = %s AND pl.is_active = TRUE
            """,
            (player_id,)
        )
        player = cur.fetchone()

    if not player:
        abort(404)

    # Youth NT: youth_nt may only edit youth players (object-scoped).
    require_youth_access(player)

    # Age-group management (promotion) is senior-staff only: admin / TD /
    # nt_staff. scout + youth_nt can edit the player but NOT change the
    # age_group — that field is ignored for them.
    can_manage_age_group = current_user.has_role(
        'admin', 'technical_director', 'nt_staff')

    position_groups = _load_position_picker()
    from app.players.clubs import get_clubs_grouped
    clubs_grouped = get_clubs_grouped()
    errors = {}

    if request.method == 'POST':
        full_name    = request.form.get('full_name', '').strip()
        full_name_ar = request.form.get('full_name_ar', '').strip()
        national_id  = request.form.get('national_id', '').strip()
        dob_str      = request.form.get('dob', '').strip()
        pos_id_str   = request.form.get('primary_position_id', '').strip()
        nationality  = request.form.get('nationality', 'BH').strip()
        height_cm    = request.form.get('height_cm', '').strip() or None
        weight_kg    = request.form.get('weight_kg', '').strip() or None
        notes        = request.form.get('notes', '').strip() or None
        photo        = request.files.get('photo')

        # Phase 5c-3: structured nationality_code (validate against ISO list)
        from app.players.nationalities import NATIONALITY_LABEL
        nationality_code = (request.form.get('nationality_code') or '').strip().upper() or None
        if nationality_code and nationality_code not in NATIONALITY_LABEL:
            errors['nationality_code'] = 'Invalid nationality.'
            nationality_code = None

        # Phase 5c-3: structured club_id with "other" escape hatch.
        #   numeric → real club id; string 'other' → NULL (use current_club_other text);
        #   ''     → NULL + clear current_club entirely.
        club_choice         = (request.form.get('club_id') or '').strip()
        current_club_other  = (request.form.get('current_club_other') or '').strip() or None
        club_id    = None
        current_club = None
        if club_choice == 'other':
            club_id = None
            current_club = current_club_other  # free-text wins
        elif club_choice.isdigit():
            try:
                club_id = int(club_choice)
                with conn.cursor() as cur:
                    cur.execute("SELECT name FROM clubs WHERE id = %s", (club_id,))
                    r = cur.fetchone()
                if r:
                    current_club = r['name']  # denormalised cache from clubs.name
                else:
                    errors['club_id'] = 'Selected club no longer exists.'
                    club_id = None
            except ValueError:
                errors['club_id'] = 'Invalid club selection.'
        else:
            club_id = None
            current_club = None  # explicit blank

        # Youth NT: age_group (promotion) is senior-staff only. For users
        # who may manage it, validate the submitted value; otherwise keep
        # the player's existing group untouched (input ignored).
        new_age_group = player['age_group']
        if can_manage_age_group:
            submitted_ag = (request.form.get('age_group') or '').strip()
            if submitted_ag:
                if submitted_ag in YOUTH_GROUPS or submitted_ag == 'senior':
                    new_age_group = submitted_ag
                else:
                    errors['age_group'] = 'Invalid age group.'

        # Phase 5c-1: NT-eligibility fields are admin/TD only — others' input is ignored.
        is_admin_td = current_user.has_role('admin', 'technical_director')
        _NS_VALUES = {'bahraini', 'foreign_ancestry', 'foreign_residency',
                      'not_eligible', 'unknown'}
        nationality_status      = (request.form.get('nationality_status') or '').strip() or None
        eligible_from_date_str  = (request.form.get('eligible_from_date') or '').strip()
        eligibility_notes_admin = (request.form.get('eligibility_notes_admin') or '').strip() or None
        if nationality_status and nationality_status not in _NS_VALUES:
            errors['nationality_status'] = 'Invalid eligibility status.'
        eligible_from_date = None
        if eligible_from_date_str:
            try:
                eligible_from_date = date.fromisoformat(eligible_from_date_str)
            except ValueError:
                errors['eligible_from_date'] = 'Invalid date.'

        # Phase 5c-2: Bahrain residency tracking (admin/TD only)
        residency_start_str     = (request.form.get('bahrain_residency_start_date') or '').strip()
        bahrain_residency_notes = (request.form.get('bahrain_residency_notes') or '').strip() or None
        bahrain_residency_start_date = None
        if residency_start_str:
            try:
                bahrain_residency_start_date = date.fromisoformat(residency_start_str)
            except ValueError:
                errors['bahrain_residency_start_date'] = 'Invalid date.'

        if not full_name:
            errors['full_name'] = 'Full name (English) is required.'

        if not national_id:
            errors['national_id'] = 'National ID is required.'
        elif 'national_id' not in errors:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT id FROM players WHERE national_id = %s AND id != %s',
                    (national_id, player_id)
                )
                if cur.fetchone():
                    errors['national_id'] = 'A player with this National ID already exists.'

        dob = None
        if dob_str:
            try:
                dob = date.fromisoformat(dob_str)
                if dob >= date.today():
                    errors['dob'] = 'Date of birth must be in the past.'
            except ValueError:
                errors['dob'] = 'Invalid date format.'

        primary_position_id = None
        if pos_id_str:
            try:
                primary_position_id = int(pos_id_str)
            except ValueError:
                errors['primary_position_id'] = 'Invalid position selection.'

        try:
            height_cm = int(height_cm) if height_cm else None
        except ValueError:
            errors['height_cm'] = 'Height must be a whole number.'

        try:
            weight_kg = int(weight_kg) if weight_kg else None
        except ValueError:
            errors['weight_kg'] = 'Weight must be a whole number.'

        photo_err = _validate_photo(photo)
        if photo_err:
            errors['photo'] = photo_err

        # Phase 5c-2: position-change orphan-scores confirmation flow
        # If admin changes primary_position_id and there are existing scores
        # tied to criteria not in the new position group, ask for confirmation.
        orphan_count   = 0
        orphan_confirm = False
        new_pos_group_id = None
        if (not errors
                and primary_position_id
                and primary_position_id != player['primary_position_id']):
            from app.players.eligibility import (
                count_orphan_scores, delete_orphan_scores
            )
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT position_group_id FROM positions WHERE id = %s",
                    (primary_position_id,)
                )
                r = cur.fetchone()
                new_pos_group_id = r['position_group_id'] if r else None
            if new_pos_group_id:
                orphan_count = count_orphan_scores(conn, player_id, new_pos_group_id)
                decision = (request.form.get('orphan_decision') or '').strip()
                if orphan_count > 0 and decision not in ('delete', 'keep'):
                    # Re-render the form WITH a confirm modal — preserve the user's
                    # POSTed values so nothing is lost (photo will need re-upload).
                    return render_template(
                        'players/edit.html',
                        player=player,
                        position_groups=position_groups,
                        clubs_premier=clubs_grouped.get('premier', []),
                        clubs_first=clubs_grouped.get('first', []),
                        errors=errors,
                        form=request.form,
                        orphan_confirm=True,
                        orphan_count=orphan_count,
                        can_manage_age_group=can_manage_age_group,
                    )
                if decision == 'delete' and orphan_count > 0:
                    delete_orphan_scores(conn, player_id, new_pos_group_id)
                    log_audit(current_user.id, 'player.position_changed', 'player', player_id,
                              {'old_position_id': player['primary_position_id'],
                               'new_position_id': primary_position_id,
                               'orphans_deleted': orphan_count})
                else:
                    log_audit(current_user.id, 'player.position_changed', 'player', player_id,
                              {'old_position_id': player['primary_position_id'],
                               'new_position_id': primary_position_id,
                               'orphans_kept': orphan_count})

        if not errors:
            with conn.cursor() as cur:
                if is_admin_td:
                    cur.execute(
                        """
                        UPDATE players
                        SET    full_name = %s, full_name_ar = %s, national_id = %s,
                               dob = %s, primary_position_id = %s, nationality = %s,
                               current_club = %s,
                               height_cm = %s, weight_kg = %s, notes = %s,
                               nationality_status = %s,
                               eligible_from_date = %s,
                               eligibility_notes_admin = %s,
                               bahrain_residency_start_date = %s,
                               bahrain_residency_notes = %s,
                               nationality_code = %s, club_id = %s,
                               age_group = %s,
                               updated_at = NOW()
                        WHERE  id = %s
                        """,
                        (full_name, full_name_ar or None, national_id, dob,
                         primary_position_id, nationality, current_club,
                         height_cm, weight_kg, notes,
                         nationality_status, eligible_from_date, eligibility_notes_admin,
                         bahrain_residency_start_date, bahrain_residency_notes,
                         nationality_code, club_id,
                         new_age_group,
                         player_id)
                    )
                else:
                    cur.execute(
                        """
                        UPDATE players
                        SET    full_name = %s, full_name_ar = %s, national_id = %s,
                               dob = %s, primary_position_id = %s, nationality = %s,
                               current_club = %s,
                               height_cm = %s, weight_kg = %s, notes = %s,
                               nationality_code = %s, club_id = %s,
                               age_group = %s,
                               updated_at = NOW()
                        WHERE  id = %s
                        """,
                        (full_name, full_name_ar or None, national_id, dob,
                         primary_position_id, nationality, current_club,
                         height_cm, weight_kg, notes,
                         nationality_code, club_id, new_age_group, player_id)
                    )
            conn.commit()

            if photo and photo.filename:
                from .photos import save_player_photo
                try:
                    save_player_photo(player_id, photo)
                except Exception as exc:
                    current_app.logger.error(f'Photo replace failed for player {player_id}: {exc}')
                    flash('Player updated but photo could not be processed.', 'error')

            log_audit(current_user.id, 'player.edit', 'player', player_id,
                      {'full_name': full_name})
            flash(f'Player "{full_name}" updated successfully.', 'success')
            return redirect(url_for('players.player_profile', player_id=player_id))

    return render_template('players/edit.html',
                           player=player,
                           position_groups=position_groups,
                           clubs_premier=clubs_grouped.get('premier', []),
                           clubs_first=clubs_grouped.get('first', []),
                           errors=errors,
                           form=request.form,
                           can_manage_age_group=can_manage_age_group)


# ─────────────────────────────────────────────────────────────────────────────
# Comparison
# ─────────────────────────────────────────────────────────────────────────────

@bp.route('/compare')
@any_authenticated
def compare_form():
    """Player picker form for the comparison view."""
    return render_template('players/compare.html')


@bp.route('/compare/search')
@any_authenticated
def compare_search():
    """
    Lightweight HTMX endpoint for the picker. Returns clickable rows that the
    Alpine handler in compare.html turns into a chosen slot.
    """
    q = request.args.get('q', '').strip()
    if not q:
        return ''  # empty search → empty results
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT pl.id, pl.full_name, pl.full_name_ar, pl.current_club,
                   pl.nationality_code,
                   p.code AS position_code, p.name AS position_name,
                   pg.code AS group_code
            FROM   players pl
            LEFT JOIN positions p        ON p.id  = pl.primary_position_id
            LEFT JOIN position_groups pg ON pg.id = p.position_group_id
            WHERE  pl.is_active = TRUE
              -- Youth NT: youth players excluded from compare (a general
              -- senior surface; youth_nt is blocked from it entirely).
              AND  (pl.age_group = 'senior' OR pl.age_group IS NULL)
              AND  (pl.full_name    ILIKE %s
                 OR pl.full_name_ar ILIKE %s
                 OR pl.current_club ILIKE %s)
            ORDER  BY pl.full_name
            LIMIT  10
            """,
            (f'%{q}%', f'%{q}%', f'%{q}%')
        )
        results = cur.fetchall()
    slot = request.args.get('slot', '0')
    return render_template('players/_compare_search.html',
                           results=results, slot=slot)


def _parse_compare_ids():
    """Shared id-parsing for /compare/view + /compare/scout-section."""
    raw_ids = request.args.getlist('ids')
    flat = []
    for chunk in raw_ids:
        for piece in chunk.split(','):
            piece = piece.strip()
            if piece:
                flat.append(piece)
    return [int(x) for x in flat]  # may raise ValueError


def _enrich_for_scout_section(player_ids: list[int], scout_mode: str,
                              requesting_user_role: str | None = None) -> dict:
    """
    Phase 5d-patch: shared enrichment for the comparison view and the
    HTMX partial. Returns a dict with everything the
    `_compare_scout_section.html` template needs:
        {data, scout_mode, grouped_criteria, any_player_has_scout_data}

    Drilldown grouping is now done in Python (was Jinja {% set _ = … %}
    which silently failed past the first category iteration).
    """
    from app.wyscout.aggregations import compare_players
    from app.evaluations.helpers import (
        get_player_evaluation_aggregate, get_evaluation_count_active,
        get_form_criteria, group_criteria_by_category,
        build_scout_radar_data,  # Phase 5d-1
    )

    data = compare_players(player_ids)  # raises ValueError on validation failure

    if scout_mode not in ('latest', 'averaged'):
        scout_mode = 'latest'

    for p in data['players']:
        # Phase 7: thread the requesting user's role so NT-staff
        # evals are excluded from scout viewers' aggregates.
        p['eval_count'] = get_evaluation_count_active(
            p['id'], requesting_user_role=requesting_user_role)
        p['scout_data'] = (
            get_player_evaluation_aggregate(
                p['id'], mode=scout_mode,
                requesting_user_role=requesting_user_role)
            if p['eval_count'] > 0 else None
        )
        # Phase 5d-patch follow-up: pre-index scores by criterion_id so the
        # drilldown template doesn't need a `{% set score_row = … %}` inside
        # a `{% for s in scores %}` loop — Jinja silently scopes that
        # binding to the loop iteration, leaving every cell as None when
        # the outer `{% if score_row %}` runs.
        if p['scout_data'] and p['scout_data'].get('scores'):
            p['scores_by_criterion'] = {
                s['criterion_id']: s for s in p['scout_data']['scores']
            }
        else:
            p['scores_by_criterion'] = {}

    # Criteria union across selected players' position groups
    seen: set[int] = set()
    all_criteria: list[dict] = []
    for p in data['players']:
        pg_id = p.get('position_group_id')
        if not pg_id:
            continue
        for c in get_form_criteria(pg_id):
            if c['criterion_id'] not in seen:
                all_criteria.append(c)
                seen.add(c['criterion_id'])
    all_criteria.sort(key=lambda c: (c.get('category_sort', 99), c.get('sort_order', 99)))
    grouped_criteria = group_criteria_by_category(all_criteria)

    # Phase 5d-1: Chart.js-ready radar configs (1 category-level + 4 per-category)
    scout_radar_data = build_scout_radar_data(data, grouped_criteria)

    return {
        'data':                       data,
        'scout_mode':                 scout_mode,
        'all_criteria':               all_criteria,
        'grouped_criteria':           grouped_criteria,
        'any_player_has_scout_data':  any(p.get('scout_data') for p in data['players']),
        'scout_radar_data':           scout_radar_data,
    }


@bp.route('/compare/view')
@any_authenticated
def compare_view():
    """
    Read ?ids=1,2,3 from the query string; validate via compare_players()
    and render the side-by-side template, or flash and redirect on error.

    Phase 5d adds a scout-data layer per player + criteria union for the
    detailed drill-down. ?scout_mode=latest|averaged toggles aggregation;
    invalid values fall back to 'latest'.
    """
    try:
        player_ids = _parse_compare_ids()
    except ValueError:
        flash('Invalid player selection.', 'error')
        return redirect(url_for('players.compare_form'))

    scout_mode = request.args.get('scout_mode', 'latest').strip()

    try:
        ctx = _enrich_for_scout_section(
            player_ids, scout_mode,
            requesting_user_role=current_user.role)
    except ValueError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('players.compare_form'))

    return render_template('players/compare_view.html', **ctx)


@bp.route('/compare/scout-section')
@any_authenticated
def compare_scout_section():
    """
    Phase 5d-patch: HTMX partial for the Latest/Averaged mode toggle.
    Returns the scout-section block only — wrapper `<section
    id="scout-section">` lives inside the partial template so swap
    targets the same outer element.
    """
    try:
        player_ids = _parse_compare_ids()
    except ValueError:
        return '', 400
    if not player_ids:
        return '', 400

    scout_mode = request.args.get('scout_mode', 'latest').strip()

    try:
        ctx = _enrich_for_scout_section(
            player_ids, scout_mode,
            requesting_user_role=current_user.role)
    except ValueError:
        return '', 400

    return render_template('players/_compare_scout_section.html', **ctx)


@bp.route('/<int:player_id>/deactivate', methods=['POST'])
@youth_section_access
def deactivate(player_id):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            'SELECT id, full_name, age_group FROM players WHERE id = %s AND is_active = TRUE',
            (player_id,)
        )
        player = cur.fetchone()

    if not player:
        abort(404)

    # Youth NT: youth_nt may only deactivate youth players.
    require_youth_access(player)

    with conn.cursor() as cur:
        cur.execute(
            'UPDATE players SET is_active = FALSE, updated_at = NOW() WHERE id = %s',
            (player_id,)
        )
    conn.commit()

    log_audit(current_user.id, 'player.deactivate', 'player', player_id,
              {'full_name': player['full_name']})
    flash(f'Player "{player["full_name"]}" has been deactivated.', 'success')
    return redirect(url_for('players.list_players'))
