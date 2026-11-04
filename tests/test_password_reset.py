from email.message import EmailMessage
from urllib.parse import urlsplit
import unittest
from unittest.mock import patch

from app import create_app
from app.database import db
from models.user import User


class PasswordResetConfig:
    TESTING = True
    SECRET_KEY = "password-reset-test-key"
    SMTP_HOST = "smtp.example.test"
    SMTP_PORT = 587
    SMTP_USERNAME = "sender@example.test"
    SMTP_PASSWORD = "smtp-password"
    SMTP_FROM_EMAIL = "Remate Martínez <sender@example.test>"
    PUBLIC_BASE_URL = "https://remate.example.test"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False


class PasswordResetTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(PasswordResetConfig)
        self.client = self.app.test_client()
        self.client.get("/auth/recuperar-contrasena")
        with self.app.app_context():
            db.create_all()
            user = User(
                username="customer",
                full_name="Test Customer",
                email="customer@example.test",
            )
            user.set_password("old-password")
            db.session.add(user)
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def csrf_token(self):
        with self.client.session_transaction() as session:
            return session["csrf_token"]

    @patch("routes.auth.smtplib.SMTP")
    def test_password_reset_email_link_changes_password_and_expires_after_use(
        self, smtp
    ):
        mail_server = smtp.return_value.__enter__.return_value
        response = self.client.post(
            "/auth/recuperar-contrasena",
            data={
                "csrf_token": self.csrf_token(),
                "email": "CUSTOMER@example.test",
            },
            follow_redirects=True,
        )
        self.assertIn("Si el correo está registrado", response.get_data(as_text=True))
        smtp.assert_called_once_with("smtp.example.test", 587, timeout=30)
        message = mail_server.send_message.call_args.args[0]
        self.assertIsInstance(message, EmailMessage)
        self.assertEqual(message["To"], "customer@example.test")
        reset_url = next(
            line
            for line in message.get_content().splitlines()
            if line.startswith("https://remate.example.test/")
        )
        reset_path = urlsplit(reset_url).path
        reset_response = self.client.post(
            reset_path,
            data={
                "csrf_token": self.csrf_token(),
                "password": "new-password",
                "password_confirmation": "new-password",
            },
            follow_redirects=True,
        )
        self.assertIn("Tu contraseña se actualizó", reset_response.get_data(as_text=True))
        with self.app.app_context():
            user = User.query.one()
            self.assertTrue(user.check_password("new-password"))
            self.assertIsNone(user.password_reset_requested_at)

        used_link_response = self.client.get(reset_path, follow_redirects=True)
        self.assertIn("no es válido o ya venció", used_link_response.get_data(as_text=True))

    @patch("routes.auth.smtplib.SMTP")
    def test_unknown_email_gets_same_response_without_sending_email(self, smtp):
        response = self.client.post(
            "/auth/recuperar-contrasena",
            data={
                "csrf_token": self.csrf_token(),
                "email": "unknown@example.test",
            },
            follow_redirects=True,
        )
        self.assertIn("Si el correo está registrado", response.get_data(as_text=True))
        smtp.assert_not_called()

    def test_reset_link_rejects_short_or_mismatched_passwords(self):
        with self.app.app_context():
            from routes.auth import _password_reset_serializer

            user = User.query.one()
            token = _password_reset_serializer().dumps(
                {"user_id": user.id, "password_hash": user.password_hash}
            )
        url = f"/auth/restablecer-contrasena/{token}"
        short_password = self.client.post(
            url,
            data={
                "csrf_token": self.csrf_token(),
                "password": "short",
                "password_confirmation": "short",
            },
        )
        self.assertEqual(short_password.status_code, 200)
        mismatch = self.client.post(
            url,
            data={
                "csrf_token": self.csrf_token(),
                "password": "new-password",
                "password_confirmation": "different-password",
            },
        )
        self.assertIn("no coinciden", mismatch.get_data(as_text=True))
