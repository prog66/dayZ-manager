import json
import tempfile
import unittest
from pathlib import Path

from tools.release_manifest import build_manifest, write_release_files


class ReleaseManifestTests(unittest.TestCase):
    def test_manifest_contains_artifact_hash_and_stable_source_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "DayZManager.exe"
            requirements = root / "requirements.txt"
            artifact.write_bytes(b"test executable")
            requirements.write_text("example==1.0.0\n", encoding="utf-8")
            (root / "main.py").write_text("print('ok')\n", encoding="utf-8")
            first = build_manifest(artifact, root)
            second = build_manifest(artifact, root)
            self.assertEqual(first, second)
            self.assertEqual(64, len(first["artifact"]["sha256"]))
            self.assertEqual(64, len(first["source"]["fingerprint"]))

    def test_manifest_and_checksums_are_written(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "bundle" / "DayZManager.exe"
            artifact.parent.mkdir()
            artifact.write_bytes(b"test executable")
            (root / "requirements.txt").write_text("example==1.0.0\n", encoding="utf-8")
            manifest_path = root / "bundle" / "manifest.json"
            write_release_files(artifact, manifest_path, root)
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["artifact"]["name"], "DayZManager.exe")
            self.assertTrue((root / "checksums.sha256").is_file())


if __name__ == "__main__":
    unittest.main()
