import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import current_app


TELEGRAM_API_URL = "https://api.telegram.org"
TELEGRAM_TIMEOUT_SECONDS = 10
TELEGRAM_MAX_MESSAGE_LENGTH = 4096


class TelegramNotificationError(RuntimeError):
    pass


def send_telegram_notification(
    text: str, chat_id: int | str | None = None
) -> bool:
    token = current_app.config.get("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or current_app.config.get("TELEGRAM_NOTIFICATION_CHAT_ID")
    if not token or not chat_id:
        current_app.logger.info(
            "Telegram auction notifications are disabled; "
            "TELEGRAM_BOT_TOKEN or TELEGRAM_NOTIFICATION_CHAT_ID is missing."
        )
        return False

    api_request = Request(
        f"{TELEGRAM_API_URL}/bot{token}/sendMessage",
        data=json.dumps(
            {
                "chat_id": chat_id,
                "text": text[:TELEGRAM_MAX_MESSAGE_LENGTH],
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(api_request, timeout=TELEGRAM_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read())
    except HTTPError as error:
        raise TelegramNotificationError(
            f"Telegram API returned HTTP {error.code}."
        ) from None
    except (URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError):
        raise TelegramNotificationError("Telegram API request failed.") from None

    if not isinstance(result, dict) or result.get("ok") is not True:
        raise TelegramNotificationError("Telegram API rejected the request.")
    return True
