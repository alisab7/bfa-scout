"""
Youth NT section (U17 / U20 / U23).

`/youth` is the dedicated workspace for youth scouting. It is the ONLY
player surface the restricted youth_nt role can reach; senior staff
(admin / TD / scout / nt_staff) can also view it. Viewers are excluded.

Access model:
  /youth, /youth/<group>        → youth_section_access (all working roles
                                  except viewer; includes youth_nt)
  /youth/<group>/new (create)   → youth_section_access; age_group is FIXED
                                  to the sub-view's group (youth_nt cannot
                                  pick/promote — promotion is senior-only,
                                  enforced on the player edit form).

Edit / delete / evaluate of a youth player reuse the existing players /
evaluations routes, which now admit youth_nt + apply require_youth_access
so youth_nt is object-scoped to youth players only.
"""
from datetime import date

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, current_app, abort
)
from flask_login import login_required, current_user

from app.auth.decorators import (
    youth_section_access, admin_or_nt_staff_required, YOUTH_GROUPS,
)
from app.auth.audit import log_audit
from app.db import get_db
from app.youth.helpers import (
    get_youth_counts, get_youth_squad, get_shortlist,
    SLUG_TO_GROUP, GROUP_TO_SLUG,
)

bp = Blueprint('youth', __name__, url_prefix='/youth')


def _group_from_slug_or_404(slug: str) -> str:
    group = SLUG_TO_GROUP.get((slug or '').lower())
    if group is None:
        abort(404)
    return group


@bp.route('/')
@login_required
@youth_section_access
def index():
    """Youth landing — three cards (U17/U20/U23) with live counts."""
    counts = get_youth_counts()
    cards = [
        {'group': g, 'slug': GROUP_TO_SLUG[g], 'count': counts.get(g, 0)}
        for g in YOUTH_GROUPS
    ]
    return render_template('youth/index.html', cards=cards, counts=counts)


@bp.route('/shortlist')
@login_required
@admin_or_nt_staff_required
def shortlist():
    """Shortlist tab — all tracked youth prospects (admin/TD/nt_staff only).

    A static rule, so Werkzeug ranks it above `/<slug>` — no collision with
    the squad sub-views. Scout and youth_nt are excluded (admin/TD/nt_staff
    are the coaching/NT side, per the shortlist access boundary)."""
    players = get_shortlist()
    return render_template('youth/shortlist.html', players=players)


@bp.route('/<slug>')
@login_required
@youth_section_access
def squad(slug):
    """Squad table for one youth age-group."""
    group = _group_from_slug_or_404(slug)
    players = get_youth_squad(group)
    return render_template('youth/squad.html',
                           group=group, slug=GROUP_TO_SLUG[group],
                           players=players)


@bp.route('/<slug>/new', methods=['GET', 'POST'])
@login_required
@youth_section_access
def new_youth(slug):
    """
    Create a youth player. age_group is FIXED to the sub-view's group —
    not a user-controlled field — so youth_nt cannot place a player in a
    senior group or promote on create (promotion is senior-staff only).
    """
    group = _group_from_slug_or_404(slug)

    # Reuse the players blueprint's pickers + validators — single source.
    from app.players import _load_position_picker, _validate_photo
    from app.players.clubs import get_clubs_grouped
    from app.players.nationalities import NATIONALITY_LABEL

    position_groups = _load_position_picker()
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

        nationality_code = (request.form.get('nationality_code') or '').strip().upper() or None
        if nationality_code and nationality_code not in NATIONALITY_LABEL:
            errors['nationality_code'] = 'Invalid nationality.'
            nationality_code = None

        # Club picker with "other" escape (mirror of players.new_player).
        club_choice        = (request.form.get('club_id') or '').strip()
        current_club_other = (request.form.get('current_club_other') or '').strip() or None
        club_id = None
        current_club = None
        if club_choice == 'other':
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

        if not full_name:
            errors['full_name'] = 'Full name (English) is required.'

        if not national_id:
            errors['national_id'] = 'National ID is required.'
        else:
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
                # age_group is FIXED to `group` — never read from the form.
                cur.execute(
                    """
                    INSERT INTO players
                        (full_name, full_name_ar, national_id, dob,
                         primary_position_id, nationality, current_club,
                         height_cm, weight_kg, notes,
                         nationality_code, club_id,
                         age_group, is_active, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s,
                            %s, TRUE, %s)
                    RETURNING id
                    """,
                    (full_name, full_name_ar or None, national_id, dob,
                     primary_position_id, nationality, current_club,
                     height_cm, weight_kg, notes,
                     nationality_code, club_id,
                     group, current_user.id)
                )
                player_id = cur.fetchone()['id']
            conn.commit()

            if photo and photo.filename:
                from app.players.photos import save_player_photo
                try:
                    save_player_photo(player_id, photo)
                except Exception as exc:
                    current_app.logger.error(f'Photo save failed for youth player {player_id}: {exc}')
                    flash('Player created but photo could not be processed.', 'error')

            log_audit(current_user.id, 'player.create', 'player', player_id,
                      {'full_name': full_name, 'national_id': national_id,
                       'age_group': group})
            flash(f'Youth player "{full_name}" added to {group}.', 'success')
            return redirect(url_for('youth.squad', slug=GROUP_TO_SLUG[group]))

    return render_template('youth/new.html',
                           group=group, slug=GROUP_TO_SLUG[group],
                           position_groups=position_groups,
                           clubs_premier=clubs_grouped.get('premier', []),
                           clubs_first=clubs_grouped.get('first', []),
                           errors=errors,
                           form=request.form)
