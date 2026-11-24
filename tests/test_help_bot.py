from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from app import create_app
from app.database import db
from models.auction import Auction
from models.auction_group import AuctionGroup
from routes.help import _answer


class HelpBotConfig:
    TESTING = True
    SECRET_KEY = "test-key"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False


class HelpBotTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(HelpBotConfig)
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

    def ask(self, message):
        with self.app.test_request_context():
            return _answer(message)

    def test_lists_active_and_upcoming_lots_with_current_public_data(self):
        active_reply, _ = self.ask("¿Qué subastas están activas?")
        self.assertIn("Reloj antiguo", active_reply)
        self.assertIn("Oferta actual: $U 125.00", active_reply)
        self.assertNotIn("Juego de sillas", active_reply)

        upcoming_reply, upcoming_links = self.ask("¿Cuáles son las próximas subastas?")
        self.assertIn("Lote U-03: Juego de sillas (Próximamente)", upcoming_reply)
        self.assertIn("Oferta por unidad; cantidad: 4", upcoming_reply)
        self.assertTrue(any(link["url"] == "/subasta/2" for link in upcoming_links))

    def test_answers_lot_number_and_common_questions(self):
        lot_reply, _ = self.ask("¿Qué pasa con el lote R-12?")
        self.assertIn("Reloj antiguo", lot_reply)
        self.assertIn("está activa", lot_reply)

        title_reply, _ = self.ask("¿A qué hora cierra el reloj antiguo?")
        self.assertIn("Reloj antiguo", title_reply)
        self.assertIn("Finaliza el", title_reply)

        address_reply, _ = self.ask("¿Dónde puedo retirar?")
        self.assertIn("Av. 8 de Octubre 4336/4328", address_reply)

        contact_reply, contact_links = self.ask("¿Cuál es el email y teléfono?")
        self.assertIn("096 164 645", contact_reply)
        self.assertIn(
            "https://wa.me/59896164645",
            next(link["url"] for link in contact_links if link["label"] == "WhatsApp"),
        )
        self.assertIn("remateonline@yahoo.com", contact_reply)
        self.assertNotIn("info@rematemartinez.com.uy", contact_reply)

        commission_reply, _ = self.ask("¿Qué comisión se cobra?")
        self.assertIn("20%", commission_reply)
        self.assertIn("ficha del lote", commission_reply)

        payment_reply, _ = self.ask("¿Cómo pago por transferencia?")
        self.assertIn("001901236", payment_reply)
        self.assertIn("JUAN MARTINEZ", payment_reply)
        self.assertIn("9102129", payment_reply)

        notifications_reply, _ = self.ask("¿Puedo recibir un recordatorio?")
        self.assertIn("24 horas antes", notifications_reply)

    def test_web_assistant_is_removed_and_telegram_qr_remains(self):
        self.assertEqual(self.client.post("/api/ayuda", json={}).status_code, 404)
        page = self.client.get("/")
        self.assertNotIn(b"help-bot", page.data)
        self.assertNotIn(b"help-bot.js", page.data)
        self.assertIn(b"telegram-qr.svg", page.data)
        self.assertIn(b"https://t.me/rematemartinezbot", page.data)
        self.assertIn(b"20% de comisi", page.data)
        self.assertIn(b"mailto:remateonline@yahoo.com", page.data)
        self.assertNotIn(b"info@rematemartinez.com.uy", page.data)


if __name__ == "__main__":
    unittest.main()
