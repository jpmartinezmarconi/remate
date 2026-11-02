from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.parse import urljoin, urlsplit
import smtplib
import ssl

from flask import current_app, url_for

from app.database import db
from models.auction import Auction
from models.auction_reminder import AuctionReminder


def send_due_auction_reminders(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("The reminder dispatch time must include a timezone.")
    now = now.astimezone(timezone.utc)
    host = current_app.config.get("SMTP_HOST")
    port = current_app.config.get("SMTP_PORT", 587)
    username = current_app.config.get("SMTP_USERNAME")
    password = current_app.config.get("SMTP_PASSWORD")
    sender = current_app.config.get("SMTP_FROM_EMAIL")
    base_url = current_app.config.get("PUBLIC_BASE_URL")
    if not host or not sender:
        raise RuntimeError("SMTP_HOST and SMTP_FROM_EMAIL are required to send reminders.")
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise RuntimeError("SMTP_PORT must be an integer between 1 and 65535.")
    if not username or not password:
        raise RuntimeError("SMTP_USERNAME and SMTP_PASSWORD are required to send reminders.")
    if not base_url:
        raise RuntimeError("PUBLIC_BASE_URL is required to build reminder links.")
    parsed_base_url = urlsplit(base_url)
    if parsed_base_url.scheme not in {"http", "https"} or not parsed_base_url.netloc:
        raise RuntimeError("PUBLIC_BASE_URL must be an absolute HTTP or HTTPS URL.")

    deadline = now + timedelta(hours=24)
    reminders = (
        AuctionReminder.query.join(Auction)
        .filter(
            AuctionReminder.sent_at.is_(None),
            Auction.starts_at > now,
            Auction.starts_at <= deadline,
            Auction.closes_at > now,
        )
        .order_by(Auction.starts_at.asc(), AuctionReminder.id.asc())
        .all()
    )
    if not reminders:
        current_app.logger.info("No auction email reminders are due.")
        return 0

    sent_count = 0
    with smtplib.SMTP(host, port, timeout=30) as mail_server:
        mail_server.starttls(context=ssl.create_default_context())
        if username and password:
            mail_server.login(username, password)

        for reminder in reminders:
            user = reminder.user
            auction = reminder.auction
            if not user.email or "@" not in user.email:
                raise RuntimeError(
                    f"User {user.id} has no valid email for auction reminder {reminder.id}."
                )
            with current_app.test_request_context(base_url=base_url):
                auction_url = urljoin(
                    base_url.rstrip("/") + "/",
                    url_for("auction.detail", auction_id=auction.id).lstrip("/"),
                )
            starts_at = auction.starts_at_montevideo.strftime("%d/%m/%Y a las %H:%M")
            message = EmailMessage()
            message["Subject"] = (
                f"Recordatorio: la subasta de {auction.title} comienza mañana"
            )
            message["From"] = sender
            message["To"] = user.email
            message.set_content(
                f"Hola {user.username}:\n\n"
                f"La subasta de {auction.title} comienza el {starts_at} "
                "(hora de Uruguay).\n\n"
                f"Podés ver el artículo y sus detalles acá: {auction_url}\n\n"
                "Remate Martínez"
            )
            mail_server.send_message(message)
            reminder.sent_at = now
            db.session.commit()
            sent_count += 1

    current_app.logger.info("Sent %s auction email reminders.", sent_count)
    return sent_count
