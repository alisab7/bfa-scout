"""
Admin user-management routes.

All routes are restricted to the 'admin' role via @admin_required.

Routes
------
GET  /admin/users                    — list all users
GET  /admin/users/new                — new-user form
POST /admin/users/new                — create user
GET  /admin/users/<id>/edit          — edit-user form
POST /admin/users/<id>/edit          — update user (name, role, active flag)
POST /admin/users/<id>/reset-password — set a new password
POST /admin/users/<id>/deactivate    — deactivate (soft-delete)
"""

from flask import render_template, redirect, url_for, request, flash
from flask_login import current_user
from werkzeug.security import generate_password_hash

from app.db import get_db
from app.auth.decorators import admin_required
from app.auth.audit import log_audit
from app.auth.validators import validate_password_strength
from . import bp

VALID_ROLES = ('admin', 'technical_director', 'scout', 'viewer')


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_user_or_404(user_id):
    """Return a RealDictRow for the given user id or flash + redirect."""
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute('SELECT * FROM users WHERE id = %s', (user_id,))
        row = cur.fetchone()
    return row


def is_last_active_admin(user_id):
    """
    Return True if *user_id* is the only active admin.
    Used to block deactivation / role-change that would lock everyone out.
    """
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND is_active = TRUE"
        )
        total = cur.fetchone()['n']
    if total > 1:
        return False
    # Only one active admin — check if it's this user
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM users WHERE role = 'admin' AND is_active = TRUE LIMIT 1"
        )
        row = cur.fetchone()
    return row is not None and row['id'] == user_id


# ── List ──────────────────────────────────────────────────────────────────────

@bp.route('/users')
@admin_required
def users_list():
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, email, full_name, full_name_ar, role, is_active,
                   created_at, last_login_at
            FROM   users
            ORDER  BY role, full_name
            """
        )
        users = cur.fetchall()
    return render_template('admin/users/list.html', users=users)


# ── New ───────────────────────────────────────────────────────────────────────

@bp.route('/users/new', methods=['GET', 'POST'])
@admin_required
def users_new():
    if request.method == 'POST':
        email        = request.form.get('email', '').strip().lower()
        full_name    = request.form.get('full_name', '').strip()
        full_name_ar = request.form.get('full_name_ar', '').strip()
        role         = request.form.get('role', 'viewer')
        password     = request.form.get('password', '')
        confirm_pw   = request.form.get('confirm_password', '')

        # ── Validation ──────────────────────────────────────────────
        error = None
        if not email:
            error = 'Email is required.'
        elif not full_name:
            error = 'Full name is required.'
        elif role not in VALID_ROLES:
            error = 'Invalid role.'
        elif password != confirm_pw:
            error = 'Passwords do not match.'
        else:
            pw_valid, pw_err = validate_password_strength(password)
            if not pw_valid:
                error = pw_err
            else:
                conn = get_db()
                with conn.cursor() as cur:
                    cur.execute('SELECT id FROM users WHERE email = %s', (email,))
                    if cur.fetchone():
                        error = 'A user with that email already exists.'

        if error:
            flash(error, 'error')
            return render_template(
                'admin/users/new.html',
                roles=VALID_ROLES,
                form=request.form,
            )

        # ── Insert ──────────────────────────────────────────────────
        pw_hash = generate_password_hash(password, method='pbkdf2:sha256:600000')
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (email, password_hash, full_name, full_name_ar, role, is_active)
                VALUES (%s, %s, %s, %s, %s, TRUE)
                RETURNING id
                """,
                (email, pw_hash, full_name, full_name_ar or None, role),
            )
            new_id = cur.fetchone()['id']
        conn.commit()

        log_audit(
            current_user.id, 'user.create', 'user', new_id,
            details={'email': email, 'role': role},
            ip_address=request.remote_addr,
        )
        flash(f'User {email} created.', 'success')
        return redirect(url_for('admin.users_list'))

    return render_template('admin/users/new.html', roles=VALID_ROLES, form={})


# ── Edit ──────────────────────────────────────────────────────────────────────

@bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@admin_required
def users_edit(user_id):
    user = _get_user_or_404(user_id)
    if user is None:
        flash('User not found.', 'error')
        return redirect(url_for('admin.users_list'))

    if request.method == 'POST':
        full_name    = request.form.get('full_name', '').strip()
        full_name_ar = request.form.get('full_name_ar', '').strip()
        new_role     = request.form.get('role', user['role'])
        is_active    = request.form.get('is_active') == 'on'

        # ── Validation ──────────────────────────────────────────────
        error = None
        if not full_name:
            error = 'Full name is required.'
        elif new_role not in VALID_ROLES:
            error = 'Invalid role.'
        elif (new_role != 'admin' or not is_active) and is_last_active_admin(user_id):
            error = (
                'Cannot demote or deactivate the last active admin. '
                'Promote another user to admin first.'
            )

        if error:
            flash(error, 'error')
            return render_template(
                'admin/users/edit.html',
                user=user,
                roles=VALID_ROLES,
                form=request.form,
            )

        # ── Update ──────────────────────────────────────────────────
        changed_fields = []
        if full_name != user['full_name']:
            changed_fields.append('full_name')
        if (full_name_ar or None) != user['full_name_ar']:
            changed_fields.append('full_name_ar')
        if new_role != user['role']:
            changed_fields.append('role')
        if is_active != user['is_active']:
            changed_fields.append('is_active')

        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET full_name = %s, full_name_ar = %s, role = %s,
                    is_active = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (full_name, full_name_ar or None, new_role, is_active, user_id),
            )
        conn.commit()

        if changed_fields:
            log_audit(
                current_user.id, 'user.edit', 'user', user_id,
                details={'fields': changed_fields, 'new_role': new_role},
                ip_address=request.remote_addr,
            )

        flash('User updated.', 'success')
        return redirect(url_for('admin.users_list'))

    return render_template(
        'admin/users/edit.html',
        user=user,
        roles=VALID_ROLES,
        form=user,
    )


# ── Reset password ────────────────────────────────────────────────────────────

@bp.route('/users/<int:user_id>/reset-password', methods=['POST'])
@admin_required
def users_reset_password(user_id):
    user = _get_user_or_404(user_id)
    if user is None:
        flash('User not found.', 'error')
        return redirect(url_for('admin.users_list'))

    new_pw     = request.form.get('new_password', '')
    confirm_pw = request.form.get('confirm_password', '')

    pw_valid, pw_err = validate_password_strength(new_pw)
    if not pw_valid:
        flash(pw_err, 'error')
        return redirect(url_for('admin.users_edit', user_id=user_id))

    if new_pw != confirm_pw:
        flash('Passwords do not match.', 'error')
        return redirect(url_for('admin.users_edit', user_id=user_id))

    pw_hash = generate_password_hash(new_pw, method='pbkdf2:sha256:600000')
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            'UPDATE users SET password_hash = %s, updated_at = NOW() WHERE id = %s',
            (pw_hash, user_id),
        )
    conn.commit()

    log_audit(
        current_user.id, 'user.password.reset', 'user', user_id,
        ip_address=request.remote_addr,
    )
    flash(f'Password reset for {user["email"]}.', 'success')
    return redirect(url_for('admin.users_list'))


# ── Deactivate ────────────────────────────────────────────────────────────────

@bp.route('/users/<int:user_id>/deactivate', methods=['POST'])
@admin_required
def users_deactivate(user_id):
    user = _get_user_or_404(user_id)
    if user is None:
        flash('User not found.', 'error')
        return redirect(url_for('admin.users_list'))

    if is_last_active_admin(user_id):
        flash(
            'Cannot deactivate the last active admin. '
            'Promote another user to admin first.',
            'error',
        )
        return redirect(url_for('admin.users_list'))

    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            'UPDATE users SET is_active = FALSE, updated_at = NOW() WHERE id = %s',
            (user_id,),
        )
    conn.commit()

    log_audit(
        current_user.id, 'user.deactivate', 'user', user_id,
        ip_address=request.remote_addr,
    )
    flash(f'{user["email"]} has been deactivated.', 'success')
    return redirect(url_for('admin.users_list'))
