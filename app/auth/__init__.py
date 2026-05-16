from flask import (
    Blueprint, render_template, redirect, url_for,
    request, flash, session
)
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash

from app.db import get_db
from .models import User
from .audit import log_audit
from .validators import validate_password_strength

bp = Blueprint('auth', __name__, template_folder='../templates/auth')


# ── Login ─────────────────────────────────────────────────────────────────────

@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        ip       = request.remote_addr

        user = User.get_by_email(email)

        if user and user.is_active and check_password_hash(
            _get_password_hash(email), password
        ):
            login_user(user, remember=False)

            # Update last_login_at
            conn = get_db()
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE users SET last_login_at = NOW() WHERE id = %s',
                    (user.id,)
                )
            conn.commit()

            log_audit(user.id, 'auth.login.success', 'user', user.id,
                      ip_address=ip)

            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))

        # Generic failure — don't reveal which field was wrong
        log_audit(
            None, 'auth.login.failure', 'user', None,
            details={'email': email}, ip_address=ip
        )
        flash('Invalid email or password.', 'error')

    return render_template('auth/login.html')


def _get_password_hash(email):
    """Fetch password_hash for a given email directly from DB."""
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute('SELECT password_hash FROM users WHERE email = %s', (email,))
        row = cur.fetchone()
    return row['password_hash'] if row else ''


# ── Logout ────────────────────────────────────────────────────────────────────

@bp.route('/logout', methods=['POST'])
@login_required
def logout():
    user_id = current_user.id
    log_audit(user_id, 'auth.logout', 'user', user_id,
              ip_address=request.remote_addr)
    logout_user()
    flash('You have been signed out.', 'info')
    return redirect(url_for('auth.login'))


# ── Profile ───────────────────────────────────────────────────────────────────

@bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        full_name    = request.form.get('full_name', '').strip()
        full_name_ar = request.form.get('full_name_ar', '').strip()
        phone        = request.form.get('phone', '').strip()

        if not full_name:
            flash('Full name is required.', 'error')
            return redirect(url_for('auth.profile'))

        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET full_name = %s, full_name_ar = %s, phone = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (full_name, full_name_ar or None, phone or None, current_user.id)
            )
        conn.commit()

        log_audit(current_user.id, 'user.edit', 'user', current_user.id,
                  details={'fields': ['full_name', 'full_name_ar', 'phone']},
                  ip_address=request.remote_addr)
        flash('Profile updated.', 'success')
        return redirect(url_for('auth.profile'))

    # Reload fresh data for display
    user = User.get_by_id(current_user.id)
    return render_template('auth/profile.html', user=user)


# ── Change password ───────────────────────────────────────────────────────────

@bp.route('/password', methods=['POST'])
@login_required
def change_password():
    current_pw  = request.form.get('current_password', '')
    new_pw      = request.form.get('new_password', '')
    confirm_pw  = request.form.get('confirm_password', '')

    # Verify current password
    current_hash = _get_password_hash(current_user.email)
    if not check_password_hash(current_hash, current_pw):
        flash('Current password is incorrect.', 'error')
        return redirect(url_for('auth.profile'))

    is_valid, pw_err = validate_password_strength(new_pw)
    if not is_valid:
        flash(pw_err, 'error')
        return redirect(url_for('auth.profile'))

    if new_pw != confirm_pw:
        flash('New passwords do not match.', 'error')
        return redirect(url_for('auth.profile'))

    new_hash = generate_password_hash(new_pw, method='pbkdf2:sha256:600000')
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            'UPDATE users SET password_hash = %s, updated_at = NOW() WHERE id = %s',
            (new_hash, current_user.id)
        )
    conn.commit()

    log_audit(current_user.id, 'auth.password.change', 'user', current_user.id,
              ip_address=request.remote_addr)
    flash('Password changed successfully.', 'success')
    return redirect(url_for('auth.profile'))
