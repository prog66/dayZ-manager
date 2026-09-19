import errno
import io
import json
import os
import posixpath
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from managers import config_manager, diagnostics, notifications, permissions, profiles
from managers import rcon, scheduler, commands
from managers.mission_import import mission_source
from ssh.ssh_client import SSHClient, SSHError


class MemorySFTP:
    def __init__(self):
        self.dirs = {"/", "/srv", "/srv/mpmissions"}
        self.files = {}
        self.fail_put = False
        self.fail_publish = False

    def stat(self, path):
        if path in self.dirs:
            return SimpleNamespace(st_mode=stat.S_IFDIR | 0o755)
        if path in self.files:
            return SimpleNamespace(st_mode=stat.S_IFREG | 0o600)
        raise FileNotFoundError(errno.ENOENT, path)

    def mkdir(self, path):
        self.stat(posixpath.dirname(path))
        self.dirs.add(path)

    def put(self, local, remote):
        self.stat(posixpath.dirname(remote))
        if self.fail_put:
            raise OSError(errno.ENOSPC, "disque plein")
        self.files[remote] = Path(local).read_bytes()

    def rename(self, source, destination):
        self.stat(source)
        if self.fail_publish and '/.import-' in source:
            raise OSError(errno.EACCES, "publication refusée")
        if destination in self.dirs:
            raise FileExistsError(destination)
        self.dirs = {destination + p[len(source):] if p == source or p.startswith(source + '/') else p for p in self.dirs}
        self.files = {destination + p[len(source):] if p.startswith(source + '/') else p: v for p, v in self.files.items()}

    def close(self):
        pass


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.source = Path(self.tmp.name) / 'empty.alteria'
        self.source.mkdir()
        (self.source / 'init.c').write_text('new mission', encoding='utf-8')
        (self.source / 'db').mkdir()
        (self.source / 'db' / 'types.xml').write_text('<types/>', encoding='utf-8')
        self.sftp = MemorySFTP()
        self.client = SSHClient()
        self.client.client = SimpleNamespace(open_sftp=lambda: self.sftp)
        self.target = '/srv/mpmissions/dayzOffline.alteria'

    def existing(self):
        self.sftp.dirs.add(self.target)
        self.sftp.files[self.target + '/init.c'] = b'old mission'

    def test_full_nested_import_and_progress(self):
        progress = []
        result = self.client.import_mission(self.source, self.target, progress=progress.append)
        self.assertEqual(self.sftp.files[self.target + '/db/types.xml'], b'<types/>')
        self.assertEqual(result['backup'], '')
        self.assertEqual(len(progress), 2)

    def test_existing_mission_requires_explicit_replacement(self):
        self.existing()
        with self.assertRaises(SSHError):
            self.client.import_mission(self.source, self.target)
        self.assertEqual(self.sftp.files[self.target + '/init.c'], b'old mission')

    def test_replacement_retains_old_files(self):
        self.existing()
        result = self.client.import_mission(self.source, self.target, replace=True)
        self.assertEqual(self.sftp.files[result['backup'] + '/init.c'], b'old mission')
        self.assertEqual(self.sftp.files[self.target + '/init.c'], b'new mission')

    def test_interrupted_transfer_does_not_touch_existing_mission(self):
        self.existing()
        self.sftp.fail_put = True
        with self.assertRaises(SSHError):
            self.client.import_mission(self.source, self.target, replace=True)
        self.assertEqual(self.sftp.files[self.target + '/init.c'], b'old mission')

    def test_failed_publish_rolls_back_old_directory(self):
        self.existing()
        self.sftp.fail_publish = True
        with self.assertRaises(SSHError):
            self.client.import_mission(self.source, self.target, replace=True)
        self.assertEqual(self.sftp.files[self.target + '/init.c'], b'old mission')

    def test_permission_errors_do_not_attempt_mkdir(self):
        sftp = Mock()
        sftp.stat.side_effect = PermissionError(errno.EACCES, 'denied')
        with self.assertRaises(PermissionError):
            SSHClient._sftp_mkdirs(sftp, '/srv/mission')
        sftp.mkdir.assert_not_called()


