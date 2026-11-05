import json
import getpass
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urljoin
from urllib.request import Request, urlopen


API_URL = "https://api.telegram.org"
SECRET_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,256}$")


def call_telegram_api(token, method, payload):
    api_request = Request(
        f"{API_URL}/bot{token}/{method}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(api_request, timeout=15) as response:
            result = json.loads(response.read())
    except HTTPError as error:
        raise RuntimeError(
            f"Telegram API returned HTTP {error.code} for {method}."
        ) from None
    except (URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError):
        raise RuntimeError(f"Telegram API request failed for {method}.") from None
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise RuntimeError(f"Telegram API rejected {method}.")


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN") or getpass.getpass(
        "Token de @BotFather (entrada oculta): "
    ).strip()
    if not token:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN before registering the webhook.")
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET") or getpass.getpass(
        "TELEGRAM_WEBHOOK_SECRET de Render (entrada oculta): "
    ).strip()
    if not secret or not SECRET_PATTERN.fullmatch(secret):
        raise RuntimeError(
            "Set TELEGRAM_WEBHOOK_SECRET to 1-256 letters, digits, '_' or '-'."
        )
    base_url = (
        os.getenv("PUBLIC_BASE_URL")
        or os.getenv("RENDER_EXTERNAL_URL")
        or input("URL pública HTTPS de tu sitio en Render: ").strip()
    )
    parsed_base_url = urlsplit(base_url or "")
    if parsed_base_url.scheme != "https" or not parsed_base_url.netloc:
        raise RuntimeError("PUBLIC_BASE_URL must be an absolute HTTPS URL.")

    webhook_url = urljoin(
        base_url.rstrip("/") + "/",
        "telegram/webhook",
    )
    call_telegram_api(
        token,
        "setWebhook",
        {
            "url": webhook_url,
            "secret_token": secret,
            "allowed_updates": ["message"],
        },
    )
    call_telegram_api(
        token,
        "setMyCommands",
        {
            "commands": [
                {"command": "start", "description": "Iniciar el bot"},
                {"command": "help", "description": "Ver qué puedo consultar"},
                {"command": "id", "description": "Ver el ID de este chat"},
            ]
        },
    )
    print("Webhook registrado y comandos del bot configurados.")


if __name__ == "__main__":
    main()
