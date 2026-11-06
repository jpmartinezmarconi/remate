from io import BytesIO
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app import create_app
from app.auction_reminders import (
    send_due_auction_closing_reminders,
    send_due_auction_outbid_notifications,
    send_due_auction_reminders,
)
from app.database import db
from routes.auction import minimum_bid_increment
from models.auction import Auction
from models.auction_closing_reminder import AuctionClosingReminder
from models.auction_favorite import AuctionFavorite
from models.auction_group import AuctionGroup
from models.auction_image import AuctionImage
from models.auction_outbid_notification import AuctionOutbidNotification
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
        self.bid_notification_patcher = patch(
            "routes.auction.send_business_notification"
        )
        self.bid_notification = self.bid_notification_patcher.start()
        self.outbid_notification_patcher = patch(
            "routes.auction.send_due_auction_outbid_notifications", return_value=0
        )
        self.outbid_notification_patcher.start()
        self.purchase_notification_patcher = patch(
            "routes.account.send_business_notification"
        )
        self.purchase_notification = self.purchase_notification_patcher.start()
        self.addCleanup(self.bid_notification_patcher.stop)
        self.addCleanup(self.outbid_notification_patcher.stop)
        self.addCleanup(self.purchase_notification_patcher.stop)
        self.app = create_app(PrivateAreaConfig)
        self.client = self.app.test_client()
        with self.app.app_context():
            db.drop_all()
            db.create_all()
        self.created_groups = {}
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

    def login_user(self, username="member"):
        with self.app.app_context():
            user = User(
                username=username,
                full_name="Test Member",
                email=f"{username}@example.test",
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
        return user_id

    def test_payment_page_handles_aware_and_naive_closing_dates(self):
        self.login()
        self.create_lot("PAY-TZ")
        winner_id = self.login_user("winner-tz")
        with self.app.app_context():
            auction = Auction.query.one()
            auction_id = auction.id
            auction.closes_at = datetime.now(timezone.utc) - timedelta(minutes=5)
            auction.current_price = 150
            db.session.add(Bid(amount=150, auction=auction, user_id=winner_id))
            db.session.commit()

        # SQLite removes tzinfo; reproduce the aware values returned by PostgreSQL.
        for aware in (False, True):
            for closed in (True, False):
                with self.subTest(aware=aware, closed=closed):
                    close_time = datetime.now(timezone.utc) + timedelta(
                        minutes=-5 if closed else 5
                    )
                    if aware:
                        close_time = close_time.astimezone(timezone(timedelta(hours=3)))
                    else:
                        close_time = close_time.replace(tzinfo=None)

                    def load_auction(model, identifier):
                        auction = db.session.get(model, identifier)
                        auction.closes_at = close_time
                        return auction

                    with patch.object(db, "get_or_404", side_effect=load_auction):
                        response = self.client.get(f"/cuenta/subasta/{auction_id}/pagar")
                    self.assertEqual(response.status_code, 200 if closed else 404)
                    if closed:
                        page = response.get_data(as_text=True)
                        self.assertIn("Transferencia bancaria BROU", page)
                        self.assertIn("Mi Dinero / Red Pagos", page)
                        self.assertIn("001901236", page)
                        self.assertIn("9102129", page)

    def test_navigation_links_follow_requested_order(self):
        response = self.client.get("/")
        page = response.get_data(as_text=True)
        self.assertIn("Funcionamiento del remate", page)
        self.assertIn("20% de comisión", page)
        self.assertIn("Incrementos de las pujas", page)
        self.assertIn("Hasta $U 500: de $U 50 en $U 50", page)
        self.assertIn("Más de $U 500 y hasta $U 2.000: de $U 100 en $U 100", page)
        self.assertIn("Más de $U 2.000 y hasta $U 10.000: de $U 500 en $U 500", page)
        self.assertIn("Más de $U 10.000: de $U 1.000 en $U 1.000", page)
        self.assertIn("Av. 8 de Octubre 4336/4328", page)
        labels = (
            "Inicio",
            "Ingresar",
            "Crear cuenta",
            "Subastas activas",
            "Próximas subastas",
            "Cómo funciona",
            "Contacto",
            "Área privada",
        )
        positions = [page.index(label) for label in labels]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('href="/proximas-subastas"', page)

    def test_home_hero_slider_links_to_multiple_auction_details(self):
        self.login()
        self.create_lot("SLIDE-01")
        self.create_lot("SLIDE-02")
        with self.app.app_context():
            auctions = Auction.query.order_by(Auction.id.asc()).all()
            auctions[0].image_url = "https://example.test/slide-01.jpg"
            auctions[1].image_url = "https://example.test/slide-02.jpg"
            auction_ids = [auction.id for auction in auctions]
            db.session.commit()

        page = self.client.get("/").get_data(as_text=True)

        self.assertIn('data-hero-slider', page)
        self.assertIn('data-hero-dot="0"', page)
        self.assertIn('data-hero-dot="1"', page)
        for auction_id in auction_ids:
            self.assertIn(f'href="/subasta/{auction_id}"', page)
        self.assertIn("home-slider.js", page)

    def create_lot(self, lot_number, *, featured=False, photos=None, **overrides):
        group_name = overrides.pop("group_name", "Colección")
        if group_name not in self.created_groups:
            self.client.post(
                "/area-privada/grupos",
                data={"csrf_token": self.csrf_token(), "name": group_name},
            )
            with self.app.app_context():
                self.created_groups[group_name] = AuctionGroup.query.filter_by(
                    name=group_name
                ).one().id
        data = {
            "csrf_token": self.csrf_token(),
            "title": f"Artículo {lot_number}",
            "description": "Descripción del artículo",
            "lot_number": lot_number,
            "group_id": str(self.created_groups[group_name]),
            "starting_price": "100.00",
            "commission_percent": "20",
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
        self.assertEqual(self.client.get("/area-privada/historial-pujas").status_code, 302)
        self.assertEqual(self.client.get("/area-privada/ventas").status_code, 302)
        self.assertEqual(
            self.client.post("/area-privada/ventas/enviar-correo-prueba").status_code,
            302,
        )
        self.assertEqual(self.client.get("/area-privada/clientes").status_code, 302)

        response = self.client.post(
            "/area-privada",
            data={"csrf_token": self.csrf_token(), "password": "incorrecta"},
            follow_redirects=True,
        )
        self.assertIn("no es correcta", response.get_data(as_text=True))

        response = self.login()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/area-privada/panel").status_code, 200)

    def test_private_customer_and_bid_history_show_client_details(self):
        self.login()
        self.create_lot("PRIVATE-PII-01")
        bidder_id = self.login_user()
        with self.app.app_context():
            auction = Auction.query.one()
            auction_id = auction.id
            db.session.add(
                Bid(amount=Decimal("125.50"), auction=auction, user_id=bidder_id)
            )
            db.session.commit()

        self.login()
        bid_history = self.client.get("/area-privada/historial-pujas")
        self.assertEqual(bid_history.status_code, 200)
        bid_page = bid_history.get_data(as_text=True)
        for value in (
            "PRIVATE-PII-01",
            "$U 125.50",
            "Test Member",
            "member@example.test",
            "099123456",
            "18 de Julio 1000",
            "Montevideo",
            "11100",
        ):
            self.assertIn(value, bid_page)
        self.assertIn(f"/subasta/{auction_id}", bid_page)

        customers = self.client.get("/area-privada/clientes")
        self.assertEqual(customers.status_code, 200)
        customer_page = customers.get_data(as_text=True)
        self.assertIn("Clientes registrados", customer_page)
        self.assertIn("member@example.test", customer_page)
        self.assertIn("Test Member", customer_page)
        self.assertIn("Código postal", customer_page)

    def test_private_sales_list_closed_auctions_with_winning_bids(self):
        self.login()
        self.create_lot("SOLD-01")
        self.create_lot("ACTIVE-01")
        self.create_lot("NO-BIDS-01")
        bidder_id = self.login_user()
        with self.app.app_context():
            auctions = {
                auction.lot_number: auction
                for auction in Auction.query.all()
            }
            other_bidder = User(
                username="saleschallenger",
                full_name="Sales Challenger",
                email="challenger@example.test",
                phone="099987654",
                shipping_address="18 de Julio 1000",
                city="Montevideo",
                postal_code="11100",
            )
            other_bidder.set_password("safe-password")
            db.session.add(other_bidder)
            db.session.flush()
            auctions["SOLD-01"].closes_at = datetime.now(timezone.utc) - timedelta(
                hours=1
            )
            auctions["ACTIVE-01"].current_price = Decimal("200")
            db.session.add_all(
                [
                    Bid(
                        amount=Decimal("150"),
                        auction=auctions["SOLD-01"],
                        user_id=bidder_id,
                    ),
                    Bid(
                        amount=Decimal("200"),
                        auction=auctions["SOLD-01"],
                        user_id=other_bidder.id,
                    ),
                    Bid(
                        amount=Decimal("150"),
                        auction=auctions["ACTIVE-01"],
                        user_id=bidder_id,
                    ),
                ]
            )
            db.session.commit()

        page = self.client.get("/area-privada/ventas")
        self.assertEqual(page.status_code, 200)
        content = page.get_data(as_text=True)
        self.assertIn("Ventas realizadas", content)
        self.assertIn("SOLD-01", content)
        self.assertIn("Sales Challenger", content)
        self.assertIn("challenger@example.test", content)
        self.assertIn("$U 200.00", content)
        self.assertNotIn("ACTIVE-01", content)
        self.assertNotIn("NO-BIDS-01", content)

    @patch("routes.private_area.smtplib.SMTP")
    def test_private_area_can_send_winner_email_preview(self, smtp):
        self.login()
        mail_server = smtp.return_value.__enter__.return_value

        response = self.client.post(
            "/area-privada/ventas/enviar-correo-prueba",
            data={"csrf_token": self.csrf_token()},
            follow_redirects=True,
        )

        self.assertIn("Correo de prueba enviado a inforemateonline@gmail.com", response.get_data(as_text=True))
        smtp.assert_called_once_with("smtp.example.test", 587, timeout=30)
        mail_server.starttls.assert_called_once()
        mail_server.login.assert_called_once_with(
            "sender@example.test", "test-smtp-password"
        )
        message = mail_server.send_message.call_args.args[0]
        self.assertEqual(message["To"], "inforemateonline@gmail.com")
        self.assertIn("Ganaste la subasta", message["Subject"])
        plain_body = message.get_body(preferencelist=("plain",)).get_content()
        self.assertIn("No se creó una subasta", plain_body)
        html_body = message.get_body(preferencelist=("html",)).get_content()
        self.assertIn("¡Ganaste la subasta!", html_body)
        self.assertIn("DEMO-001", html_body)
        self.assertIn("$U 1,800.00", html_body)

    @patch("routes.private_area.send_due_auction_outbid_notifications", return_value=4)
    def test_outbid_retry_requires_private_session_and_csrf(self, retry):
        response = self.client.post("/area-privada/ventas/reintentar-avisos", data={"csrf_token": self.csrf_token()})
        self.assertEqual(response.status_code, 302)
        retry.assert_not_called()
        self.login()
        response = self.client.post("/area-privada/ventas/reintentar-avisos", data={})
        self.assertEqual(response.status_code, 400)
        retry.assert_not_called()
        response = self.client.post(
            "/area-privada/ventas/reintentar-avisos",
            data={"csrf_token": self.csrf_token()}, follow_redirects=True,
        )
        self.assertIn("Avisos de puja superada enviados: 4", response.get_data(as_text=True))
        retry.assert_called_once_with()

    @patch("routes.private_area.smtplib.SMTP")
    def test_private_area_test_email_accepts_requested_recipient(self, smtp):
        self.login()
        response = self.client.post(
            "/area-privada/ventas/enviar-correo-prueba",
            data={"csrf_token": self.csrf_token(), "recipient": "recipient@example.test"},
            follow_redirects=True,
        )
        self.assertIn("Correo de prueba enviado a recipient@example.test", response.get_data(as_text=True))
        message = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
        self.assertEqual(message["To"], "recipient@example.test")

    @patch("routes.private_area.smtplib.SMTP_SSL")
    def test_private_area_can_test_gmail_direct_tls(self, smtp):
        self.login()
        self.app.config["SMTP_HOST"] = "smtp.gmail.com"
        response = self.client.post(
            "/area-privada/ventas/enviar-correo-prueba",
            data={"csrf_token": self.csrf_token(), "recipient": "recipient@example.test", "direct_tls": "1"},
            follow_redirects=True,
        )
        self.assertIn("Correo de prueba enviado", response.get_data(as_text=True))
        self.assertEqual(smtp.call_args.args, ("smtp.gmail.com", 465))
        server = smtp.return_value.__enter__.return_value
        server.starttls.assert_not_called()
        server.login.assert_called_once()
        server.send_message.assert_called_once()

    @patch("routes.private_area.smtplib.SMTP")
    def test_private_area_test_email_rejects_multiple_recipients(self, smtp):
        self.login()
        response = self.client.post(
            "/area-privada/ventas/enviar-correo-prueba",
            data={"csrf_token": self.csrf_token(), "recipient": "a@example.test,b@example.test"},
            follow_redirects=True,
        )
        self.assertIn("Ingresá una dirección de correo válida", response.get_data(as_text=True))
        smtp.assert_not_called()

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
            self.assertEqual(str(auction.commission_percent), "20.00")
            self.assertEqual(len(auction.photos), 6)
            self.assertEqual(image.content_type, "image/png")

        home = self.client.get("/")
        self.assertIn(b"Art\xc3\xadculo U-01", home.data)
        self.assertIn(b"3 unidades", home.data)
        active = self.client.get("/subastas-activas")
        self.assertIn(b"Colecci\xc3\xb3n", active.data)
        detail = self.client.get(f"/subasta/{auction_id}")
        self.assertIn(b"el ganador se adjudica toda la cantidad", detail.data)
        self.assertIn(b'data-photo-lightbox aria-label="Vista ampliada', detail.data)
        self.assertEqual(detail.data.count(b'data-lightbox-image='), 6)
        self.assertIn(b'data-lightbox-previous', detail.data)
        self.assertIn(b'data-lightbox-next', detail.data)
        self.assertIn(b'photo-lightbox.js', detail.data)
        image_response = self.client.get(f"/area-privada/fotos/{image_id}")
        self.assertEqual(image_response.status_code, 200)
        self.assertEqual(image_response.mimetype, "image/png")

    def test_creates_groups_separately_and_assigns_lots_to_them(self):
        self.login()
        response = self.client.post(
            "/area-privada/grupos",
            data={"csrf_token": self.csrf_token(), "name": "Remate de junio"},
            follow_redirects=True,
        )
        self.assertIn("Se creó el grupo", response.get_data(as_text=True))
        with self.app.app_context():
            group = AuctionGroup.query.filter_by(name="Remate de junio").one()
            group_id = group.id

        self.client.post(
            "/area-privada/lotes",
            data={
                "csrf_token": self.csrf_token(),
                "title": "Lote de prueba",
                "description": "Descripción",
                "lot_number": "J-01",
                "group_id": str(group_id),
                "starting_price": "100",
                "commission_percent": "20",
                "quantity": "1",
                "sale_mode": "lot",
                "start_mode": "now",
                "duration_hours": "48",
            },
            follow_redirects=True,
        )
        with self.app.app_context():
            auction = Auction.query.one()
            self.assertEqual(auction.group_id, group_id)
            self.assertEqual(auction.group_name, "Remate de junio")
            self.assertEqual(auction.closes_at - auction.starts_at, timedelta(hours=48))

    def test_new_lot_form_defaults_commission_to_twenty_percent(self):
        self.login()
        dashboard = self.client.get("/area-privada/panel").get_data(as_text=True)
        self.assertIn('id="commission" name="commission_percent"', dashboard)
        self.assertIn('value="20" required', dashboard)
        self.create_lot("COM-20")
        with self.app.app_context():
            auction = Auction.query.one()
            self.assertEqual(auction.commission_percent, Decimal("20.00"))

    def test_edits_an_existing_lot_and_saves_its_fields_and_photos(self):
        self.login()
        self.create_lot(
            "EDIT-01",
            photos=[(BytesIO(b"\x89PNG\r\n\x1a\nold"), "old.png")],
        )
        with self.app.app_context():
            auction = Auction.query.one()
            auction.starts_at = auction.starts_at.replace(second=37, microsecond=123456)
            auction.closes_at = auction.closes_at.replace(second=37, microsecond=123456)
            db.session.commit()
            auction = db.session.get(Auction, auction.id)
            auction_id = auction.id
            group_id = auction.group_id
            old_photo_id = auction.photos[0].id
            original_starts_at = auction.starts_at
            original_closes_at = auction.closes_at
            starts_at = auction.starts_at_montevideo.strftime("%Y-%m-%dT%H:%M")
            closes_at = auction.closes_at_montevideo.strftime("%Y-%m-%dT%H:%M")

        edit_url = f"/area-privada/lotes/{auction_id}/editar"
        edit_page = self.client.get(edit_url)
        self.assertEqual(edit_page.status_code, 200)
        self.assertIn(b"Guardar cambios", edit_page.data)
        dashboard = self.client.get("/area-privada/panel")
        self.assertIn(edit_url.encode(), dashboard.data)

        response = self.client.post(
            edit_url,
            data={
                "csrf_token": self.csrf_token(),
                "title": "Artículo actualizado",
                "description": "Descripción corregida",
                "lot_number": "EDIT-02",
                "group_id": str(group_id),
                "starting_price": "125.50",
                "commission_percent": "15",
                "quantity": "4",
                "sale_mode": "lot",
                "starts_at": starts_at,
                "closes_at": closes_at,
                "remove_photo_ids": str(old_photo_id),
                "photos": (BytesIO(b"\x89PNG\r\n\x1a\nnew"), "new.png"),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertIn("se actualizó correctamente", response.get_data(as_text=True))

        with self.app.app_context():
            auction = db.session.get(Auction, auction_id)
            self.assertEqual(auction.title, "Artículo actualizado")
            self.assertEqual(auction.description, "Descripción corregida")
            self.assertEqual(auction.lot_number, "EDIT-02")
            self.assertEqual(auction.starting_price, Decimal("125.50"))
            self.assertEqual(auction.current_price, Decimal("125.50"))
            self.assertEqual(auction.commission_percent, Decimal("15.00"))
            self.assertEqual(auction.quantity, 4)
            self.assertEqual(auction.sale_mode, "lot")
            self.assertEqual(auction.starts_at, original_starts_at)
            self.assertEqual(auction.closes_at, original_closes_at)
            self.assertEqual(len(auction.photos), 1)
            self.assertEqual(auction.photos[0].filename, "new.png")

    def test_editing_lot_dates_is_explicit_and_updates_countdown(self):
        self.login()
        self.create_lot("EDIT-TIME")
        with self.app.app_context():
            auction = Auction.query.one()
            auction_id = auction.id
            group_id = auction.group_id
            new_start = (datetime.now(timezone.utc) + timedelta(days=2)).astimezone(
                ZoneInfo("America/Montevideo")
            )
            new_close = new_start + timedelta(hours=3)

        response = self.client.post(
            f"/area-privada/lotes/{auction_id}/editar",
            data={
                "csrf_token": self.csrf_token(),
                "title": "Artículo actualizado",
                "description": "Descripción corregida",
                "lot_number": "EDIT-TIME",
                "group_id": str(group_id),
                "starting_price": "100",
                "commission_percent": "20",
                "quantity": "3",
                "sale_mode": "units",
                "starts_at": new_start.strftime("%Y-%m-%dT%H:%M"),
                "closes_at": new_close.strftime("%Y-%m-%dT%H:%M"),
            },
            follow_redirects=True,
        )
        self.assertIn("se actualizó correctamente", response.get_data(as_text=True))

        with self.app.app_context():
            auction = db.session.get(Auction, auction_id)
            self.assertEqual(
                auction.starts_at,
                new_start.astimezone(timezone.utc).replace(
                    second=0, microsecond=0, tzinfo=None
                ),
            )
            self.assertEqual(
                auction.closes_at,
                new_close.astimezone(timezone.utc).replace(
                    second=0, microsecond=0, tzinfo=None
                ),
            )

    def test_editing_a_lot_with_bids_preserves_auction_terms(self):
        self.login()
        self.create_lot("LOCKED-01")
        user_id = self.login_user()
        with self.app.app_context():
            auction = Auction.query.one()
            auction_id = auction.id
            group_id = auction.group_id
            starts_at = auction.starts_at
            closes_at = auction.closes_at
            db.session.add(
                Bid(amount=Decimal("150.00"), auction=auction, user_id=user_id)
            )
            auction.current_price = Decimal("150.00")
            db.session.commit()

        edit_url = f"/area-privada/lotes/{auction_id}/editar"
        edit_page = self.client.get(edit_url)
        self.assertIn(b"tiene pujas o pagos registrados", edit_page.data)
        response = self.client.post(
            edit_url,
            data={
                "csrf_token": self.csrf_token(),
                "title": "Artículo corregido",
                "description": "Descripción corregida",
                "lot_number": "ALTERADO",
                "group_id": str(group_id),
                "starting_price": "1",
                "commission_percent": "99",
                "quantity": "100",
                "sale_mode": "lot",
            },
            follow_redirects=True,
        )
        self.assertIn("se actualizó correctamente", response.get_data(as_text=True))

        with self.app.app_context():
            auction = db.session.get(Auction, auction_id)
            self.assertEqual(auction.title, "Artículo corregido")
            self.assertEqual(auction.description, "Descripción corregida")
            self.assertEqual(auction.lot_number, "LOCKED-01")
            self.assertEqual(auction.starting_price, Decimal("100.00"))
            self.assertEqual(auction.current_price, Decimal("150.00"))
            self.assertEqual(auction.commission_percent, Decimal("20.00"))
            self.assertEqual(auction.quantity, 3)
            self.assertEqual(auction.sale_mode, "units")
            self.assertEqual(auction.starts_at, starts_at)
            self.assertEqual(auction.closes_at, closes_at)

    def test_finished_lot_can_be_relaunched_without_losing_previous_bids(self):
        self.login()
        self.create_lot("RELIST-01")
        user_id = self.login_user()
        with self.app.app_context():
            previous = Auction.query.one()
            previous_id = previous.id
            previous.starts_at = datetime.now(timezone.utc) - timedelta(days=2)
            previous.closes_at = datetime.now(timezone.utc) - timedelta(days=1)
            previous.current_price = Decimal("150.00")
            db.session.add(
                Bid(amount=Decimal("150.00"), auction=previous, user_id=user_id)
            )
            db.session.commit()

        edit_url = f"/area-privada/lotes/{previous_id}/editar"
        self.assertIn(
            b"Publicar este art\xc3\xadculo en un nuevo remate",
            self.client.get(edit_url).data,
        )
        self.assertIn(b"Publicar pr\xc3\xb3ximamente", self.client.get(edit_url).data)
        starts_at = (datetime.now(timezone.utc) + timedelta(days=1)).astimezone(
            ZoneInfo("America/Montevideo")
        )
        response = self.client.post(
            edit_url,
            data={
                "csrf_token": self.csrf_token(),
                "action": "relaunch",
                "title": "Artículo relanzado",
                "description": "Nueva descripción del artículo",
                "lot_number": "RELIST-02",
                "group_id": str(self.created_groups["Colección"]),
                "starting_price": "200",
                "commission_percent": "20",
                "quantity": "2",
                "sale_mode": "lot",
                "start_mode": "scheduled",
                "starts_at": starts_at.strftime("%Y-%m-%dT%H:%M"),
                "duration_hours": "24",
            },
            follow_redirects=True,
        )
        self.assertIn("se publicó nuevamente", response.get_data(as_text=True))

        with self.app.app_context():
            previous = db.session.get(Auction, previous_id)
            relaunch = Auction.query.filter_by(lot_number="RELIST-02").one()
            self.assertEqual(previous.title, "Artículo RELIST-01")
            self.assertEqual(previous.bid_count, 1)
            self.assertEqual(previous.current_price, Decimal("150.00"))
            self.assertEqual(relaunch.title, "Artículo relanzado")
            self.assertEqual(relaunch.description, "Nueva descripción del artículo")
            self.assertEqual(relaunch.starting_price, Decimal("200.00"))
            self.assertEqual(relaunch.current_price, Decimal("200.00"))
            self.assertEqual(relaunch.bid_count, 0)
            self.assertTrue(relaunch.is_upcoming)
            self.assertEqual(
                relaunch.closes_at - relaunch.starts_at, timedelta(hours=24)
            )

    def test_finished_lot_can_be_relaunched_immediately(self):
        self.login()
        self.create_lot("RELIST-NOW-01")
        user_id = self.login_user()
        with self.app.app_context():
            previous = Auction.query.one()
            previous_id = previous.id
            previous.starts_at = datetime.now(timezone.utc) - timedelta(days=2)
            previous.closes_at = datetime.now(timezone.utc) - timedelta(days=1)
            db.session.add(
                Bid(amount=Decimal("150.00"), auction=previous, user_id=user_id)
            )
            db.session.commit()

        response = self.client.post(
            f"/area-privada/lotes/{previous_id}/editar",
            data={
                "csrf_token": self.csrf_token(),
                "action": "relaunch",
                "title": "Artículo disponible ahora",
                "description": "Descripción del artículo",
                "lot_number": "RELIST-NOW-02",
                "group_id": str(self.created_groups["Colección"]),
                "starting_price": "200",
                "commission_percent": "20",
                "quantity": "1",
                "sale_mode": "lot",
                "start_mode": "now",
                "duration_hours": "24",
            },
            follow_redirects=True,
        )
        self.assertIn("se publicó nuevamente", response.get_data(as_text=True))
        with self.app.app_context():
            relaunch = Auction.query.filter_by(lot_number="RELIST-NOW-02").one()
            self.assertTrue(relaunch.is_active)
            self.assertFalse(relaunch.is_upcoming)
            self.assertEqual(
                relaunch.closes_at - relaunch.starts_at, timedelta(hours=24)
            )

    def test_duration_is_whole_hours_and_cannot_exceed_seven_days(self):
        self.login()
        invalid = self.create_lot("D-169", duration_hours="169")
        self.assertIn("entre 1 y 168 horas", invalid.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(Auction.query.count(), 0)

        self.create_lot("D-168", duration_hours="168")
        with self.app.app_context():
            auction = Auction.query.one()
            self.assertEqual(auction.closes_at - auction.starts_at, timedelta(days=7))

    def test_can_delete_selected_lots_and_then_the_entire_empty_group(self):
        self.login()
        self.create_lot("DEL-01")
        self.create_lot("DEL-02")
        self.create_lot("DEL-03")
        group_id = self.created_groups["Colección"]

        response = self.client.post(
            f"/area-privada/grupos/{group_id}/lotes/eliminar",
            data={
                "csrf_token": self.csrf_token(),
                "auction_ids": ["1", "2"],
            },
            follow_redirects=True,
        )
        self.assertIn("Se eliminaron 2 lote(s)", response.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(Auction.query.count(), 1)

        response = self.client.post(
            f"/area-privada/grupos/{group_id}/eliminar",
            data={"csrf_token": self.csrf_token()},
            follow_redirects=True,
        )
        self.assertIn("Se eliminó el grupo", response.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(Auction.query.count(), 0)
            self.assertEqual(AuctionGroup.query.count(), 0)

    def test_group_and_lot_deletion_preserve_lots_with_bids(self):
        self.login()
        self.create_lot("KEEP-01")
        group_id = self.created_groups["Colección"]
        with self.app.app_context():
            auction = Auction.query.one()
            auction_id = auction.id
            bidder = User(username="bidder", email="bidder@example.test")
            bidder.set_password("safe-password")
            db.session.add(bidder)
            db.session.flush()
            db.session.add(Bid(amount=150, auction=auction, bidder=bidder))
            db.session.commit()

        response = self.client.post(
            f"/area-privada/grupos/{group_id}/lotes/eliminar",
            data={"csrf_token": self.csrf_token(), "auction_ids": [str(auction_id)]},
            follow_redirects=True,
        )
        self.assertIn("no se pueden eliminar lotes", response.get_data(as_text=True).lower())
        response = self.client.post(
            f"/area-privada/grupos/{group_id}/eliminar",
            data={"csrf_token": self.csrf_token()},
            follow_redirects=True,
        )
        self.assertIn("no se pueden eliminar lotes", response.get_data(as_text=True).lower())
        with self.app.app_context():
            self.assertEqual(Auction.query.count(), 1)
            self.assertEqual(Bid.query.count(), 1)

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

    def test_active_upcoming_and_sold_lots_are_separated(self):
        self.login()
        self.create_lot("LIVE-01")
        upcoming_start = (datetime.now(timezone.utc) + timedelta(hours=25)).astimezone(
            ZoneInfo("America/Montevideo")
        )
        self.create_lot(
            "FUTURE-01",
            start_mode="scheduled",
            starts_at=upcoming_start.strftime("%Y-%m-%dT%H:%M"),
        )
        self.create_lot("SOLD-01")
        self.create_lot("ENDED-01")

        with self.app.app_context():
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            sold = Auction.query.filter_by(lot_number="SOLD-01").one()
            sold.starts_at = now - timedelta(hours=1)
            sold.closes_at = now - timedelta(minutes=5)
            ended_without_bids = Auction.query.filter_by(lot_number="ENDED-01").one()
            ended_without_bids.starts_at = now - timedelta(hours=2)
            ended_without_bids.closes_at = now - timedelta(hours=1)
            bidder = User(
                username="soldwinner",
                full_name="Sold Winner",
                email="soldwinner@example.test",
                phone="099123456",
                shipping_address="18 de Julio 1000",
                city="Montevideo",
                postal_code="11100",
            )
            bidder.set_password("safe-password")
            db.session.add(bidder)
            db.session.flush()
            db.session.add(Bid(amount=Decimal("150"), auction=sold, bidder=bidder))
            db.session.commit()

        active_page = self.client.get("/subastas-activas").get_data(as_text=True)
        upcoming_page = self.client.get("/proximas-subastas").get_data(as_text=True)

        self.assertIn("Artículo LIVE-01", active_page)
        self.assertIn("data-auction-countdown", active_page)
        self.assertNotIn("Artículo FUTURE-01", active_page)
        self.assertIn("Artículo SOLD-01", active_page)
        self.assertIn("SUBASTADO", active_page)
        self.assertNotIn("Artículo ENDED-01", active_page)
        self.assertIn("Artículo FUTURE-01", upcoming_page)
        self.assertNotIn("Artículo LIVE-01", upcoming_page)
        self.assertNotIn("Artículo SOLD-01", upcoming_page)
        self.assertEqual(
            self.client.get("/articulos-en-remate").status_code,
            200,
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

        self.assertIn(b"PR\xc3\x93XIMAMENTE", self.client.get("/proximas-subastas").data)
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
            other_bidder = User(
                username="otherbidder",
                full_name="Other Bidder",
                email="otherbidder@example.test",
                phone="099123456",
                shipping_address="18 de Julio 1000",
                city="Montevideo",
                postal_code="11100",
            )
            other_bidder.set_password("safe-password")
            db.session.add(other_bidder)
            db.session.commit()
            user_id = user.id
            other_bidder_id = other_bidder.id
        with self.client.session_transaction() as session:
            session["user_id"] = user_id

        too_low = self.client.post(
            f"/subasta/{auction_id}/ofertar",
            data={"csrf_token": self.csrf_token(), "amount": "99"},
            follow_redirects=True,
        )
        self.assertIn(
            "primera oferta no puede ser menor", too_low.get_data(as_text=True)
        )
        self.client.post(
            f"/subasta/{auction_id}/ofertar",
            data={"csrf_token": self.csrf_token(), "amount": "100"},
        )
        with self.app.app_context():
            first_bid_id = Bid.query.one().id
        with self.client.session_transaction() as session:
            session["user_id"] = other_bidder_id
        offer_page = self.client.get(f"/subasta/{auction_id}").get_data(as_text=True)
        self.assertIn("Ofertar $U 150.00", offer_page)
        self.assertIn('class="btn btn-auction btn-lg rounded-pill w-100 mt-3" type="submit">Ofertar', offer_page)
        self.assertNotIn('name="amount"', offer_page)
        stale = self.client.post(
            f"/subasta/{auction_id}/ofertar",
            data={"csrf_token": self.csrf_token(), "amount": "149"},
            follow_redirects=True,
        )
        self.assertIn("La oferta cambió", stale.get_data(as_text=True))
        self.client.post(
            f"/subasta/{auction_id}/ofertar",
            data={"csrf_token": self.csrf_token(), "expected_bid_id": str(first_bid_id), "amount": "9999"},
        )
        self.assertEqual(self.bid_notification.call_count, 2)
        self.assertIn("Oferta: $U 150.00", self.bid_notification.call_args.args[1])
        with self.client.session_transaction() as session:
            session["user_id"] = user_id
        detail = self.client.get(f"/subasta/{auction_id}")
        self.assertIn(b"OFERTA ACTUAL", detail.data)
        self.assertIn(b"$U 150.00", detail.data)
        self.assertIn(b"Ofertar $U 200.00", detail.data)
        self.assertIn(b"data-auction-countdown", detail.data)
        self.assertIn(b"data-bid-form", detail.data)
        self.assertIn(b"auction-countdown.js", detail.data)

    def test_automatic_bid_rejects_outdated_bid_and_applies_tiers(self):
        self.login()
        self.create_lot("AUTO-TIERS")
        with self.app.app_context():
            auction_id = Auction.query.one().id
        first_id = self.login_user("tier-first")
        second_id = self.login_user("tier-second")
        for price, increment in ((Decimal("499.99"), Decimal("50")),
                                 (Decimal("500"), Decimal("50")),
                                 (Decimal("500.01"), Decimal("100")),
                                 (Decimal("2000"), Decimal("100")),
                                 (Decimal("2000.01"), Decimal("500")),
                                 (Decimal("10000"), Decimal("500")),
                                 (Decimal("10000.01"), Decimal("1000"))):
            with self.subTest(price=price):
                with self.app.app_context():
                    AuctionOutbidNotification.query.delete()
                    Bid.query.delete()
                    auction = db.session.get(Auction, auction_id)
                    auction.current_price = price
                    old_bid = Bid(amount=price, auction=auction, user_id=first_id)
                    db.session.add(old_bid)
                    db.session.commit()
                    old_bid_id = old_bid.id
                with self.client.session_transaction() as session:
                    session["user_id"] = second_id
                response = self.client.post(
                    f"/subasta/{auction_id}/ofertar",
                    data={"csrf_token": self.csrf_token(), "expected_bid_id": str(old_bid_id)},
                    follow_redirects=True,
                )
                self.assertIn("Oferta registrada", response.get_data(as_text=True))
                with self.app.app_context():
                    self.assertEqual(db.session.get(Auction, auction_id).current_price, price + increment)
                    self.assertEqual(AuctionOutbidNotification.query.count(), 1)
                with self.client.session_transaction() as session:
                    session["user_id"] = first_id
                response = self.client.post(
                    f"/subasta/{auction_id}/ofertar",
                    data={"csrf_token": self.csrf_token(), "expected_bid_id": str(old_bid_id)},
                    follow_redirects=True,
                )
                self.assertIn("La oferta cambió", response.get_data(as_text=True))
                with self.app.app_context():
                    self.assertEqual(Bid.query.count(), 2)

    def test_automatic_bid_shows_unit_total_and_limits_maximum_amount(self):
        self.login()
        self.create_lot("AUTO-UNIT")
        with self.app.app_context():
            auction = Auction.query.one()
            auction_id = auction.id
            auction.current_price = Decimal("9999999999.99")
            old_user = User(username="auto-old", email="auto-old@example.test", password_hash="x")
            db.session.add(old_user)
            db.session.flush()
            db.session.add(Bid(amount=auction.current_price, auction=auction, user_id=old_user.id))
            db.session.commit()
            bid_id = Bid.query.one().id
        self.login_user("auto-new")
        page = self.client.get(f"/subasta/{auction_id}").get_data(as_text=True)
        self.assertIn("por unidad", page)
        self.assertIn("Total de la oferta por 3 unidades", page)
        response = self.client.post(
            f"/subasta/{auction_id}/ofertar",
            data={"csrf_token": self.csrf_token(), "expected_bid_id": str(bid_id)},
            follow_redirects=True,
        )
        self.assertIn("importe máximo permitido", response.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(Bid.query.count(), 1)

    def test_bid_succeeds_when_business_notification_fails(self):
        self.login()
        self.create_lot("MAIL-01")
        with self.app.app_context():
            auction_id = Auction.query.one().id
        self.login_user()
        self.bid_notification.side_effect = RuntimeError("SMTP is unavailable")

        response = self.client.post(
            f"/subasta/{auction_id}/ofertar",
            data={"csrf_token": self.csrf_token(), "amount": "100"},
            follow_redirects=True,
        )

        self.assertIn("¡Oferta registrada!", response.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(Bid.query.count(), 1)

    def test_first_bid_can_exceed_base_by_any_amount(self):
        self.login()
        self.create_lot("B-FIRST-01")
        self.login_user()
        with self.app.app_context():
            auction_id = Auction.query.one().id
        response = self.client.post(
            f"/subasta/{auction_id}/ofertar",
            data={"csrf_token": self.csrf_token(), "amount": "123.45"},
            follow_redirects=True,
        )
        self.assertIn("Oferta registrada", response.get_data(as_text=True))
        with self.app.app_context():
            auction = db.session.get(Auction, auction_id)
            self.assertEqual(auction.current_price, Decimal("123.45"))
            self.assertEqual(auction.bid_count, 1)

    def test_outbid_bidder_receives_one_email_with_replacement_offer(self):
        self.login()
        self.create_lot("OUTBID-01")
        with self.app.app_context():
            auction_id = Auction.query.one().id
            bidders = [
                User(
                    username=f"outbidder{index}",
                    full_name=f"Outbidder {index}",
                    email=f"outbidder{index}@example.test",
                    phone="099123456",
                    shipping_address="18 de Julio 1000",
                    city="Montevideo",
                    postal_code="11100",
                )
                for index in range(2)
            ]
            for bidder in bidders:
                bidder.set_password("safe-password")
            db.session.add_all(bidders)
            db.session.commit()
            bidder_ids = [bidder.id for bidder in bidders]

        with self.client.session_transaction() as session:
            session["user_id"] = bidder_ids[0]
        self.client.post(
            f"/subasta/{auction_id}/ofertar",
            data={"csrf_token": self.csrf_token(), "amount": "150"},
        )
        with self.app.app_context():
            first_bid_id = Bid.query.one().id
        with self.client.session_transaction() as session:
            session["user_id"] = bidder_ids[1]
        self.client.post(
            f"/subasta/{auction_id}/ofertar",
            data={"csrf_token": self.csrf_token(), "expected_bid_id": str(first_bid_id)},
        )

        with self.app.app_context():
            notification = AuctionOutbidNotification.query.one()
            self.assertEqual(notification.outbid_bid.bidder.id, bidder_ids[0])
            self.assertEqual(notification.replacement_bid.amount, Decimal("200.00"))
            self.assertIsNone(notification.sent_at)

            with patch("app.auction_reminders.smtplib.SMTP") as smtp_factory:
                mail_server = smtp_factory.return_value.__enter__.return_value
                self.assertEqual(send_due_auction_outbid_notifications(), 1)
                self.assertEqual(send_due_auction_outbid_notifications(), 0)
                self.assertEqual(mail_server.send_message.call_count, 1)
                message = mail_server.send_message.call_args.args[0]
                self.assertEqual(message["To"], "outbidder0@example.test")
                self.assertIn("Superaron tu oferta", message["Subject"])
                self.assertIn("$U 150.00", message.get_content())
                self.assertIn("$U 200.00", message.get_content())
                self.assertIn(f"/subasta/{auction_id}", message.get_content())

            self.assertIsNotNone(notification.sent_at)

    def test_outbid_email_is_attempted_immediately_and_retried_if_smtp_fails(self):
        self.login()
        self.create_lot("IMMEDIATE-MAIL")
        first_id = self.login_user("immediate-first")
        second_id = self.login_user("immediate-second")
        with self.app.app_context():
            auction_id = Auction.query.one().id
        with self.client.session_transaction() as session:
            session["user_id"] = first_id
        self.client.post(
            f"/subasta/{auction_id}/ofertar",
            data={"csrf_token": self.csrf_token(), "amount": "150"},
        )
        with self.app.app_context():
            first_bid_id = Bid.query.one().id
        with self.client.session_transaction() as session:
            session["user_id"] = second_id

        with patch(
            "routes.auction.send_due_auction_outbid_notifications",
            wraps=send_due_auction_outbid_notifications,
        ) as send_outbid, patch("app.auction_reminders.smtplib.SMTP") as smtp:
            mail = smtp.return_value.__enter__.return_value
            mail.send_message.side_effect = OSError("temporary SMTP failure")
            response = self.client.post(
                f"/subasta/{auction_id}/ofertar",
                data={"csrf_token": self.csrf_token(), "expected_bid_id": str(first_bid_id)},
                follow_redirects=True,
            )
            self.assertIn("Oferta registrada", response.get_data(as_text=True))
            send_outbid.assert_called_once()
            with self.app.app_context():
                notification = AuctionOutbidNotification.query.one()
                self.assertIsNone(notification.sent_at)
                self.assertEqual(Bid.query.count(), 2)
                mail.send_message.side_effect = None
                self.assertEqual(send_due_auction_outbid_notifications(), 1)
                self.assertEqual(send_due_auction_outbid_notifications(), 0)
                self.assertIsNotNone(db.session.get(AuctionOutbidNotification, notification.id).sent_at)
                self.assertEqual(mail.send_message.call_args.args[0]["To"], "immediate-first@example.test")

    def test_outbid_email_is_sent_immediately_after_bid(self):
        self.login()
        self.create_lot("IMMEDIATE-SUCCESS")
        first_id = self.login_user("instant-first")
        second_id = self.login_user("instant-second")
        with self.app.app_context():
            auction_id = Auction.query.one().id
        with self.client.session_transaction() as session:
            session["user_id"] = first_id
        self.client.post(
            f"/subasta/{auction_id}/ofertar",
            data={"csrf_token": self.csrf_token(), "amount": "150"},
        )
        with self.app.app_context():
            first_bid_id = Bid.query.one().id
        with self.client.session_transaction() as session:
            session["user_id"] = second_id
        with patch(
            "routes.auction.send_due_auction_outbid_notifications",
            wraps=send_due_auction_outbid_notifications,
        ), patch("app.auction_reminders.smtplib.SMTP") as smtp:
            response = self.client.post(
                f"/subasta/{auction_id}/ofertar",
                data={"csrf_token": self.csrf_token(), "expected_bid_id": str(first_bid_id)},
                follow_redirects=True,
            )
            self.assertIn("Oferta registrada", response.get_data(as_text=True))
            message = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
            self.assertEqual(message["To"], "instant-first@example.test")
            self.assertIn("$U 200.00", message.get_content())
        with self.app.app_context():
            self.assertIsNotNone(AuctionOutbidNotification.query.one().sent_at)

    def test_bidder_cannot_bid_again_until_another_user_outbids_them(self):
        self.login()
        self.create_lot("SELF-BID-01")
        with self.app.app_context():
            auction_id = Auction.query.one().id
            bidders = [
                User(
                    username=username,
                    full_name=username,
                    email=f"{username}@example.test",
                    phone="099123456",
                    shipping_address="18 de Julio 1000",
                    city="Montevideo",
                    postal_code="11100",
                )
                for username in ("selfbidder", "challenger")
            ]
            for bidder in bidders:
                bidder.set_password("safe-password")
            db.session.add_all(bidders)
            db.session.commit()
            bidder_ids = [bidder.id for bidder in bidders]
        with self.client.session_transaction() as session:
            session["user_id"] = bidder_ids[0]

        self.client.post(
            f"/subasta/{auction_id}/ofertar",
            data={"csrf_token": self.csrf_token(), "amount": "150"},
        )
        with self.app.app_context():
            first_bid_id = Bid.query.one().id
        blocked_page = self.client.get(f"/subasta/{auction_id}")
        self.assertIn(b"Tu oferta es la m\xc3\xa1s alta", blocked_page.data)
        self.assertNotIn(b"data-bid-form", blocked_page.data)

        blocked_bid = self.client.post(
            f"/subasta/{auction_id}/ofertar",
            data={"csrf_token": self.csrf_token(), "amount": "200"},
            follow_redirects=True,
        )
        self.assertIn(
            "Podés volver a ofertar cuando otro participante la supere",
            blocked_bid.get_data(as_text=True),
        )
        with self.app.app_context():
            self.assertEqual(Bid.query.count(), 1)

        with self.client.session_transaction() as session:
            session["user_id"] = bidder_ids[1]
        self.client.post(
            f"/subasta/{auction_id}/ofertar",
            data={"csrf_token": self.csrf_token(), "expected_bid_id": str(first_bid_id)},
        )
        with self.app.app_context():
            second_bid_id = Bid.query.order_by(Bid.id.desc()).first().id
        with self.client.session_transaction() as session:
            session["user_id"] = bidder_ids[0]
        allowed_bid = self.client.post(
            f"/subasta/{auction_id}/ofertar",
            data={"csrf_token": self.csrf_token(), "expected_bid_id": str(second_bid_id)},
            follow_redirects=True,
        )
        self.assertIn("¡Oferta registrada!", allowed_bid.get_data(as_text=True))

        with self.app.app_context():
            self.assertEqual(Bid.query.count(), 3)
            self.assertEqual(AuctionOutbidNotification.query.count(), 2)

    def test_bid_increment_tiers_follow_current_price_thresholds(self):
        self.assertEqual(minimum_bid_increment(Decimal("500")), Decimal("50"))
        self.assertEqual(minimum_bid_increment(Decimal("500.01")), Decimal("100"))
        self.assertEqual(minimum_bid_increment(Decimal("2000")), Decimal("100"))
        self.assertEqual(minimum_bid_increment(Decimal("2000.01")), Decimal("500"))
        self.assertEqual(minimum_bid_increment(Decimal("10000")), Decimal("500"))
        self.assertEqual(minimum_bid_increment(Decimal("10000.01")), Decimal("1000"))

    def test_registered_user_can_toggle_favorites_and_see_them_on_home(self):
        self.login()
        self.create_lot("FAV-01")
        with self.app.app_context():
            auction_id = Auction.query.one().id
        user_id = self.login_user()

        response = self.client.post(
            f"/subasta/{auction_id}/favorito",
            data={
                "csrf_token": self.csrf_token(),
                "return_to": "/",
            },
            follow_redirects=True,
        )
        page = response.get_data(as_text=True)
        self.assertIn("Tus artículos favoritos", page)
        self.assertIn("Artículo FAV-01", page)
        with self.app.app_context():
            self.assertEqual(
                AuctionFavorite.query.filter_by(
                    user_id=user_id, auction_id=auction_id
                ).count(),
                1,
            )

        self.client.post(
            f"/subasta/{auction_id}/favorito",
            data={
                "csrf_token": self.csrf_token(),
                "return_to": "/",
            },
        )
        with self.app.app_context():
            self.assertEqual(AuctionFavorite.query.count(), 0)

    def test_home_shows_eight_most_recently_viewed_articles_from_browser_session(self):
        self.login()
        for index in range(9):
            self.create_lot(f"VIEW-{index}")
        with self.app.app_context():
            auction_ids = [
                auction.id
                for auction in Auction.query.order_by(Auction.id.asc()).all()
            ]

        for auction_id in auction_ids:
            self.client.get(f"/subasta/{auction_id}")

        page = self.client.get("/").get_data(as_text=True)
        self.assertIn("Últimos artículos vistos", page)
        self.assertNotIn("Artículo VIEW-0", page)
        for index in range(1, 9):
            self.assertIn(f"Artículo VIEW-{index}", page)

    def test_successful_bid_shows_same_group_recommendations(self):
        self.login()
        self.create_lot("REL-01")
        self.create_lot("REL-02")
        self.create_lot("REL-03")
        self.create_lot("OTHER-01", group_name="Otro grupo")
        self.create_lot("OTHER-02", group_name="Otro grupo")
        with self.app.app_context():
            target = Auction.query.filter_by(lot_number="REL-01").one()
            target_id = target.id
        self.login_user()

        response = self.client.post(
            f"/subasta/{target_id}/ofertar",
            data={"csrf_token": self.csrf_token(), "amount": "150"},
            follow_redirects=True,
        )
        page = response.get_data(as_text=True)
        self.assertIn("Artículos relacionados", page)
        related_start = page.index(
            '<section class="mt-5" aria-labelledby="related-auctions-title">'
        )
        related_page = page[related_start:]
        self.assertIn("Artículo REL-02", related_page)
        self.assertIn("Artículo REL-03", related_page)
        self.assertIn("Artículo OTHER-01", related_page)
        self.assertNotIn("Artículo REL-01", related_page)

    def test_closing_reminder_emails_each_bidder_once_inside_30_minute_window(self):
        now = datetime.now(timezone.utc)
        with self.app.app_context():
            group = AuctionGroup(name="Cierre")
            in_window = Auction(
                title="Lote con cierre próximo",
                description="Descripción",
                lot_number="CLOSE-01",
                starting_price=Decimal("100"),
                current_price=Decimal("150"),
                commission_percent=Decimal("20"),
                quantity=1,
                sale_mode="lot",
                group_name=group.name,
                sales_group=group,
                starts_at=(now - timedelta(hours=1)).replace(tzinfo=None),
                closes_at=(now + timedelta(minutes=27)).replace(tzinfo=None),
            )
            outside_window = Auction(
                title="Lote fuera de ventana",
                description="Descripción",
                lot_number="CLOSE-02",
                starting_price=Decimal("100"),
                current_price=Decimal("150"),
                commission_percent=Decimal("20"),
                quantity=1,
                sale_mode="lot",
                group_name=group.name,
                sales_group=group,
                starts_at=(now - timedelta(hours=1)).replace(tzinfo=None),
                closes_at=(now + timedelta(minutes=31)).replace(tzinfo=None),
            )
            bidders = [
                User(username=f"closer{index}", email=f"closer{index}@example.test")
                for index in range(3)
            ]
            for bidder in bidders:
                bidder.set_password("safe-password")
            db.session.add_all([in_window, outside_window, *bidders])
            db.session.flush()
            db.session.add_all(
                [
                    Bid(amount=Decimal("150"), auction=in_window, bidder=bidders[0]),
                    Bid(amount=Decimal("200"), auction=in_window, bidder=bidders[0]),
                    Bid(amount=Decimal("150"), auction=in_window, bidder=bidders[1]),
                    Bid(amount=Decimal("150"), auction=outside_window, bidder=bidders[2]),
                ]
            )
            db.session.commit()

            with patch("app.auction_reminders.smtplib.SMTP") as smtp_factory:
                mail_server = smtp_factory.return_value.__enter__.return_value
                self.assertEqual(
                    send_due_auction_closing_reminders(now=now),
                    2,
                )
                self.assertEqual(
                    send_due_auction_closing_reminders(now=now),
                    0,
                )
                self.assertEqual(mail_server.send_message.call_count, 2)
                messages = [
                    call.args[0]
                    for call in mail_server.send_message.call_args_list
                ]
                self.assertEqual(
                    {message["To"] for message in messages},
                    {"closer0@example.test", "closer1@example.test"},
                )
                self.assertTrue(
                    all("Quedan 30 minutos" in message["Subject"] for message in messages)
                )
                self.assertTrue(
                    all("subasta/1" in message.get_content() for message in messages)
                )
            self.assertEqual(AuctionClosingReminder.query.count(), 2)

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
        self.assertIn(b"$U 540.00", dashboard.data)

        payment_page = self.client.get(f"/cuenta/subasta/{auction_id}/pagar")
        self.assertNotIn(b"Tarjeta de cr\xc3\xa9dito o d\xc3\xa9bito", payment_page.data)
        self.assertIn(b"Transferencia bancaria", payment_page.data)
        self.assertIn(b"001901236", payment_page.data)
        self.assertIn(b"JUAN MARTINEZ", payment_page.data)
        self.assertIn(b"9102129", payment_page.data)
        self.assertIn(b"$U 540.00", payment_page.data)

        response = self.client.post(
            f"/cuenta/subasta/{auction_id}/pagar",
            data={
                "csrf_token": self.csrf_token(),
                "method": "brou_transfer",
            },
            follow_redirects=True,
        )
        self.assertIn("pendiente de confirmación", response.get_data(as_text=True))
        with self.app.app_context():
            payment = AuctionPayment.query.one()
            self.assertEqual(payment.method, "brou_transfer")
            self.assertEqual(payment.status, "pending")
            self.assertEqual(payment.amount, Decimal("540.00"))
        self.purchase_notification.assert_called_once()
        self.assertIn(
            "Total: $U 540.00", self.purchase_notification.call_args.args[1]
        )

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
