import os
from datetime import timedelta
from datetime import datetime

from flask import Flask, g, session
from flask_cors import CORS
from flask_migrate import Migrate

from config import Config
from .database import db

migrate = Migrate()


def create_app(config_class=Config):
    app = Flask(
        __name__,
        instance_relative_config=True,
        template_folder="../templates",
        static_folder="../static",
    )
    app.config.from_object(config_class)
    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")
    app.config.setdefault("PERMANENT_SESSION_LIFETIME", timedelta(hours=12))
    app.config.setdefault("SESSION_COOKIE_SECURE", os.getenv("FLASK_ENV") == "production")
    origins = app.config.get("CORS_ORIGINS", "http://localhost:3000")
    CORS(app, resources={r"/api/*": {"origins": origins.split(",")}})

    # Import models so Flask-Migrate sees every table in the metadata.
    import models  # noqa: F401

    from .routes import main_bp
    from routes.auction import auction_bp
    from routes.auth import auth_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auction_bp)
    app.register_blueprint(auth_bp)

    @app.before_request
    def load_current_user():
        from models.user import User

        user_id = session.get("user_id")
        g.current_user = db.session.get(User, user_id) if user_id else None

    @app.context_processor
    def inject_template_helpers():
        from routes.security import generate_csrf_token

        return {
            "current_user": g.current_user,
            "csrf_token": generate_csrf_token,
            "current_year": datetime.now().year,
        }

    @app.template_filter("uyu")
    def format_uyu(value):
        return f"$U {value:,.2f}"

    return app
