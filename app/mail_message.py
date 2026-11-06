"""Build consistently identified transactional email messages."""

from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime, formataddr, make_msgid, parseaddr
from urllib.parse import urlsplit

from flask import current_app


def transactional_message(sender: str, recipient: str, subject: str) -> EmailMessage:
    message = EmailMessage()
    display_name, address = parseaddr(sender)
    message["From"] = formataddr((display_name or "Remate Martínez", address))
    message["To"] = recipient
    message["Subject"] = subject
    message["Date"] = format_datetime(datetime.now(timezone.utc))
    domain = urlsplit(current_app.config.get("PUBLIC_BASE_URL") or "").hostname
    message["Message-ID"] = make_msgid(domain=domain)
    return message