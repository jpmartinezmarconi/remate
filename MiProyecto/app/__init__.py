from pathlib import Path

from flask import Flask

from app.database import db
from config import Config


def create_app(config_class: type = Config) -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__)
    app.config.from_object(config_class)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    db.init_app(app)

    from app import models  # noqa: F401 - register models with SQLAlchemy metadata
    from app.routes import main_bp

    app.register_blueprint(main_bp)

    @app.cli.command("init-db")
    def init_db() -> None:
        """Create database tables for the registered models."""
        db.create_all()
        print("Database tables created.")

    return app
