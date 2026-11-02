from io import BytesIO
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app import create_app
from app.auction_reminders import send_due_auction_reminders
from app.database import db
from models.auction import Auction
from models.auction_image import AuctionImage
from models.auction_payment import AuctionPayment
from models.auction_reminder import AuctionReminder
from models.bid import Bid
from models.user import User


class PrivateAreaConfig:
    TESTING = True
    SECRET_KEY = "test-key"
    PRIVATE_AREA_PASSWORD = "test-private-password"
    SMTP_HOST = "smtp.example.test"
    SMTP_PORT = 587
    SMTP_USERNAME = "sender@example.test"
    SMTP_PASSWORD = "test-smtp-password"
    SMTP_FROM_EMAIL = "Remate Martínez <sender@example.test>"
    PUBLIC_BASE_URL = "https://remate.example.test"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False


class PrivateAreaTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(PrivateAreaConfig)
        self.client = self.app.test_client()
        with self.app.app_context():
            db.drop_all()
            db.create_all()
        self.client.get("/area-privada")

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def csrf_token(self):
        with self.client.session_transaction() as session:
            return session["csrf_token"]

    def login(self):
        return self.client.post(
            "/area-privada",
            data={
                "csrf_token": self.csrf_token(),
                "password": "test-private-password",
            },
        )

    def test_navigation_links_follow_requested_order(self):
        response = self.client.get("/")
        page = response.get_data(as_text=True)
        self.assertIn("Funcionamiento del remate", page)
        self.assertIn("16,67% de comisión", page)
        self.assertIn("Av. 8 de Octubre 4336/4328", page)
        labels = (
            "Inicio",
            "Ingresar",
            "Crear cuenta",
            "Subastas activas",
            "Artículos en remate",
            "Cómo funciona",
            "Contacto",
            "Área privada",
        )
        positions = [page.index(label) for label in labels]
        self.assertEqual(positions, sorted(positions))

    def create_lot(self, lot_number, *, featured=False, photos=None, **overrides):
        data = {
            "csrf_token": self.csrf_token(),
            "title": f"Artículo {lot_number}",
            "description": "Descripción del artículo",
            "lot_number": lot_number,
            "group_name": "Colección",
            "starting_price": "100.00",
            "commission_percent": "12.5",
            "quantity": "3",
            "sale_mode": "units",
            "start_mode": "now",
            "duration_hours": "24",
        }
        data.update(overrides)
        if data.get("start_mode") == "scheduled" and "starts_at" not in data:
            start = (datetime.now(timezone.utc) + timedelta(hours=25)).astimezone(
                ZoneInfo("America/Montevideo")
            )
            data["starts_at"] = start.strftime("%Y-%m-%dT%H:%M")
        if featured:
            data["featured_on_home"] = "on"
        if photos:
            data["photos"] = photos
        return self.client.post(
            "/area-privada/lotes",
            data=data,
            content_type="multipart/form-data",
            follow_redirects=True,
        )

    def test_private_panel_requires_password_and_rejects_wrong_password(self):
        response = self.client.get("/area-privada/panel")
        self.assertEqual(response.status_code, 302)

        response = self.client.post(
            "/area-privada",
            data={"csrf_token": self.csrf_token(), "password": "incorrecta"},
            follow_redirects=True,
        )
        self.assertIn("no es correcta", response.get_data(as_text=True))

        response = self.login()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/area-privada/panel").status_code, 200)

    def test_creates_grouped_unit_lot_with_persistent_photo(self):
        self.login()
        response = self.create_lot(
            "U-01",
            featured=True,
            photos=[
                (BytesIO(b"\x89PNG\r\n\x1a\nimage"), f"foto-{index}.png")
                for index in range(6)
            ],
        )
        self.assertIn("se publicó correctamente", response.get_data(as_text=True))

        with self.app.app_context():
            auction = Auction.query.one()
            image = AuctionImage.query.order_by(AuctionImage.id).first()
            auction_id = auction.id
            image_id = image.id
            self.assertEqual(auction.sale_mode, "units")
            self.assertEqual(auction.quantity, 3)
            self.assertEqual(str(auction.commission_percent), "12.50")
            self.assertEqual(len(auction.photos), 6)
            self.assertEqual(image.content_type, "image/png")

        home = self.client.get("/")
        self.assertIn(b"Art\xc3\xadculo U-01", home.data)
        self.assertIn(b"3 unidades", home.data)
        active = self.client.get("/subastas-activas")
        self.assertIn(b"Colecci\xc3\xb3n", active.data)
        detail = self.client.get(f"/subasta/{auction_id}")
        self.assertIn(b"el ganador se adjudica toda la cantidad", detail.data)
        image_response = self.client.get(f"/area-privada/fotos/{image_id}")
        self.assertEqual(image_response.status_code, 200)
        self.assertEqual(image_response.mimetype, "image/png")

    def test_only_five_active_lots_per_group_can_be_featured(self):
        self.login()
        for index in range(1, 6):
            self.create_lot(f"F-{index}", featured=True)

        response = self.create_lot("F-6", featured=True)
        self.assertIn("máximo cinco", response.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(Auction.query.count(), 5)
            self.assertEqual(
                Auction.query.filter_by(featured_on_home=True).count(), 5
            )

    def test_homepage_allows_at_most_five_featured_groups(self):
        self.login()
        for index in range(1, 6):
            self.create_lot(
                f"G-{index}",
                featured=True,
                group_name=f"Grupo {index}",
            )

        response = self.create_lot(
            "G-6",
            featured=True,
            group_name="Grupo 6",
        )
        self.assertIn("cinco grupos", response.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(Auction.query.count(), 5)

    def test_non_featured_lots_only_appear_in_active_list(self):
        self.login()
        self.create_lot("A-01", featured=False)

        self.assertNotIn(b"Art\xc3\xadculo A-01", self.client.get("/").data)
        self.assertIn(
            b"Art\xc3\xadculo A-01", self.client.get("/subastas-activas").data
        )

    def test_scheduled_auction_can_be_subscribed_to_and_sends_one_email(self):
        self.login()
        start = (datetime.now(timezone.utc) + timedelta(hours=23)).astimezone(
            ZoneInfo("America/Montevideo")
        )
        self.create_lot(
            "S-01",
            start_mode="scheduled",
            starts_at=start.strftime("%Y-%m-%dT%H:%M"),
        )
        with self.app.app_context():
            auction = Auction.query.one()
            auction_id = auction.id
            user = User(
                username="bidder",
                full_name="Bidder Example",
                email="bidder@example.test",
                phone="099123456",
                shipping_address="18 de Julio 1000",
                city="Montevideo",
                postal_code="11100",
            )
            user.set_password("safe-password")
            db.session.add(user)
            db.session.commit()
            user_id = user.id
        with self.client.session_transaction() as session:
            session["user_id"] = user_id

        upcoming = self.client.get(f"/subasta/{auction_id}")
        self.assertIn(b"PR\xc3\x93XIMAMENTE", upcoming.data)
        self.assertIn(b"Notificame por mail", upcoming.data)
        self.assertNotIn(b"Este remate ya cerr\xc3\xb3", upcoming.data)

        response = self.client.post(
            f"/subasta/{auction_id}/notificar",
            data={"csrf_token": self.csrf_token()},
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            reminder = AuctionReminder.query.one()
            self.assertEqual(reminder.user_id, user_id)
            self.assertIsNone(reminder.sent_at)

            now = datetime.now(timezone.utc)
            with patch("app.auction_reminders.smtplib.SMTP") as smtp_factory:
                self.assertEqual(send_due_auction_reminders(now=now), 1)
                self.assertEqual(send_due_auction_reminders(now=now), 0)
                smtp_factory.return_value.__enter__.return_value.starttls.assert_called_once()
                sent_message = (
                    smtp_factory.return_value.__enter__.return_value
                    .send_message.call_args.args[0]
                )
                self.assertEqual(sent_message["To"], "bidder@example.test")
                self.assertIn("subasta", sent_message["Subject"].lower())

            reminder = AuctionReminder.query.one()
            self.assertIsNotNone(reminder.sent_at)

    def test_upcoming_lots_are_visible_but_cannot_receive_bids(self):
        self.login()
        start = (datetime.now(timezone.utc) + timedelta(hours=30)).astimezone(
            ZoneInfo("America/Montevideo")
        )
        self.create_lot(
            "S-02",
            start_mode="scheduled",
            starts_at=start.strftime("%Y-%m-%dT%H:%M"),
        )
        with self.app.app_context():
            auction = Auction.query.one()
            auction_id = auction.id
            user = User(
                username="bidder",
                full_name="Bidder Example",
                email="bidder@example.test",
                phone="099123456",
                shipping_address="18 de Julio 1000",
                city="Montevideo",
                postal_code="11100",
            )
            user.set_password("safe-password")
            db.session.add(user)
            db.session.commit()
            user_id = user.id
        with self.client.session_transaction() as session:
            session["user_id"] = user_id

        self.assertIn(b"PR\xc3\x93XIMAMENTE", self.client.get("/subastas-activas").data)
        response = self.client.post(
            f"/subasta/{auction_id}/ofertar",
            data={"csrf_token": self.csrf_token(), "amount": "150"},
            follow_redirects=True,
        )
        self.assertIn("todavía no comenzó", response.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(Auction.query.one().current_price, 100)

    def test_bid_page_displays_the_latest_offer(self):
        self.login()
        self.create_lot("B-01")
        with self.app.app_context():
            auction = Auction.query.one()
            auction_id = auction.id
            user = User(
                username="bidder",
                full_name="Bidder Example",
                email="bidder@example.test",
                phone="099123456",
                shipping_address="18 de Julio 1000",
                city="Montevideo",
                postal_code="11100",
            )
            user.set_password("safe-password")
            db.session.add(user)
            db.session.commit()
            user_id = user.id
        with self.client.session_transaction() as session:
            session["user_id"] = user_id

        self.client.post(
            f"/subasta/{auction_id}/ofertar",
            data={"csrf_token": self.csrf_token(), "amount": "150"},
        )
        detail = self.client.get(f"/subasta/{auction_id}")
        self.assertIn(b"OFERTA ACTUAL", detail.data)
        self.assertIn(b"$U 150.00", detail.data)

    def test_account_shows_wins_and_records_pending_payment_including_commission(self):
        self.login()
        self.create_lot("P-01")
        with self.app.app_context():
            auction = Auction.query.one()
            auction_id = auction.id
            auction.closes_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            auction.current_price = 150
            user = User(
                username="winner",
                full_name="Winning Bidder",
                email="winner@example.test",
                phone="099123456",
                shipping_address="18 de Julio 1000",
                city="Montevideo",
                postal_code="11100",
            )
            user.set_password("safe-password")
            db.session.add(user)
            db.session.flush()
            db.session.add(Bid(amount=150, auction=auction, bidder=user))
            db.session.commit()
            user_id = user.id

        with self.client.session_transaction() as session:
            session["user_id"] = user_id

        dashboard = self.client.get("/cuenta")
        self.assertIn(b"Subastas que gan\xc3\xa9", dashboard.data)
        self.assertIn(b"Art\xc3\xadculo P-01", dashboard.data)
        self.assertIn(b"$U 506.25", dashboard.data)

        payment_page = self.client.get(f"/cuenta/subasta/{auction_id}/pagar")
        self.assertIn(b"Tarjeta de cr\xc3\xa9dito o d\xc3\xa9bito", payment_page.data)
        self.assertIn(b"Transferencia bancaria", payment_page.data)
        self.assertIn(b"MercadoPago", payment_page.data)
        self.assertIn(b"no procesa cargos", payment_page.data)

        response = self.client.post(
            f"/cuenta/subasta/{auction_id}/pagar",
            data={
                "csrf_token": self.csrf_token(),
                "method": "mercadopago",
            },
            follow_redirects=True,
        )
        self.assertIn("pendiente de confirmación", response.get_data(as_text=True))
        with self.app.app_context():
            payment = AuctionPayment.query.one()
            self.assertEqual(payment.method, "mercadopago")
            self.assertEqual(payment.status, "pending")
            self.assertEqual(payment.amount, Decimal("506.25"))

    def test_profile_is_required_to_bid_and_can_be_completed_from_account(self):
        self.login()
        self.create_lot("PROFILE-01")
        with self.app.app_context():
            auction = Auction.query.one()
            auction_id = auction.id
            user = User(username="incomplete", email="incomplete@example.test")
            user.set_password("safe-password")
            db.session.add(user)
            db.session.commit()
            user_id = user.id
        with self.client.session_transaction() as session:
            session["user_id"] = user_id

        response = self.client.post(
            f"/subasta/{auction_id}/ofertar",
            data={"csrf_token": self.csrf_token(), "amount": "150"},
            follow_redirects=True,
        )
        self.assertIn("Completá tus datos", response.get_data(as_text=True))
        self.assertIn("Dirección de envío", response.get_data(as_text=True))
        profile_response = self.client.post(
            "/cuenta/perfil",
            data={
                "csrf_token": self.csrf_token(),
                "full_name": "Complete Example",
                "email": "complete@example.test",
                "phone": "099123456",
                "shipping_address": "18 de Julio 1000",
                "city": "Montevideo",
                "postal_code": "11100",
            },
            follow_redirects=True,
        )
        self.assertIn("actualizaron correctamente", profile_response.get_data(as_text=True))
        with self.app.app_context():
            self.assertTrue(User.query.one().profile_complete)

    def test_registration_collects_shipping_profile(self):
        response = self.client.post(
            "/auth/registro",
            data={
                "csrf_token": self.csrf_token(),
                "username": "newuser",
                "full_name": "New User",
                "email": "new@example.test",
                "phone": "099123456",
                "shipping_address": "18 de Julio 1000",
                "city": "Montevideo",
                "postal_code": "11100",
                "password": "safe-password",
            },
            follow_redirects=True,
        )
        self.assertIn("Subastas que gané", response.get_data(as_text=True))
        with self.app.app_context():
            user = User.query.one()
            self.assertTrue(user.profile_complete)
            self.assertEqual(user.city, "Montevideo")


if __name__ == "__main__":
    unittest.main()
