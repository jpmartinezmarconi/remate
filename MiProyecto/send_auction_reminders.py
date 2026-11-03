from pathlib import Path

from flask_migrate import upgrade

from main import app

from app.auction_reminders import (
    send_due_auction_closing_reminders,
    send_due_auction_outbid_notifications,
    send_due_auction_reminders,
)


if __name__ == "__main__":
    with app.app_context():
        upgrade(directory=str(Path(__file__).resolve().parent / "migrations"))
        send_due_auction_reminders()
        send_due_auction_closing_reminders()
        send_due_auction_outbid_notifications()
