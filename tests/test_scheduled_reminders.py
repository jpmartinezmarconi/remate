import unittest
from unittest.mock import patch

from app import create_app
from app.database import db


class ScheduledRemindersConfig:
    TESTING = True
    SECRET_KEY = "test-key"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    REMINDER_TRIGGER_SECRET = "test-reminder-secret"


class ScheduledRemindersTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(ScheduledRemindersConfig)
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def test_rejects_requests_without_valid_trigger_secret(self):
        for headers in ({}, {"Authorization": "Bearer wrong-secret"}):
            with self.subTest(headers=headers):
                response = self.client.post(
                    "/api/internal/process-reminders",
                    headers=headers,
                )
                self.assertEqual(response.status_code, 403)

    def test_reports_missing_trigger_secret_configuration(self):
        self.app.config["REMINDER_TRIGGER_SECRET"] = None
        response = self.client.post(
            "/api/internal/process-reminders",
            headers={"Authorization": "Bearer test-reminder-secret"},
        )
        self.assertEqual(response.status_code, 503)

    @patch("app.routes.send_due_auction_outbid_notifications", return_value=3)
    @patch(
        "app.routes.send_due_auction_completion_notifications",
        return_value={"email": 4, "telegram": 5},
    )
    @patch("app.routes.send_due_auction_closing_reminders", return_value=2)
    @patch("app.routes.send_due_auction_reminders", return_value=1)
    def test_authorized_request_runs_all_reminder_jobs(
        self,
        send_reminders,
        send_closing_reminders,
        send_completion_notifications,
        send_outbid_notifications,
    ):
        response = self.client.post(
            "/api/internal/process-reminders",
            headers={"Authorization": "Bearer test-reminder-secret"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json,
            {
                "ok": True,
                "sent": {
                    "auction_reminders": 1,
                    "closing_reminders": 2,
                    "outbid_notifications": 3,
                    "auction_completion_notifications": 4,
                    "telegram_completion_notifications": 5,
                },
            },
        )
        send_reminders.assert_called_once_with()
        send_closing_reminders.assert_called_once_with()
        send_outbid_notifications.assert_called_once_with()
        send_completion_notifications.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
