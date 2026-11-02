import os
import subprocess
import sys
import unittest


class ConfigurationTest(unittest.TestCase):
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
