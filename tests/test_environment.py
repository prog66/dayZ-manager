import tempfile
import unittest
from pathlib import Path

from tools.verify_environment import read_lock
from managers.config_manager import (
    DEFAULTS,
    DEFAULT_NOTIFICATION_EMAIL_FROM,
    DEFAULT_NOTIFICATION_EMAIL_HOST,
    DEFAULT_NOTIFICATION_EMAIL_TO,
    DEFAULT_NOTIFICATION_EMAIL_USER,
)
from version import GITHUB_REPOSITORY, GITHUB_REPOSITORY_URL


class EnvironmentTests(unittest.TestCase):
    def test_update_repository_defaults_to_official_github_url(self):
        self.assertEqual("prog66/dayZ-manager", GITHUB_REPOSITORY)
        self.assertEqual(
            "https://github.com/prog66/dayZ-manager",
            GITHUB_REPOSITORY_URL,
        )
        self.assertEqual(GITHUB_REPOSITORY_URL, DEFAULTS["github_repository"])

    def test_openxchange_email_defaults_are_prefilled(self):
        self.assertEqual(DEFAULT_NOTIFICATION_EMAIL_HOST, "smtp.openxchange.eu")
        self.assertEqual(
            DEFAULTS["notification_email_host"],
            DEFAULT_NOTIFICATION_EMAIL_HOST,
        )
        self.assertEqual(
            DEFAULTS["notification_email_user"],
            DEFAULT_NOTIFICATION_EMAIL_USER,
        )
        self.assertEqual(
            DEFAULTS["notification_email_from"],
            DEFAULT_NOTIFICATION_EMAIL_FROM,
        )
        self.assertEqual(
            DEFAULTS["notification_email_to"],
            DEFAULT_NOTIFICATION_EMAIL_TO,
        )

    def test_lock_parser_accepts_exact_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "requirements-lock.txt"
            path.write_text("Example-Package==1.2.3\n", encoding="utf-8")
            self.assertEqual([("Example-Package", "1.2.3")], read_lock(path))


if __name__ == "__main__":
    unittest.main()
