import os
from datetime import timedelta

from flask import Flask, redirect, url_for, session
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect

from .config import Config

login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please sign in to continue.'
login_manager.login_message_category = 'info'

csrf = CSRFProtect()


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(config_class())

    # ── Session security (Phase 8.1) ──────────────────────────────
    # Sliding 8-hour idle timeout: every request resets the countdown.
    # SESSION_COOKIE_SECURE requires HTTPS; disabled in dev so local
    # Flask (HTTP) doesn't silently drop sessions.
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)
    app.config['SESSION_COOKIE_SECURE']   = (
        os.environ.get('FLASK_ENV', 'development') == 'production'
    )
    app.config['SESSION_COOKIE_HTTPONLY'] = True   # No JS access
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # CSRF mitigation

    # ── Extensions ────────────────────────────────────────────────
    login_manager.init_app(app)
    csrf.init_app(app)

    # ── Database ──────────────────────────────────────────────────
    from . import db
    db.init_app(app)

    # User loader for Flask-Login
    from .auth.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.get_by_id(int(user_id))

    # ── Blueprints ────────────────────────────────────────────────
    from .auth import bp as auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')

    from .admin import bp as admin_bp
    app.register_blueprint(admin_bp, url_prefix='/admin')

    from .players import bp as players_bp
    app.register_blueprint(players_bp, url_prefix='/players')

    from .evaluations import bp as evaluations_bp
    # Phase 5c-1: blueprint owns multiple URL roots (/players/<id>/evaluate,
    # /evaluations/<id>, /matches/new-inline), so registration uses absolute
    # paths inside the blueprint instead of a single prefix.
    app.register_blueprint(evaluations_bp)

    from .criteria import bp as criteria_bp
    app.register_blueprint(criteria_bp, url_prefix='/criteria')

    from .wyscout import bp as wyscout_bp
    app.register_blueprint(wyscout_bp, url_prefix='/wyscout')

    from .reports import bp as reports_bp
    app.register_blueprint(reports_bp, url_prefix='/reports')

    from .ai import bp as ai_bp
    app.register_blueprint(ai_bp, url_prefix='/ai')

    from .api import bp as api_bp
    app.register_blueprint(api_bp, url_prefix='/api')

    # Phase 6: Player Passport PDF. Route is absolute
    # (/players/<id>/passport.pdf) so it co-locates with the player
    # profile URL space without conflicting with the players blueprint.
    from .passport import bp as passport_bp
    app.register_blueprint(passport_bp)

    # Phase 7: National Team workspace. /nt/* — admin + nt_staff only.
    from .nt import bp as nt_bp
    app.register_blueprint(nt_bp)

    # Youth NT section (U17/U20/U23) + restricted youth_nt role.
    from .youth import bp as youth_bp
    app.register_blueprint(youth_bp)

    # Phase 8: healthcheck for Docker / Cloudflare / deploy gate.
    from .healthz import healthz_bp
    app.register_blueprint(healthz_bp)

    # ── Jinja globals ─────────────────────────────────────────────
    # v1.0.2: role display-name map (all 5 roles). Registered globally so
    # every template can use ROLE_LABELS.get(role, role) without needing
    # the admin blueprint's VALID_ROLES import.
    from .admin.users import ROLE_LABELS
    app.jinja_env.globals['ROLE_LABELS'] = ROLE_LABELS

    from .players.helpers import get_player_photo, get_player_pos, age
    app.jinja_env.globals['get_player_photo'] = get_player_photo
    app.jinja_env.globals['get_player_pos']   = get_player_pos
    app.jinja_env.globals['age']              = age

    from .wyscout.aggregations import (
        get_player_summary, get_player_match_history, get_player_radar_scores,
        get_player_seasons, get_player_radar_seasons,
    )
    from .wyscout.helpers import season_label_for_date
    app.jinja_env.globals['get_wyscout_summary']       = get_player_summary
    app.jinja_env.globals['get_player_match_history']  = get_player_match_history
    app.jinja_env.globals['get_player_radar_scores']   = get_player_radar_scores
    app.jinja_env.globals['get_player_seasons']        = get_player_seasons
    app.jinja_env.globals['get_player_radar_seasons']  = get_player_radar_seasons
    app.jinja_env.globals['season_label_for_date']     = season_label_for_date

    from .clubs.resolver import enrich_match_history_with_opponent
    app.jinja_env.globals['enrich_match_history_with_opponent'] = enrich_match_history_with_opponent

    # Phase 5c-2 + 5c-2.1 + 5d: evaluations history, eligibility, scout-comparison
    from .evaluations.helpers import (
        get_player_evaluations, nt_readiness_summary, group_scores_by_category,
        NT_LEVEL_LABEL_AR, RECOMMENDATION_LABEL_AR, ELIGIBILITY_STATUS_LABEL_AR,
        NT_LEVEL_LABEL_EN, RECOMMENDATION_LABEL_EN, NATIONALITY_ROUTE_LABEL_EN,
        CATEGORY_LABEL_EN,
    )
    from .players.eligibility import (
        compute_eligibility_status, compute_suggested_eligibility,
        RESIDENCY_YEARS_REQUIRED,
    )
    app.jinja_env.globals['get_player_evaluations']        = get_player_evaluations
    app.jinja_env.globals['nt_readiness_summary']          = nt_readiness_summary
    # Phase 7: NT-eval-count for the /nt squad table
    from .nt.helpers import get_nt_evaluation_count
    app.jinja_env.globals['get_nt_evaluation_count']       = get_nt_evaluation_count
    app.jinja_env.globals['group_scores_by_category']      = group_scores_by_category
    app.jinja_env.globals['compute_eligibility_status']    = compute_eligibility_status
    app.jinja_env.globals['compute_suggested_eligibility'] = compute_suggested_eligibility
    app.jinja_env.globals['NT_LEVEL_LABEL_AR']             = NT_LEVEL_LABEL_AR
    app.jinja_env.globals['RECOMMENDATION_LABEL_AR']       = RECOMMENDATION_LABEL_AR
    app.jinja_env.globals['ELIGIBILITY_STATUS_LABEL_AR']   = ELIGIBILITY_STATUS_LABEL_AR
    app.jinja_env.globals['NT_LEVEL_LABEL_EN']             = NT_LEVEL_LABEL_EN
    app.jinja_env.globals['RECOMMENDATION_LABEL_EN']       = RECOMMENDATION_LABEL_EN
    app.jinja_env.globals['NATIONALITY_ROUTE_LABEL_EN']    = NATIONALITY_ROUTE_LABEL_EN
    app.jinja_env.globals['RESIDENCY_YEARS_REQUIRED']      = RESIDENCY_YEARS_REQUIRED
    app.jinja_env.globals['CATEGORY_LABEL_EN']             = CATEGORY_LABEL_EN

    # Phase 5d: URL helper for the Latest/Averaged toggle, preserving other args
    from urllib.parse import urlencode as _urlencode
    from flask import request as _flask_request
    def urlencode_with(key, value):
        """Build a query string from request.args, replacing/appending one key."""
        try:
            args = _flask_request.args.to_dict(flat=False)
        except RuntimeError:
            args = {}
        args[key] = [value]
        # Flatten for urlencode
        flat = []
        for k, vs in args.items():
            if isinstance(vs, list):
                for v in vs:
                    flat.append((k, v))
            else:
                flat.append((k, vs))
        return _urlencode(flat)
    app.jinja_env.globals['urlencode_with'] = urlencode_with

    # Phase 5c-3: nationality + flag emoji helpers
    from .players.nationalities import (
        NATIONALITY_CHOICES, NATIONALITY_LABEL, flag_emoji,
    )
    app.jinja_env.globals['NATIONALITY_CHOICES'] = NATIONALITY_CHOICES
    app.jinja_env.globals['NATIONALITY_LABEL']   = NATIONALITY_LABEL
    app.jinja_env.globals['flag_emoji']          = flag_emoji

    # Phase 6.2.2: inline SVG flag for the eligibility card (no WeasyPrint
    # dependency — works in browser context too since it's just file I/O).
    from .passport.data import _flag_svg_inline
    app.jinja_env.globals['get_flag_svg'] = _flag_svg_inline

    # ── Session sliding window (Phase 8.1) ───────────────────────
    # Mark every session as permanent so PERMANENT_SESSION_LIFETIME
    # applies, and touch session.modified so Flask re-issues the
    # cookie on every response, resetting the idle timer.
    @app.before_request
    def refresh_session_timeout():
        session.permanent = True
        session.modified = True

    # ── Root routes ───────────────────────────────────────────────
    from flask_login import current_user

    @app.route('/')
    def index():
        from flask import render_template
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        # Youth NT is a restricted role — its landing page is the youth
        # section, not the general dashboard (which links to senior data).
        if current_user.role == 'youth_nt':
            return redirect(url_for('youth.index'))
        return render_template('index.html')

    @app.route('/health')
    def health():
        from flask import jsonify
        try:
            conn = db.get_db()
            with conn.cursor() as cur:
                cur.execute('SELECT 1')
                cur.fetchone()
            return jsonify({'status': 'ok', 'db': 'connected'}), 200
        except Exception as e:
            return jsonify({'status': 'error', 'db': 'disconnected', 'error': str(e)}), 503

    # ── First-boot admin seed (runs once if no admin exists) ──────
    with app.app_context():
        db.seed_initial_admin()

    return app
