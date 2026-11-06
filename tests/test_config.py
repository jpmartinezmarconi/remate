import os
import subprocess
import sys
import unittest
from unittest.mock import patch

from config import _database_url_from_environment, _smtp_settings_from_environment


class ConfigurationTest(unittest.TestCase):
    def test_existing_gmail_secret_uses_correct_account_and_takes_priority(self):
        with patch.dict(os.environ, {
            "gmail_SMTP": "aaaa bbbb cccc dddd",
            "SMTP_PASSWORD": "old-password",
            "SMTP_USERNAME": "old@example.test",
            "SMTP_FROM_EMAIL": "old@example.test",
            "SMTP_HOST": "smtp.example.test",
        }, clear=True):
            settings = _smtp_settings_from_environment()
        self.assertEqual(settings["SMTP_HOST"], "smtp.gmail.com")
        self.assertEqual(settings["SMTP_PORT"], 587)
        self.assertEqual(settings["SMTP_USERNAME"], "inforematemartinez@gmail.com")
        self.assertEqual(settings["SMTP_FROM_EMAIL"], "inforematemartinez@gmail.com")
        self.assertEqual(settings["SMTP_PASSWORD"], "aaaabbbbccccdddd")

    def test_legacy_smtp_configuration_is_preserved_without_gmail_secret(self):
        with patch.dict(os.environ, {
            "SMTP_HOST": "smtp.example.test", "SMTP_PORT": "587",
            "SMTP_USERNAME": "sender@example.test", "SMTP_PASSWORD": "test-password",
            "SMTP_FROM_EMAIL": "sender@example.test",
        }, clear=True):
            settings = _smtp_settings_from_environment()
        self.assertEqual(settings["SMTP_HOST"], "smtp.example.test")
        self.assertEqual(settings["SMTP_USERNAME"], "sender@example.test")
        self.assertEqual(settings["SMTP_PASSWORD"], "test-password")

    def test_reminder_trigger_secret_uses_environment(self):
        environment = os.environ.copy()
        environment["REMINDER_TRIGGER_SECRET"] = "test-reminder-secret"
        configured_secret = subprocess.run(
            [
                sys.executable,
                "-c",
                "from config import Config; print(Config.REMINDER_TRIGGER_SECRET)",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        ).stdout.strip()
        self.assertEqual(configured_secret, "test-reminder-secret")

    def test_local_database_defaults_to_sqlite(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                _database_url_from_environment(),
                "sqlite:///app.db",
            )

    def test_render_requires_persistent_postgresql_database(self):
        with patch.dict(os.environ, {"RENDER": "true"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "DATABASE_URL"):
                _database_url_from_environment()

    def test_render_rejects_sqlite_database(self):
        with patch.dict(
            os.environ,
            {"RENDER": "true", "DATABASE_URL": "sqlite:///app.db"},
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "PostgreSQL"):
                _database_url_from_environment()

    def test_render_accepts_neon_postgresql_database(self):
        database_url = (
            "postgresql+psycopg2://user:password@ep.example.neon.tech/app"
        )
        with patch.dict(
            os.environ,
            {
                "RENDER": "true",
                "DATABASE_URL": (
                    "postgresql://user:password@ep.example.neon.tech/app"
                ),
            },
            clear=True,
        ):
            self.assertEqual(_database_url_from_environment(), database_url)

    def test_render_normalizes_neon_psycopg_driver_url(self):
        with patch.dict(
            os.environ,
            {
                "RENDER": "true",
                "DATABASE_URL": (
                    "postgresql+psycopg://user:password@ep.example.neon.tech/app"
                ),
            },
            clear=True,
        ):
            self.assertEqual(
                _database_url_from_environment(),
                "postgresql+psycopg2://user:password@ep.example.neon.tech/app",
            )

    def test_render_normalizes_legacy_postgres_scheme(self):
        with patch.dict(
            os.environ,
            {
                "RENDER": "true",
                "DATABASE_URL": "postgres://user:password@db.example/app",
            },
            clear=True,
        ):
            self.assertEqual(
                _database_url_from_environment(),
                "postgresql+psycopg2://user:password@db.example/app",
            )

    def test_area_password_prefers_render_variable_and_supports_legacy_name(self):
        environment = os.environ.copy()
        environment["PASSWORD_AREA_PRIVADA"] = "render-password"
        environment["PRIVATE_AREA_PASSWORD"] = "legacy-password"

        configured_password = subprocess.run(
            [
                sys.executable,
                "-c",
                "from config import Config; print(Config.PRIVATE_AREA_PASSWORD)",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        ).stdout.strip()
        self.assertEqual(configured_password, "render-password")

        environment["PASSWORD_AREA_PRIVADA"] = ""
        configured_password = subprocess.run(
            [
                sys.executable,
                "-c",
                "from config import Config; print(Config.PRIVATE_AREA_PASSWORD)",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        ).stdout.strip()
        self.assertEqual(configured_password, "legacy-password")
