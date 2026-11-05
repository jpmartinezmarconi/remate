from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from html import escape
from urllib.parse import urljoin, urlsplit
import smtplib
import ssl

from flask import current_app, url_for
from sqlalchemy import or_

from app.database import db
from models.auction import Auction
from models.auction_closing_reminder import AuctionClosingReminder
from models.auction_completion_notification import AuctionCompletionNotification
from models.auction_outbid_notification import AuctionOutbidNotification
from models.auction_payment import AuctionPayment
from models.auction_reminder import AuctionReminder
from models.bid import Bid
from models.user import User
from app.telegram_notifications import (
    TelegramNotificationError,
    send_telegram_notification,
)


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


def send_due_auction_completion_notifications(
    now: datetime | None = None,
) -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("The notification dispatch time must include a timezone.")
    now = now.astimezone(timezone.utc)
    telegram_enabled = bool(
        current_app.config.get("TELEGRAM_BOT_TOKEN")
        and current_app.config.get("TELEGRAM_NOTIFICATION_CHAT_ID")
    )
    pending_channels = [AuctionCompletionNotification.sent_at.is_(None)]
    if telegram_enabled:
        pending_channels.append(
            AuctionCompletionNotification.telegram_sent_at.is_(None)
        )
    auctions = (
        Auction.query.outerjoin(
            AuctionCompletionNotification,
            AuctionCompletionNotification.auction_id == Auction.id,
        )
        .filter(
            Auction.starts_at <= now,
            Auction.closes_at <= now,
            or_(
                AuctionCompletionNotification.auction_id.is_(None),
                *pending_channels,
            ),
        )
        .order_by(Auction.closes_at.asc(), Auction.id.asc())
        .all()
    )
    if not auctions:
        current_app.logger.info("No auction completion email notifications are due.")
        return {"email": 0, "telegram": 0}

    email_due = any(
        AuctionCompletionNotification.query.filter_by(auction_id=auction.id)
        .with_entities(AuctionCompletionNotification.sent_at)
        .scalar()
        is None
        for auction in auctions
    )
    if email_due:
        host, port, username, password, sender, base_url = _mail_configuration()
        recipient = current_app.config.get(
            "CONTACT_EMAIL", "remateonline@yahoo.com"
        )
        if not recipient or "@" not in recipient:
            raise RuntimeError("CONTACT_EMAIL must be a valid email address.")
        mail_context = smtplib.SMTP(host, port, timeout=30)
    else:
        sender = current_app.config.get("SMTP_FROM_EMAIL")
        recipient = current_app.config.get(
            "CONTACT_EMAIL", "remateonline@yahoo.com"
        )
        base_url = current_app.config.get("PUBLIC_BASE_URL")
        mail_context = nullcontext(None)
    sent_count = 0
    telegram_sent_count = 0
    with mail_context as mail_server:
        if mail_server is not None:
            mail_server.starttls(context=ssl.create_default_context())
            mail_server.login(username, password)

        for candidate in auctions:
            auction = (
                db.session.execute(
                    db.select(Auction)
                    .where(Auction.id == candidate.id)
                    .with_for_update()
                )
                .scalar_one_or_none()
            )
            if auction is None:
                db.session.rollback()
                continue

            notification = AuctionCompletionNotification.query.filter_by(
                auction_id=auction.id
            ).first()
            if notification is None:
                notification = AuctionCompletionNotification(auction_id=auction.id)
                db.session.add(notification)
                db.session.flush()
            needs_email = notification.sent_at is None
            needs_telegram = (
                telegram_enabled and notification.telegram_sent_at is None
            )
            if not needs_email and not needs_telegram:
                db.session.rollback()
                continue

            winner_bid = (
                Bid.query.filter_by(auction_id=auction.id)
                .order_by(Bid.amount.desc(), Bid.created_at.asc(), Bid.id.asc())
                .first()
            )
            auction_url = _auction_url(base_url, auction.id)
            closed_at = auction.closes_at_montevideo.strftime("%d/%m/%Y a las %H:%M")
            message = EmailMessage()

            if winner_bid is None:
                status = "Sin ofertas"
                subject = f"Subasta finalizada sin ofertas · {auction.title}"
                summary = "Esta subasta finalizó sin ofertas; podés evaluar republicar el lote."
                details = "<p>No se recibieron ofertas durante esta subasta.</p>"
            else:
                winner = winner_bid.bidder
                payment = AuctionPayment.query.filter_by(
                    auction_id=auction.id
                ).first()
                status = "Con ganador"
                subject = f"Subasta finalizada con ganador · {auction.title}"
                if payment is None:
                    payment_summary = "El ganador todavía no registró un método de pago."
                    payment_details = "Sin método de pago registrado"
                else:
                    payment_summary = (
                        f"Método de pago: {payment.method.replace('_', ' ')} "
                        f"({payment.status})"
                    )
                    payment_details = (
                        f"{payment.method.replace('_', ' ').title()} · "
                        f"{payment.status.title()} · $U {payment.amount:,.2f}"
                    )
                summary = (
                    "La subasta finalizó con un ganador. Revisá sus datos para "
                    "coordinar el envío o la entrega."
                )
                details = (
                    "<p><strong>Ganador:</strong> "
                    f"{escape(winner.full_name or winner.username)}</p>"
                    f"<p><strong>Correo:</strong> {escape(winner.email)}</p>"
                    f"<p><strong>Teléfono:</strong> {escape(winner.phone or 'No informado')}</p>"
                    f"<p><strong>Oferta ganadora:</strong> $U {winner_bid.amount:,.2f}</p>"
                    f"<p><strong>Pago:</strong> {escape(payment_details)}</p>"
                )

            text_body = (
                f"Subasta finalizada: {auction.title}\n"
                f"Estado: {status}\n"
                f"Lote: {auction.display_lot_number}\n"
                f"Cierre: {closed_at} (hora de Uruguay)\n\n"
                f"{summary}\n"
                + (
                    f"Ganador: {winner_bid.bidder.full_name or winner_bid.bidder.username}\n"
                    f"Correo: {winner_bid.bidder.email}\n"
                    f"Teléfono: {winner_bid.bidder.phone or 'No informado'}\n"
                    f"Oferta ganadora: $U {winner_bid.amount:,.2f}\n"
                    f"{payment_summary}\n"
                    if winner_bid is not None
                    else ""
                )
                + f"\nVer lote: {auction_url}\n\nRemate Martínez"
            )
            if needs_telegram:
                try:
                    if send_telegram_notification(text_body):
                        notification.telegram_sent_at = now
                        db.session.commit()
                        telegram_sent_count += 1
                except TelegramNotificationError:
                    current_app.logger.exception(
                        "Could not send the Telegram completion notification "
                        "for auction %s.",
                        auction.id,
                    )

            if needs_email:
                message["Subject"] = subject
                message["From"] = sender
                message["To"] = recipient
                message.set_content(text_body)
                message.add_alternative(
                    "<!doctype html><html lang=\"es\"><body style=\"margin:0;"
                    "padding:24px;background:#f2f5f8;font-family:Arial,sans-serif;"
                    "color:#1f2937\"><main style=\"max-width:600px;margin:auto;"
                    "padding:28px;background:#fff;border-radius:12px\">"
                    "<p style=\"margin:0 0 8px;color:#64748b\">REMATE MARTÍNEZ</p>"
                    "<h1 style=\"margin:0 0 16px;font-size:24px\">Subasta finalizada</h1>"
                    f"<p style=\"display:inline-block;padding:7px 12px;border-radius:20px;"
                    f"background:#e8f1fb;color:#064584\"><strong>{escape(status)}</strong></p>"
                    f"<h2 style=\"font-size:20px\">{escape(auction.title)}</h2>"
                    f"<p><strong>Lote:</strong> {escape(auction.display_lot_number)}<br>"
                    f"<strong>Cierre:</strong> {escape(closed_at)} (hora de Uruguay)</p>"
                    f"<p>{escape(summary)}</p>{details}"
                    f"<p style=\"margin:24px 0\"><a href=\"{escape(auction_url, quote=True)}\" "
                    "style=\"display:inline-block;padding:12px 18px;background:#064584;"
                    "color:white;text-decoration:none;border-radius:6px\">Ver lote</a></p>"
                    "<hr style=\"border:0;border-top:1px solid #e5e7eb\">"
                    "<p style=\"margin-bottom:0;color:#64748b\">Aviso automático · "
                    "Remate Martínez</p></main></body></html>",
                    subtype="html",
                )
                mail_server.send_message(message)
                notification.sent_at = now
                db.session.commit()
                sent_count += 1

    current_app.logger.info(
        "Sent %s auction completion email and %s Telegram notifications.",
        sent_count,
        telegram_sent_count,
    )
    return {"email": sent_count, "telegram": telegram_sent_count}


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
