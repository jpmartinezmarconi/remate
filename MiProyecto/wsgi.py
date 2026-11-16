import os
from pathlib import Path

from flask_migrate import upgrade

from main import app


with app.app_context():
    upgrade(directory=str(Path(__file__).resolve().parent / "migrations"))

if os.getenv("RENDER", "").lower() == "true":
    from app.outbid_worker import start_outbid_retry_worker

    start_outbid_retry_worker(app)
