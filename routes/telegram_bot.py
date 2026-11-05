import hmac
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

from flask import Blueprint, current_app, jsonify, request

from .help import _answer, MAX_QUESTION_LENGTH


telegram_bp = Blueprint("telegram", __name__)
TELEGRAM_API_URL = "https://api.telegram.org"
TELEGRAM_TIMEOUT_SECONDS = 10
TELEGRAM_MAX_MESSAGE_LENGTH = 4096
WEBHOOK_SECRET_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,256}$")


class TelegramAPIError(Exception):
    pass


def _telegram_api(method: str, payload: dict) -> dict:
    token = current_app.config["TELEGRAM_BOT_TOKEN"]
    api_request = Request(
        f"{TELEGRAM_API_URL}/bot{token}/{method}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(api_request, timeout=TELEGRAM_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read())
    except HTTPError as error:
        raise TelegramAPIError(
            f"Telegram API returned HTTP {error.code}."
        ) from None
    except (URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError):
        raise TelegramAPIError("Telegram API request failed.") from None

    if not isinstance(result, dict) or result.get("ok") is not True:
        raise TelegramAPIError("Telegram API rejected the request.")
    return result


def _telegram_keyboard(links: list[dict[str, str]]) -> dict | None:
    base_url = current_app.config.get("PUBLIC_BASE_URL")
    if not base_url:
        raise RuntimeError("PUBLIC_BASE_URL is required for Telegram links.")
    parsed_base_url = urlsplit(base_url)
    if parsed_base_url.scheme not in {"http", "https"} or not parsed_base_url.netloc:
        raise RuntimeError("PUBLIC_BASE_URL must be an absolute HTTP or HTTPS URL.")

    buttons = []
    for link in links:
        target = link["url"]
        parsed_target = urlsplit(target)
        if target.startswith("/"):
            target = urljoin(base_url.rstrip("/") + "/", target.lstrip("/"))
        elif parsed_target.scheme not in {"http", "https"} or not parsed_target.netloc:
            continue
        buttons.append({"text": link["label"], "url": target})

    if not buttons:
        return None
    return {
        "inline_keyboard": [
            buttons[index : index + 2] for index in range(0, len(buttons), 2)
        ]
    }


@telegram_bp.post("/telegram/webhook")
def telegram_webhook():
    token = current_app.config.get("TELEGRAM_BOT_TOKEN")
    secret = current_app.config.get("TELEGRAM_WEBHOOK_SECRET")
    if not token or not secret or not WEBHOOK_SECRET_PATTERN.fullmatch(secret):
        current_app.logger.error("Telegram webhook credentials are not configured.")
        return jsonify(error="Telegram webhook is not configured."), 503

    supplied_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not hmac.compare_digest(secret, supplied_secret):
        return jsonify(error="Unauthorized."), 403

    if request.content_length and request.content_length > 16_384:
        return jsonify(error="Update exceeds the allowed size."), 413
    update = request.get_json(silent=True)
    if not isinstance(update, dict):
        return jsonify(error="Expected a JSON Telegram update."), 400

    message = update.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("text"), str):
        return jsonify(ok=True)
    chat = message.get("chat")
    chat_id = chat.get("id") if isinstance(chat, dict) else None
    if not isinstance(chat_id, (int, str)) or isinstance(chat_id, bool):
        return jsonify(ok=True)

    text = message["text"].strip()
    if not text:
        return jsonify(ok=True)
    command = text.split(maxsplit=1)[0].split("@", maxsplit=1)[0].lower()
    if command == "/id":
        reply = (
            f"El ID de este chat es: {chat_id}\n"
            "Guardalo como TELEGRAM_NOTIFICATION_CHAT_ID en Render para recibir "
            "avisos privados de subastas. No lo compartas públicamente."
        )
        links = []
    elif command in {"/start", "/help"}:
        reply = (
            "¡Hola! Soy el bot de Remate Martínez. Puedo informarte sobre "
            "subastas activas y próximas, lotes, horarios, comisión, pagos, "
            "dirección y contacto. ¿Qué necesitás saber?"
        )
        links = [
            {"label": "Ver subastas", "url": "/subastas-activas"},
            {"label": "Ver próximas subastas", "url": "/proximas-subastas"},
            {"label": "Abrir Remate Martínez", "url": "/"},
        ]
    elif len(text) > MAX_QUESTION_LENGTH:
        reply = f"Tu pregunta no puede superar {MAX_QUESTION_LENGTH} caracteres."
        links = []
    else:
        reply, links = _answer(text)

    telegram_payload = {
        "chat_id": chat_id,
        "text": reply[:TELEGRAM_MAX_MESSAGE_LENGTH],
    }
    keyboard = _telegram_keyboard(links)
    if keyboard:
        telegram_payload["reply_markup"] = keyboard

    try:
        _telegram_api("sendMessage", telegram_payload)
    except TelegramAPIError:
        current_app.logger.error("Telegram could not deliver a bot response.")
        return jsonify(error="Telegram could not deliver the response."), 502
    except RuntimeError as error:
        current_app.logger.error("Telegram link configuration error: %s", error)
        return jsonify(error="Telegram link configuration is incomplete."), 503
    return jsonify(ok=True)
