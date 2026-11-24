from pathlib import Path

from flask_migrate import upgrade

from main import app


with app.app_context():
    upgrade(directory=str(Path(__file__).resolve().parent / "migrations"))