class ZipTests(unittest.TestCase):
    def test_github_zip_with_nested_mission_and_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'mission.zip'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('DayZ-Alteria-Missions-main/empty.alteria/init.c', 'void main() {}')
                archive.writestr('DayZ-Alteria-Missions-main/empty.alteria/db/types.xml', '<types/>')
            with mission_source(path) as (source, name):
                self.assertEqual(name, 'dayzOffline.alteria')
                self.assertTrue((Path(source) / 'db/types.xml').is_file())
            self.assertFalse(Path(source).exists())

    def test_unsafe_zip_entries_are_rejected(self):
        for entry in ('../init.c', '/absolute/init.c', 'C:/init.c', 'bad/CON.txt', 'bad/.. /init.c'):
            with self.subTest(entry=entry), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'unsafe.zip'
                with zipfile.ZipFile(path, 'w') as archive:
                    archive.writestr(entry, 'bad')
                with self.assertRaises(ValueError), mission_source(path):
                    pass

    def test_expanded_size_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'large.zip'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('init.c', 'large')
            with patch('managers.mission_import.MAX_BYTES', 1):
                with self.assertRaises(ValueError), mission_source(path):
                    pass


class AuditTests(unittest.TestCase):
    def test_schedules_do_not_delete_other_jobs_or_timezone(self):
        existing = 'CRON_TZ=UTC\n0 1 * * * external-job\n0 2 * * * map-job # DAYZ-MANAGER-MAP\n'
        merged = scheduler._merge_job(existing, scheduler.TAG, ['0 4 * * * restart # DAYZ-MANAGER'], 'Europe/Paris')
        self.assertTrue(merged.startswith(existing))
        self.assertEqual(scheduler._without_job(merged, scheduler.TAG), existing.splitlines())
        self.assertEqual(scheduler._merge_job(merged, scheduler.TAG, ['0 4 * * * restart # DAYZ-MANAGER'], 'Europe/Paris'), merged)

    def test_crontab_read_failure_aborts_edit(self):
        with patch.object(scheduler, 'connection') as connection:
            connection.execute.return_value = (1, '', 'permission denied')
            with self.assertRaises(RuntimeError):
                scheduler._read_crontab()

    def test_restore_validator_rejects_traversal_and_symlink(self):
        import tarfile
        script = commands.restore_backup({'lgsm_path': '/srv/dayz'}, 'dayz-backup-test.tar.gz')
        validator = script.split("<<'PY'\n", 1)[1].split('\nPY', 1)[0]
        for name, link in (('../outside', False), ('safe-link', True)):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                archive_path = root / 'backup.tar.gz'
                with tarfile.open(archive_path, 'w:gz') as archive:
                    entry = tarfile.TarInfo(name)
                    if link:
                        entry.type = tarfile.SYMTYPE
                        entry.linkname = '../outside'
                    archive.addfile(entry)
                with patch('sys.argv', ['validate', str(archive_path), str(root)]):
                    with self.assertRaises(SystemExit):
                        exec(compile(validator, '<restore-validation>', 'exec'), {})

    def test_atomic_remote_write_failure_leaves_original(self):
        sftp = Mock()
        sftp.stat.return_value = SimpleNamespace(st_mode=stat.S_IFREG | 0o640)
        sftp.normalize.return_value = '/srv/server.cfg'
        sftp.open.return_value = io.BytesIO()
        sftp.posix_rename.side_effect = OSError('unsupported')
        client = SSHClient()
        client.client = SimpleNamespace(open_sftp=lambda: sftp)
        with self.assertRaises(OSError):
            client.write_file('/srv/server.cfg', 'new content')
        written = sftp.open.call_args.args[0]
        self.assertNotEqual(written, '/srv/server.cfg')
        sftp.chmod.assert_called_once_with(written, 0o640)
        sftp.remove.assert_called_once_with(written)
        sftp.close.assert_called_once()

    def test_rcon_rejects_damaged_crc(self):
        module = {'__name__': 'rcon_test'}
        exec(compile(rcon.RCONCTL_SCRIPT, '<rcon>', 'exec'), module)
        frame = module['_packet'](b'\xff\x01\x00players')
        self.assertEqual(module['_parse'](frame)[0], 1)
        self.assertEqual(module['_parse'](frame[:-1] + b'X'), (None, None))

    def test_rcon_no_response_is_failure(self):
        module = {'__name__': 'rcon_test'}
        exec(compile(rcon.RCONCTL_SCRIPT, '<rcon>', 'exec'), module)
        import socket
        sock = Mock()
        sock.recv.side_effect = [module['_packet'](b'\xff\x00\x01'), socket.timeout()]
        with patch('socket.socket', return_value=sock), patch('sys.argv', ['rcon', 'players']), patch('sys.stderr', new_callable=io.StringIO):
            self.assertEqual(module['main'](), 3)

    def test_viewer_cannot_restore_update_or_change_security(self):
        for action in ('write', 'restore', 'server_update', 'security', 'moderation', 'console'):
            self.assertFalse(permissions.can('viewer', action))
            self.assertFalse(permissions.can('unknown', action))

    def test_configuration_handles_non_object_and_invalid_numbers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.json'
            with patch.object(config_manager, 'CONFIG_FILE', path):
                path.write_text('[]', encoding='utf-8')
                self.assertEqual(config_manager.ConfigManager.load()['port'], 22)
                path.write_text(json.dumps({'refresh_interval': 'oops', 'port': -1, 'user_role': 'invalid'}), encoding='utf-8')
                result = config_manager.ConfigManager.load()
                self.assertEqual(result['refresh_interval'], 30)
                self.assertEqual(result['port'], 1)
                self.assertEqual(result['user_role'], 'viewer')

    def test_failed_local_save_preserves_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.json'
            path.write_text('{"host":"old"}', encoding='utf-8')
            with patch.object(config_manager, 'CONFIG_FILE', path), patch.object(config_manager.os, 'replace', side_effect=OSError('locked')):
                with self.assertRaises(OSError):
                    config_manager.ConfigManager.save({'host': 'new'})
            self.assertEqual(json.loads(path.read_text())['host'], 'old')
            self.assertEqual(list(Path(tmp).iterdir()), [path])

    def test_export_does_not_leak_server_snapshot_passwords(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'profile.json'
            profiles.export_bundle(path, {'password': 'hidden'}, {}, {'serverDZ': 'passwordAdmin="hidden";'})
            self.assertNotIn('hidden', path.read_text())

    def test_notification_failure_does_not_skip_second_channel(self):
        with patch.object(notifications, 'send_discord', side_effect=OSError('offline')), patch.object(notifications, 'send_email', return_value='E-mail OK') as email:
            with self.assertRaisesRegex(RuntimeError, 'E-mail OK'):
                notifications.send({'discord_webhook': 'configured', 'notification_email_enabled': True}, 'subject', 'body')
            email.assert_called_once()

    def test_smtp_missing_credentials_is_error(self):
        with self.assertRaises(ValueError):
            notifications.send_email({'notification_email_host': 'host', 'notification_email_to': 'to', 'notification_email_user': 'user'}, 's', 'b')

    def test_unconfigured_diagnostics_does_not_connect(self):
        with patch.object(diagnostics, 'connection') as connection:
            rows = diagnostics.inspect_server({})
            self.assertTrue(rows)
            connection.execute.assert_not_called()

    def test_large_ssh_output_drained_before_exit_status(self):
        channel = Mock()
        out = [b'A' * 65536] * 40
        err = [b'warning'] * 20
        channel.recv_ready.side_effect = lambda: bool(out)
        channel.recv_stderr_ready.side_effect = lambda: bool(err)
        channel.recv.side_effect = lambda _: out.pop()
        channel.recv_stderr.side_effect = lambda _: err.pop()
        channel.exit_status_ready.side_effect = lambda: not out and not err
        channel.recv_exit_status.return_value = 0
        client = SSHClient()
        client.client = Mock()
        client.client.exec_command.return_value = (Mock(), SimpleNamespace(channel=channel), Mock())
        with patch('ssh.ssh_client.time.sleep'):
            code, stdout, stderr = client.execute('read large log')
        self.assertEqual(len(stdout), 40 * 65536)
        self.assertEqual(stderr.count('warning'), 20)
        self.assertEqual(code, 0)
        channel.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
