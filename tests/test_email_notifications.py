import unittest
from unittest.mock import patch

from app import create_app
from app.email_notifications import send_business_notification


class EmailNotificationConfig:
    TESTING = True
    SECRET_KEY = "test-key"
    CONTACT_EMAIL = "remateonline@yahoo.com"
    SMTP_HOST = "smtp.mail.yahoo.com"
    SMTP_PORT = 587
    SMTP_USERNAME = "remateonline@yahoo.com"
    SMTP_PASSWORD = "application-password"
    SMTP_FROM_EMAIL = "remateonline@yahoo.com"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False


class EmailNotificationTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(EmailNotificationConfig)

    @patch("app.email_notifications.smtplib.SMTP")
    def test_sends_business_notification_using_configured_smtp(self, smtp):
        mail_server = smtp.return_value.__enter__.return_value

        with self.app.app_context():
            send_business_notification("Nueva puja", "Oferta: $U 150.00")

        smtp.assert_called_once_with("smtp.mail.yahoo.com", 587, timeout=30)
        mail_server.starttls.assert_called_once()
        mail_server.login.assert_called_once_with(
            "remateonline@yahoo.com", "application-password"
        )
        message = mail_server.send_message.call_args.args[0]
        self.assertEqual(message["To"], "remateonline@yahoo.com")
        self.assertEqual(message["From"], "remateonline@yahoo.com")
        self.assertEqual(message["Subject"], "Nueva puja")
        self.assertIn("Oferta: $U 150.00", message.get_content())

    @patch("app.email_notifications.smtplib.SMTP")
    def test_requires_smtp_password(self, smtp):
        self.app.config["SMTP_PASSWORD"] = None

        with self.app.app_context(), self.assertRaises(RuntimeError):
            send_business_notification("Nueva puja", "Oferta registrada.")

        smtp.assert_not_called()


if __name__ == "__main__":
    unittest.main()
