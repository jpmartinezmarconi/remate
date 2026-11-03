import json
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

from app import create_app
from app.database import db
from models.auction import Auction
from models.auction_group import AuctionGroup


class TelegramBotConfig:
    TESTING = True
    SECRET_KEY = "test-key"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    TELEGRAM_BOT_TOKEN = "test-token"
    TELEGRAM_WEBHOOK_SECRET = "test_secret-123"
    PUBLIC_BASE_URL = "https://remate.example.test"


class TelegramBotTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TelegramBotConfig)
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            db.session.add_all(
                [
                    Auction(
                        title="Reloj antiguo",
                        description="Reloj de colección",
                        lot_number="R-12",
                        starting_price=Decimal("100"),
                        current_price=Decimal("125"),
                        commission_percent=Decimal("20"),
                        quantity=1,
                        sale_mode="lot",
                        group_name="Colección",
                        starts_at=now - timedelta(minutes=5),
                        closes_at=now + timedelta(hours=2),
                        sales_group=AuctionGroup(name="Colección"),
                    ),
                    Auction(
                        title="Juego de sillas",
                        description="Cuatro sillas",
                        lot_number="U-03",
                        starting_price=Decimal("50"),
                        current_price=Decimal("50"),
                        commission_percent=Decimal("20"),
                        quantity=4,
                        sale_mode="units",
                        group_name="Muebles",
                        starts_at=now + timedelta(days=2),
                        closes_at=now + timedelta(days=3),
                        sales_group=AuctionGroup(name="Muebles"),
                    ),
                ]
            )
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def post_update(self, payload, secret="test_secret-123"):
        return self.client.post(
            "/telegram/webhook",
            json=payload,
            headers={"X-Telegram-Bot-Api-Secret-Token": secret},
        )

    @patch("routes.telegram_bot.urlopen")
    def test_start_replies_and_links_to_site(self, mocked_urlopen):
        mocked_urlopen.return_value.__enter__.return_value.read.return_value = (
            b'{"ok":true,"result":{}}'
        )
        response = self.post_update(
            {
                "message": {
                    "text": "/start",
                    "chat": {"id": 12345},
                }
            }
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["ok"])
        api_request = mocked_urlopen.call_args.args[0]
        self.assertIn("/bottest-token/sendMessage", api_request.full_url)
        payload = json.loads(api_request.data)
        self.assertEqual(payload["chat_id"], 12345)
        self.assertIn("Remate Martínez", payload["text"])
        self.assertEqual(
            payload["reply_markup"]["inline_keyboard"][0][0]["url"],
            "https://remate.example.test/subastas-activas",
        )

    @patch("routes.telegram_bot.urlopen")
    def test_answers_common_questions_and_filters_non_web_links(self, mocked_urlopen):
        mocked_urlopen.return_value.__enter__.return_value.read.return_value = (
            b'{"ok":true,"result":{}}'
        )
        response = self.post_update(
            {
                "message": {
                    "text": "¿Dónde puedo retirar?",
                    "chat": {"id": 12345},
                }
            }
        )

        self.assertEqual(response.status_code, 200)
        payload = json.loads(mocked_urlopen.call_args.args[0].data)
        self.assertIn("Av. 8 de Octubre", payload["text"])
        buttons = payload["reply_markup"]["inline_keyboard"]
        self.assertEqual(buttons[0][0]["url"], "https://wa.me/59896430909")
        self.assertTrue(
            all(
                button["url"].startswith(("http://", "https://"))
                for row in buttons
                for button in row
            )
        )

    @patch("routes.telegram_bot.urlopen")
    def test_answers_with_live_active_and_upcoming_auction_data(self, mocked_urlopen):
        mocked_urlopen.return_value.__enter__.return_value.read.return_value = (
            b'{"ok":true,"result":{}}'
        )
        active = self.post_update(
            {
                "message": {
                    "text": "¿Qué subastas están activas?",
                    "chat": {"id": 12345},
                }
            }
        )
        upcoming = self.post_update(
            {
                "message": {
                    "text": "¿Cuáles son las próximas subastas?",
                    "chat": {"id": 12345},
                }
            }
        )

        self.assertEqual(active.status_code, 200)
        active_payload = json.loads(mocked_urlopen.call_args_list[0].args[0].data)
        self.assertIn("Reloj antiguo", active_payload["text"])
        self.assertIn("Oferta actual: $U 125.00", active_payload["text"])

        self.assertEqual(upcoming.status_code, 200)
        upcoming_payload = json.loads(mocked_urlopen.call_args_list[1].args[0].data)
        self.assertIn("Juego de sillas", upcoming_payload["text"])
        self.assertIn("Próximamente", upcoming_payload["text"])

    @patch("routes.telegram_bot.urlopen")
    def test_rejects_bad_secret_without_contacting_telegram(self, mocked_urlopen):
        response = self.post_update(
            {"message": {"text": "/start", "chat": {"id": 12345}}},
            secret="wrong",
        )
        self.assertEqual(response.status_code, 403)
        mocked_urlopen.assert_not_called()

    def test_rejects_invalid_json_and_ignores_non_text_updates(self):
        invalid = self.client.post(
            "/telegram/webhook",
            data="not json",
            content_type="application/json",
            headers={"X-Telegram-Bot-Api-Secret-Token": "test_secret-123"},
        )
        self.assertEqual(invalid.status_code, 400)
        ignored = self.post_update({"message": {"chat": {"id": 12345}}})
        self.assertEqual(ignored.status_code, 200)
        self.assertTrue(ignored.json["ok"])

    @patch("routes.telegram_bot.urlopen")
    def test_explains_question_length_limit_without_truncating(self, mocked_urlopen):
        mocked_urlopen.return_value.__enter__.return_value.read.return_value = (
            b'{"ok":true,"result":{}}'
        )
        response = self.post_update(
            {
                "message": {
                    "text": "x" * 301,
                    "chat": {"id": 12345},
                }
            }
        )

        self.assertEqual(response.status_code, 200)
        mocked_urlopen.assert_called_once()
        payload = json.loads(mocked_urlopen.call_args.args[0].data)
        self.assertIn("no puede superar 300 caracteres", payload["text"])

    @patch("routes.telegram_bot.urlopen")
    def test_reports_telegram_delivery_failure(self, mocked_urlopen):
        mocked_urlopen.return_value.__enter__.return_value.read.return_value = (
            b'{"ok":false}'
        )
        response = self.post_update(
            {
                "message": {
                    "text": "¿Cuál es la comisión?",
                    "chat": {"id": 12345},
                }
            }
        )
        self.assertEqual(response.status_code, 502)

    def test_missing_secret_configuration_disables_webhook(self):
        self.app.config["TELEGRAM_WEBHOOK_SECRET"] = None
        response = self.post_update(
            {"message": {"text": "/start", "chat": {"id": 12345}}}
        )
        self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main()
