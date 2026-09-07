import unittest
from unittest.mock import patch

from managers import cfg_editor


class FakeConnection:
    def __init__(self):
        self.files = {
            cfg_editor.common_cfg_path({"lgsm_path": "/srv/dayz"}):
                'steamuser="username"\nmods="@DeerIsle\\;@CF"\n',
            cfg_editor.serverdz_path({"lgsm_path": "/srv/dayz"}):
                'template = "dayzOffline.chernarusplus";\n',
        }
        self.dirs = {"/srv/dayz/serverfiles/mpmissions/dayzOffline.namalsk"}
        self.fail_common_write = False

    def read_file(self, path):
        return self.files[path]

    def write_file(self, path, content):
        if self.fail_common_write and path.endswith("common.cfg"):
            raise IOError("write failed")
        self.files[path] = content

    def is_dir(self, path):
        return path in self.dirs

    def file_exists(self, path):
        return path in self.files or path in self.dirs


class CfgEditorTests(unittest.TestCase):
    def test_map_switch_removes_old_map_and_keeps_other_mod(self):
        fake = FakeConnection()
        cfg = {"lgsm_path": "/srv/dayz"}
        with patch.object(cfg_editor, "connection", fake):
            result = cfg_editor.set_active_map(
                cfg,
                "@NamalskIsland",
                "dayzOffline.namalsk",
                ("@DeerIsle", "@NamalskIsland"),
            )
            self.assertEqual(["@DeerIsle"], result["removed_mods"])
            self.assertEqual(
                ["@CF", "@NamalskIsland"],
                cfg_editor.get_mods(cfg),
            )

    def test_map_switch_rolls_back_both_files(self):
        fake = FakeConnection()
        fake.fail_common_write = True
        cfg = {"lgsm_path": "/srv/dayz"}
        server_path = cfg_editor.serverdz_path(cfg)
        common_path = cfg_editor.common_cfg_path(cfg)
        old_server = fake.files[server_path]
        old_common = fake.files[common_path]
        with patch.object(cfg_editor, "connection", fake):
            with self.assertRaises(IOError):
                cfg_editor.set_active_map(
                    cfg,
                    "@NamalskIsland",
                    "dayzOffline.namalsk",
                    ("@DeerIsle", "@NamalskIsland"),
                )
        self.assertEqual(old_server, fake.files[server_path])
        self.assertEqual(old_common, fake.files[common_path])

    def test_ensure_steam_user_replaces_lgsm_placeholder(self):
        fake = FakeConnection()
        cfg = {"lgsm_path": "/srv/dayz", "steam_user": "dayz_manager"}
        with patch.object(cfg_editor, "connection", fake):
            self.assertEqual("dayz_manager", cfg_editor.ensure_steam_user(cfg))
            self.assertEqual("dayz_manager", cfg_editor.get_steam_user(cfg))

    def test_ensure_steam_user_keeps_existing_remote_login(self):
        fake = FakeConnection()
        common_path = cfg_editor.common_cfg_path({"lgsm_path": "/srv/dayz"})
        fake.files[common_path] = 'steamuser="remote_login"\n'
        cfg = {"lgsm_path": "/srv/dayz", "steam_user": "local_login"}
        with patch.object(cfg_editor, "connection", fake):
            self.assertEqual("remote_login", cfg_editor.ensure_steam_user(cfg))

    def test_ensure_steam_user_requires_real_login(self):
        fake = FakeConnection()
        cfg = {"lgsm_path": "/srv/dayz", "steam_user": "anonymous"}
        with patch.object(cfg_editor, "connection", fake):
            with self.assertRaises(ValueError):
                cfg_editor.ensure_steam_user(cfg)


if __name__ == "__main__":
    unittest.main()
