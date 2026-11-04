from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from app import create_app
from app.database import db
from models.auction import Auction
from models.auction_group import AuctionGroup


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
        return self.client.post("/api/ayuda", json={"message": message})

    def test_lists_active_and_upcoming_lots_with_current_public_data(self):
        active = self.ask("¿Qué subastas están activas?")
        self.assertEqual(active.status_code, 200)
        self.assertIn("Reloj antiguo", active.json["reply"])
        self.assertIn("Oferta actual: $U 125.00", active.json["reply"])
        self.assertNotIn("Juego de sillas", active.json["reply"])

        upcoming = self.ask("¿Cuáles son las próximas subastas?")
        self.assertEqual(upcoming.status_code, 200)
        self.assertIn("Lote U-03: Juego de sillas (Próximamente)", upcoming.json["reply"])
        self.assertIn("Oferta por unidad; cantidad: 4", upcoming.json["reply"])
        self.assertTrue(any(link["url"] == "/subasta/2" for link in upcoming.json["links"]))

    def test_answers_lot_number_and_common_questions(self):
        lot = self.ask("¿Qué pasa con el lote R-12?")
        self.assertIn("Reloj antiguo", lot.json["reply"])
        self.assertIn("está activa", lot.json["reply"])

        title_search = self.ask("¿A qué hora cierra el reloj antiguo?")
        self.assertIn("Reloj antiguo", title_search.json["reply"])
        self.assertIn("Finaliza el", title_search.json["reply"])

        address = self.ask("¿Dónde puedo retirar?")
        self.assertIn("Av. 8 de Octubre 4336/4328", address.json["reply"])

        contact = self.ask("¿Cuál es el email y teléfono?")
        self.assertIn("096 164 645", contact.json["reply"])
        self.assertIn(
            "https://wa.me/59896164645",
            next(link["url"] for link in contact.json["links"] if link["label"] == "WhatsApp"),
        )
        self.assertIn("info@rematemartinez.com.uy", contact.json["reply"])

        commission = self.ask("¿Qué comisión se cobra?")
        self.assertIn("20%", commission.json["reply"])
        self.assertIn("ficha del lote", commission.json["reply"])

        payment = self.ask("¿Cómo pago por transferencia?")
        self.assertIn("001901236", payment.json["reply"])
        self.assertIn("JUAN MARTINEZ", payment.json["reply"])
        self.assertIn("9102129", payment.json["reply"])

        notifications = self.ask("¿Puedo recibir un recordatorio?")
        self.assertIn("24 horas antes", notifications.json["reply"])

    def test_validates_help_question_and_page_widget(self):
        self.assertEqual(self.client.post("/api/ayuda", json={}).status_code, 400)
        self.assertEqual(
            self.ask("x" * 301).status_code,
            400,
        )
        self.assertEqual(
            self.client.post("/api/ayuda", data="{}", content_type="text/plain").status_code,
            400,
        )
        page = self.client.get("/")
        self.assertIn(b"help-bot-launcher", page.data)
        self.assertIn(b"help-bot.js", page.data)
        self.assertIn(b"data-help-question=", page.data)
        self.assertIn(b">Comisi", page.data)


if __name__ == "__main__":
    unittest.main()
