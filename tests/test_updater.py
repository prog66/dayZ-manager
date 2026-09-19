import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from managers import updater
from tools.package_release import build_archive


class UpdaterTests(unittest.TestCase):
    def test_normalize_repository_accepts_short_name_and_https_url(self):
        self.assertEqual("owner/repository", updater.normalize_repository("owner/repository"))
        self.assertEqual(
            "owner/repository",
            updater.normalize_repository("https://github.com/owner/repository.git/"),
        )

    def test_normalize_repository_rejects_non_github_urls(self):
        with self.assertRaises(updater.UpdateError):
            updater.normalize_repository("http://github.com/owner/repository")
        with self.assertRaises(updater.UpdateError):
            updater.normalize_repository("owner")

    @patch("managers.updater._json_request")
    def test_fetch_latest_release_uses_sidecar_checksum(self, json_request):
        json_request.return_value = {
            "tag_name": "v1.0.0",
            "name": "Version 1.0.0",
            "html_url": "https://github.com/owner/repository/releases/tag/v1.0.0",
            "body": "Correctifs",
            "draft": False,
            "prerelease": False,
            "assets": [
                {
                    "name": "DayZManager-windows-amd64.zip",
                    "size": 123,
                    "browser_download_url": (
                        "https://github.com/owner/repository/releases/download/"
                        "v1.0.0/DayZManager-windows-amd64.zip"
                    ),
                },
                {
                    "name": "DayZManager-windows-amd64.zip.sha256",
                    "browser_download_url": (
                        "https://github.com/owner/repository/releases/download/"
                        "v1.0.0/DayZManager-windows-amd64.zip.sha256"
                    ),
                },
            ],
        }

        info = updater.fetch_latest_release("owner/repository", "0.9.0")

        self.assertTrue(info.is_newer)
        self.assertEqual("1.0.0", info.version)
        self.assertEqual(123, info.size_bytes)
        self.assertIsNone(info.sha256)
        self.assertTrue(info.checksum_url.endswith(".zip.sha256"))

    @patch("managers.updater._json_request")
    def test_fetch_latest_release_reports_current_version(self, json_request):
        json_request.return_value = {
            "tag_name": "v0.9.0",
            "draft": False,
            "prerelease": False,
            "assets": [],
        }

        info = updater.fetch_latest_release("owner/repository", "0.9.0")

        self.assertFalse(info.is_newer)
        self.assertEqual("", info.download_url)

    def test_safe_extract_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "unsafe.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("../outside.txt", "no")

            with self.assertRaises(updater.UpdateError):
                updater._safe_extract(archive, root / "extract")

    def test_prepare_update_downloads_verifies_and_preserves_local_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "DayZManager"
            package.mkdir()
            executable = package / "DayZManager.exe"
            executable.write_bytes(b"new executable")
            manifest = {
                "version": "1.0.0",
                "artifact": {
                    "name": "DayZManager.exe",
                    "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                },
            }
            (package / "manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            archive, _ = build_archive(package, root / "update.zip")
            install = root / "installed"
            install.mkdir()
            (install / "DayZManager.exe").write_bytes(b"old executable")
            (install / "config.json").write_text("local", encoding="utf-8")
            (install / "map_profiles.json").write_text("maps", encoding="utf-8")
            info = updater.UpdateInfo(
                repository="owner/repository",
                version="1.0.0",
                tag_name="v1.0.0",
                release_name="Version 1.0.0",
                release_url="https://github.com/owner/repository/releases/tag/v1.0.0",
                download_url="https://github.com/owner/repository/releases/download/v1.0.0/update.zip",
                asset_name="update.zip",
                size_bytes=archive.stat().st_size,
                sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                checksum_url=None,
                notes="",
                is_newer=True,
            )

            def copy_fixture(_url, destination, _expected_size=0):
                destination.write_bytes(archive.read_bytes())

            with patch("managers.updater._download", side_effect=copy_fixture):
                plan = updater.prepare_update(info, install_dir=install)

            self.assertTrue((plan.staged_dir / "DayZManager.exe").is_file())
            self.assertEqual("local", (plan.temp_root / "preserved" / "config.json").read_text(encoding="utf-8"))
            self.assertEqual("maps", (plan.temp_root / "preserved" / "map_profiles.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
