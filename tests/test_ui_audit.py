import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from managers.config_manager import DEFAULTS
from ui.dashboard import Dashboard
from ui.mission_dialog import MissionImportDialog


class UIAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.cfg = {**DEFAULTS, 'auto_refresh': False, 'user_role': 'viewer'}
        self.patches = [
            patch('ui.dashboard.ConfigManager.load', side_effect=lambda: dict(self.cfg)),
            patch('ui.dashboard.profiles.load_profiles', return_value={}),
            patch.object(Dashboard, '_auto_check_for_updates'),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.window = Dashboard()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()
        self.window.deleteLater()

    def test_all_navigation_destinations(self):
        for builder in self.window._tab_targets:
            self.window._nav_to(builder)
            self.assertEqual(self.window._active_builder(self.window.nav.currentRow()), builder)

    def test_local_diagnostics_does_not_report_connected(self):
        before = self.window.status_pill.text()
        self.window.run_diagnostics()
        self.assertEqual(self.window.status_pill.text(), before)
        self.assertEqual(self.window.workers, [])

    def test_viewer_actions_block_before_network_or_dialog(self):
        with patch.object(self.window, '_require_config') as config:
            for action in ('import_mission_dialog', 'broadcast_message', 'kick_player',
                           'ban_player', 'offline_ban', 'import_bans', 'remove_selected_ban',
                           'reload_bans', 'restore_backup', '_persist_mods_order', 'start_live_console'):
                getattr(self.window, action)()
            config.assert_not_called()

    def test_func_worker_kept_until_real_thread_finish(self):
        received = []
        worker = self.window.run_net(lambda: 42, ok=received.append)
        self.assertIn(worker, self.window.workers)
        for _ in range(100):
            QTest.qWait(10)
            if not self.window.workers:
                break
        self.assertEqual(received, [42])
        self.assertEqual(self.window.workers, [])

    def test_mission_dialog_failure_restores_controls(self):
        dialog = MissionImportDialog(self.cfg, self.window)
        dialog.source.setText('absent.zip')
        with patch('ui.mission_dialog.import_source', side_effect=ValueError('Archive invalide')):
            dialog.start()
            for _ in range(100):
                QTest.qWait(10)
                if dialog.worker is None:
                    break
        self.assertIsNone(dialog.worker)
        self.assertTrue(dialog.start_btn.isEnabled())
        self.assertIn('Archive invalide', dialog.messages.toPlainText())
        self.assertIsNone(dialog.result_data)
        dialog.reject()

    def test_connection_test_does_not_reconfigure_shared_connection(self):
        self.window.host_edit.setText('example.invalid')
        self.window.user_edit.setText('tester')
        with patch('ssh.ssh_client.SSHClient') as client, \
                patch('ui.dashboard.connection.configure') as configure, \
                patch('ui.dashboard.QMessageBox.information'):
            client.return_value.execute.return_value = (0, 'CONNECTED', '')
            self.window.test_connection()
            for _ in range(100):
                QTest.qWait(10)
                if not self.window.workers:
                    break
            configure.assert_not_called()
            client.return_value.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
