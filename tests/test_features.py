import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from managers import notifications, permissions, profiles, scheduler


class FeatureTests(unittest.TestCase):
    def test_permissions_roles(self):
        self.assertTrue(permissions.can("operator", "write"))
        self.assertFalse(permissions.can("operator", "restore"))
        self.assertFalse(permissions.can("viewer", "console"))
        self.assertTrue(permissions.can("viewer", "read"))

    def test_profile_export_excludes_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            profiles.export_bundle(
                path,
                {"host": "example", "password": "secret", "discord_webhook": "hidden"},
                {"Night": {"template": "dayzOffline.night", "mods": []}},
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertNotIn("password", payload["settings"])
        self.assertNotIn("discord_webhook", payload["settings"])
        self.assertIn("Night", payload["map_profiles"])

    def test_notifications_without_configuration_are_noop(self):
        self.assertEqual(
            "Aucune notification configurée",
            notifications.send({}, "test", "message"),
        )

    def test_rotation_script_contains_profiles_and_restart(self):
        cfg = {"lgsm_path": "/srv/dayz"}
        fake = type(
            "Connection",
            (),
            {
                "is_dir": lambda _self, path: path.endswith("dayzOffline.test"),
                "write_file": lambda _self, _path, _content: None,
                "execute": lambda _self, _command: (0, "", ""),
            },
        )()
        captured = {}
        fake.write_file = lambda _path, content: captured.setdefault("script", content)
        with patch.object(scheduler, "connection", fake):
            result = scheduler.apply_map_rotation(
                cfg,
                [{"template": "dayzOffline.test", "mods": [], "startparameters": ""}],
                "20:00",
                "Europe/Paris",
            )
        self.assertIn("Rotation active", result)
        self.assertIn("dayzOffline.test", captured["script"])
        self.assertIn("dayzserver", captured["script"])


if __name__ == "__main__":
    unittest.main()
