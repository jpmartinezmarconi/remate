import os

from flask import Flask
from flask_cors import CORS

from config import Config
from .database import db


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
    origins = app.config.get("CORS_ORIGINS", "http://localhost:3000")
    CORS(app, resources={r"/api/*": {"origins": origins.split(",")}})

    from .routes import main_bp

    app.register_blueprint(main_bp)
    return app
