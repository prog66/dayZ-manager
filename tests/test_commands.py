import unittest

from managers import commands


class CommandTests(unittest.TestCase):
    CFG = {"lgsm_path": "/srv/dayz"}

    def test_backup_contains_real_active_config_and_common_cfg(self):
        script = commands.create_backup(self.CFG)
        self.assertIn("serverfiles/cfg/dayzserver.server.cfg", script)
        self.assertIn("lgsm/config-lgsm/dayzserver/common.cfg", script)
        self.assertNotIn("[ -f serverDZ.cfg ]", script)

    def test_restore_supports_new_and_old_archive_roots(self):
        script = commands.restore_backup(
            self.CFG, "dayz-backup-20260914-120000.tar.gz"
        )
        self.assertIn('serverfiles/*|lgsm/*) DEST="$ROOT"', script)
        self.assertIn('DEST="$ROOT/serverfiles"', script)

    def test_backup_path_is_validated(self):
        with self.assertRaises(ValueError):
            commands.delete_backup(self.CFG, "../outside.tar.gz")

    def test_remove_mod_has_server_side_active_guard(self):
        script = commands.remove_mod(self.CFG, "@DeerIsle")
        self.assertIn("MOD_ACTIVE", script)
        self.assertIn("rm -rf --", script)


if __name__ == "__main__":
    unittest.main()
