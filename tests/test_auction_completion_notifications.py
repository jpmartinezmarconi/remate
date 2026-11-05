from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest
from unittest.mock import patch

from app import create_app
from app.auction_reminders import send_due_auction_completion_notifications
from app.database import db
from models.auction import Auction
from models.auction_completion_notification import AuctionCompletionNotification
from models.auction_group import AuctionGroup
from models.auction_payment import AuctionPayment
from models.bid import Bid
from models.user import User


class AuctionCompletionConfig:
    TESTING = True
    SECRET_KEY = "test-key"
    CONTACT_EMAIL = "remateonline@yahoo.com"
    SMTP_HOST = "smtp.mail.yahoo.com"
    SMTP_PORT = 587
    SMTP_USERNAME = "remateonline@yahoo.com"
    SMTP_PASSWORD = "application-password"
    SMTP_FROM_EMAIL = "remateonline@yahoo.com"
    PUBLIC_BASE_URL = "https://remate.example.test"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False


class AuctionCompletionNotificationTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(AuctionCompletionConfig)
        with self.app.app_context():
            db.create_all()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def create_auction(self, title, *, closes_at, starts_at=None, bid=None):
        with self.app.app_context():
            group = AuctionGroup(name=f"Group {title}")
            auction = Auction(
                title=title,
                description="Auction description",
                starting_price=Decimal("100"),
                current_price=Decimal("100"),
                commission_percent=Decimal("20"),
                quantity=1,
                sale_mode="lot",
                group_name=group.name,
                sales_group=group,
                starts_at=starts_at or closes_at - timedelta(days=1),
                closes_at=closes_at,
            )
            db.session.add(auction)
            if bid:
                bidder = User(
                    username=f"buyer-{title}",
                    full_name="<Buyer>",
                    email="buyer@example.test",
                    phone="099123456",
                    shipping_address="18 de Julio 1000",
                    city="Montevideo",
                    postal_code="11100",
                )
                bidder.set_password("safe-password")
                db.session.add(bidder)
                db.session.flush()
                db.session.add(
                    Bid(amount=Decimal("150"), auction=auction, bidder=bidder)
                )
                if bid == "paid":
                    db.session.add(
                        AuctionPayment(
                            auction=auction,
                            user=bidder,
                            method="brou_transfer",
                            amount=Decimal("180"),
                            status="pending",
                        )
                    )
            db.session.commit()
            return auction.id

    @patch("app.auction_reminders.smtplib.SMTP")
    def test_sends_html_and_text_emails_once_for_ended_auctions(self, smtp):
        now = datetime.now(timezone.utc)
        self.create_auction("Sin ofertas", closes_at=now - timedelta(minutes=2))
        self.create_auction(
            "Con ganador",
            closes_at=now - timedelta(minutes=1),
            bid="paid",
        )
        self.create_auction("Todavía activa", closes_at=now + timedelta(hours=1))
        self.create_auction(
            "No comenzó",
            starts_at=now + timedelta(hours=1),
            closes_at=now - timedelta(minutes=1),
        )
        mail_server = smtp.return_value.__enter__.return_value

        with self.app.app_context():
            sent = send_due_auction_completion_notifications(now)

        self.assertEqual(sent, 2)
        self.assertEqual(mail_server.send_message.call_count, 2)
        messages = [
            call.args[0] for call in mail_server.send_message.call_args_list
        ]
        no_bid_message = next(
            message for message in messages if "Sin ofertas" in message["Subject"]
        )
        winner_message = next(
            message for message in messages if "Con ganador" in message["Subject"]
        )
        self.assertEqual(no_bid_message["To"], "remateonline@yahoo.com")
        no_bid_plain = no_bid_message.get_body(
            preferencelist=("plain",)
        ).get_content()
        self.assertIn("republicar el lote", no_bid_plain)
        no_bid_html = no_bid_message.get_body(
            preferencelist=("html",)
        ).get_content()
        self.assertIn("No se recibieron ofertas", no_bid_html)
        winner_plain = winner_message.get_body(
            preferencelist=("plain",)
        ).get_content()
        self.assertIn("buyer@example.test", winner_plain)
        self.assertIn("Método de pago: brou transfer (pending)", winner_plain)
        winner_html = winner_message.get_body(preferencelist=("html",)).get_content()
        self.assertIn("&lt;Buyer&gt;", winner_html)
        self.assertNotIn("<Buyer>", winner_html)
        with self.app.app_context():
            self.assertEqual(AuctionCompletionNotification.query.count(), 2)

        smtp.reset_mock()
        with self.app.app_context():
            self.assertEqual(send_due_auction_completion_notifications(now), 0)
        smtp.assert_not_called()

    def test_rejects_naive_dispatch_time(self):
        with self.app.app_context(), self.assertRaises(ValueError):
            send_due_auction_completion_notifications(datetime.now())


if __name__ == "__main__":
    unittest.main()
