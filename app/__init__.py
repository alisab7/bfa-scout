from flask import Flask
from .config import Config


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(config_class())

    # DB
    from . import db
    db.init_app(app)

    # Blueprints (placeholders — each registered with a TODO route)
    from .auth import bp as auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')

    from .players import bp as players_bp
    app.register_blueprint(players_bp, url_prefix='/players')

    from .evaluations import bp as evaluations_bp
    app.register_blueprint(evaluations_bp, url_prefix='/evaluations')

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

    # Root + health
    @app.route('/')
    def index():
        from flask import render_template
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

    return app
