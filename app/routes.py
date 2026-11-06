import hmac

from flask import Blueprint, current_app, jsonify, request

from app.database import db
from app.auction_reminders import (
    send_due_auction_completion_notifications,
    send_due_auction_closing_reminders,
    send_due_auction_outbid_notifications,
    send_due_auction_reminders,
)


main_bp = Blueprint("main", __name__)


@main_bp.get("/api/health")
@main_bp.get("/health")
def health():
    return jsonify(status="ok", service="MiProyecto")


@main_bp.post("/api/internal/process-reminders")
def process_auction_reminders():
    expected_secret = current_app.config.get("REMINDER_TRIGGER_SECRET")
    if not expected_secret:
        current_app.logger.error("REMINDER_TRIGGER_SECRET is not configured.")
        return jsonify(error="Reminder processing is not configured."), 503

    provided_secret = request.headers.get("Authorization", "")
    expected_authorization = f"Bearer {expected_secret}"
    if not hmac.compare_digest(provided_secret, expected_authorization):
        return jsonify(error="Unauthorized."), 403

    counts = {}
    errors = []
    jobs = (
        ("outbid_notifications", send_due_auction_outbid_notifications),
        ("auction_reminders", send_due_auction_reminders),
        ("closing_reminders", send_due_auction_closing_reminders),
        ("completion_notifications", send_due_auction_completion_notifications),
    )
    for name, job in jobs:
        try:
            result = job()
            if name == "completion_notifications":
                counts["auction_completion_notifications"] = result["email"]
                counts["telegram_completion_notifications"] = result["telegram"]
            else:
                counts[name] = result
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Reminder job %s failed.", name)
            errors.append(name)
    if errors:
        return jsonify(ok=False, sent=counts, failed=errors), 503
    return jsonify(ok=True, sent=counts)
