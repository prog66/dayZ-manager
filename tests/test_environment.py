import tempfile
import unittest
from pathlib import Path

from tools.verify_environment import read_lock


class EnvironmentTests(unittest.TestCase):
    def test_lock_parser_accepts_exact_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "requirements-lock.txt"
            path.write_text("Example-Package==1.2.3\n", encoding="utf-8")
            self.assertEqual([("Example-Package", "1.2.3")], read_lock(path))


if __name__ == "__main__":
    unittest.main()
