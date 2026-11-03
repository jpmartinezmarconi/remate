import os

from dotenv import load_dotenv


load_dotenv()


def _database_url_from_environment():
    database_url = os.getenv("DATABASE_URL", "").strip()
    is_render = os.getenv("RENDER", "").lower() == "true"

    if not database_url:
        if is_render:
            raise RuntimeError(
                "DATABASE_URL must be set to a persistent PostgreSQL database "
                "in Render; SQLite storage is ephemeral."
            )
        return "sqlite:///app.db"

    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    if database_url.startswith("postgresql+psycopg://"):
        database_url = database_url.replace(
            "postgresql+psycopg://", "postgresql+psycopg2://", 1
        )
    elif database_url.startswith("postgresql://"):
        database_url = database_url.replace(
            "postgresql://", "postgresql+psycopg2://", 1
        )

    if is_render and not database_url.startswith("postgresql+psycopg2://"):
        raise RuntimeError(
            "DATABASE_URL must use PostgreSQL in Render; SQLite storage is "
            "ephemeral and can lose auction data on deploy."
        )

    return database_url


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
    PRIVATE_AREA_PASSWORD = os.getenv("PASSWORD_AREA_PRIVADA") or os.getenv(
        "PRIVATE_AREA_PASSWORD"
    )
    SMTP_HOST = os.getenv("SMTP_HOST")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USERNAME = os.getenv("SMTP_USERNAME")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
    SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL")
    PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL") or os.getenv("RENDER_EXTERNAL_URL")
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET")
    BANK_TRANSFER_INSTRUCTIONS = os.getenv("BANK_TRANSFER_INSTRUCTIONS", "")
    SQLALCHEMY_DATABASE_URI = _database_url_from_environment()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000")
