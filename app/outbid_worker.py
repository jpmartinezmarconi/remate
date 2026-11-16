"""Retry pending outbid notifications from the running web service."""

import threading

from app.auction_reminders import send_due_auction_outbid_notifications
from app.database import db


def run_outbid_retry_loop(app, stop_event, interval=60):
    while not stop_event.is_set():
        with app.app_context():
            try:
                send_due_auction_outbid_notifications()
            except Exception:
                db.session.rollback()
                app.logger.exception("Outbid notification retry failed; will retry again.")
        if stop_event.wait(interval):
            break


def start_outbid_retry_worker(app):
    worker = threading.Thread(
        target=run_outbid_retry_loop,
        args=(app, threading.Event()),
        name="outbid-notification-retry",
        daemon=True,
    )
    worker.start()
    return worker