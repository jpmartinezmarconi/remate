from email.message import EmailMessage
import smtplib
import ssl

from flask import current_app


def send_business_notification(subject: str, body: str) -> None:
    host = current_app.config.get("SMTP_HOST")
    port = current_app.config.get("SMTP_PORT", 587)
    username = current_app.config.get("SMTP_USERNAME")
    password = current_app.config.get("SMTP_PASSWORD")
    sender = current_app.config.get("SMTP_FROM_EMAIL")
    recipient = current_app.config.get("CONTACT_EMAIL", "remateonline@yahoo.com")
    if not host or not sender or not recipient or not username or not password:
        raise RuntimeError(
            "SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM_EMAIL, and "
            "CONTACT_EMAIL are required to send business notifications."
        )
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise RuntimeError("SMTP_PORT must be an integer between 1 and 65535.")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    message.set_content(body)

    with smtplib.SMTP(host, port, timeout=30) as mail_server:
        mail_server.starttls(context=ssl.create_default_context())
        mail_server.login(username, password)
        mail_server.send_message(message)
