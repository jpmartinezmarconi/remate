from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.parse import urljoin, urlsplit
import smtplib
import ssl

from flask import current_app, url_for

from app.database import db
from models.auction import Auction
from models.auction_closing_reminder import AuctionClosingReminder
from models.auction_outbid_notification import AuctionOutbidNotification
from models.auction_reminder import AuctionReminder
from models.bid import Bid
from models.user import User


def _mail_configuration() -> tuple[str, int, str, str, str, str]:
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
    return host, port, username, password, sender, base_url


def _auction_url(base_url: str, auction_id: int) -> str:
    with current_app.test_request_context(base_url=base_url):
        return urljoin(
            base_url.rstrip("/") + "/",
            url_for("auction.detail", auction_id=auction_id).lstrip("/"),
        )


def send_due_auction_reminders(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("The reminder dispatch time must include a timezone.")
    now = now.astimezone(timezone.utc)
    host, port, username, password, sender, base_url = _mail_configuration()

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
            auction_url = _auction_url(base_url, auction.id)
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


def send_due_auction_closing_reminders(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("The reminder dispatch time must include a timezone.")
    now = now.astimezone(timezone.utc)
    host, port, username, password, sender, base_url = _mail_configuration()
    window_start = now + timedelta(minutes=25)
    window_end = now + timedelta(minutes=30)
    auctions = (
        Auction.query.filter(
            Auction.starts_at <= now,
            Auction.closes_at > window_start,
            Auction.closes_at <= window_end,
        )
        .order_by(Auction.closes_at.asc(), Auction.id.asc())
        .all()
    )
    due_reminders = []
    for auction in auctions:
        bidders = (
            User.query.join(Bid, Bid.user_id == User.id)
            .filter(Bid.auction_id == auction.id)
            .order_by(User.id.asc())
            .distinct()
            .all()
        )
        sent_user_ids = {
            row[0]
            for row in db.session.query(AuctionClosingReminder.user_id)
            .filter(AuctionClosingReminder.auction_id == auction.id)
            .all()
        }
        due_reminders.extend(
            (auction, user)
            for user in bidders
            if user.id not in sent_user_ids
        )

    if not due_reminders:
        current_app.logger.info("No auction closing email reminders are due.")
        return 0

    sent_count = 0
    with smtplib.SMTP(host, port, timeout=30) as mail_server:
        mail_server.starttls(context=ssl.create_default_context())
        mail_server.login(username, password)

        for auction, user in due_reminders:
            if not user.email or "@" not in user.email:
                raise RuntimeError(
                    f"User {user.id} has no valid email for auction closing reminder."
                )
            message = EmailMessage()
            message["Subject"] = f"Quedan 30 minutos: {auction.title}"
            message["From"] = sender
            message["To"] = user.email
            message.set_content(
                f"Hola {user.username}:\n\n"
                f"La subasta de {auction.title} (lote {auction.display_lot_number}) "
                "está llegando a su cierre. Quedan aproximadamente 30 minutos "
                "para ofertar.\n\n"
                f"Finaliza el {auction.closes_at_montevideo.strftime('%d/%m/%Y a las %H:%M')} "
                "(hora de Uruguay).\n"
                f"Consultá el lote y su oferta actual: {_auction_url(base_url, auction.id)}\n\n"
                "Remate Martínez"
            )
            mail_server.send_message(message)
            db.session.add(
                AuctionClosingReminder(
                    auction_id=auction.id,
                    user_id=user.id,
                    sent_at=now,
                )
            )
            db.session.commit()
            sent_count += 1

    current_app.logger.info("Sent %s auction closing email reminders.", sent_count)
    return sent_count


def send_due_auction_outbid_notifications() -> int:
    notifications = (
        AuctionOutbidNotification.query.filter(
            AuctionOutbidNotification.sent_at.is_(None)
        )
        .order_by(AuctionOutbidNotification.id.asc())
        .all()
    )
    if not notifications:
        current_app.logger.info("No auction outbid email notifications are due.")
        return 0

    host, port, username, password, sender, base_url = _mail_configuration()
    sent_count = 0
    with smtplib.SMTP(host, port, timeout=30) as mail_server:
        mail_server.starttls(context=ssl.create_default_context())
        mail_server.login(username, password)

        for notification in notifications:
            outbid_bid = notification.outbid_bid
            replacement_bid = notification.replacement_bid
            user = outbid_bid.bidder
            auction = outbid_bid.auction
            if not user.email or "@" not in user.email:
                raise RuntimeError(
                    f"User {user.id} has no valid email for outbid notification "
                    f"{notification.id}."
                )
            message = EmailMessage()
            message["Subject"] = f"Superaron tu oferta: {auction.title}"
            message["From"] = sender
            message["To"] = user.email
            message.set_content(
                f"Hola {user.username}:\n\n"
                f"Tu oferta de $U {outbid_bid.amount:,.2f} para "
                f"{auction.title} (lote {auction.display_lot_number}) "
                f"fue superada por una oferta de $U {replacement_bid.amount:,.2f}.\n\n"
                f"Podés volver a ofertar desde acá: {_auction_url(base_url, auction.id)}\n\n"
                "Remate Martínez"
            )
            mail_server.send_message(message)
            notification.sent_at = datetime.now(timezone.utc)
            db.session.commit()
            sent_count += 1

    current_app.logger.info("Sent %s auction outbid email notifications.", sent_count)
    return sent_count
