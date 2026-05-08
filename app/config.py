import os


class Config:
    # Required — will raise KeyError on missing in production (no default)
    SECRET_KEY = os.environ.get('SECRET_KEY')

    # Database
    DATABASE_URL = os.environ.get('DATABASE_URL')

    # Flask env — defaults to development
    ENV = os.environ.get('FLASK_ENV', 'development')
    DEBUG = ENV == 'development'

    # Upload folder — defaults to ./uploads
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', './uploads')

    def __init__(self):
        # Fail loud if SECRET_KEY is missing (hard rule: no fallback default)
        if not self.SECRET_KEY:
            raise RuntimeError(
                'SECRET_KEY environment variable is not set. '
                'Set it in your .env file or environment before starting the app.'
            )
