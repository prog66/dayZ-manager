import unittest

from ssh.text import clean_terminal_text, decode_bytes


class SshTextTests(unittest.TestCase):
    def test_removes_ansi_and_normalizes_progress_lines(self):
        value = "\x1b[1m\x1b[31m FAIL \x1b[0m\x1b[K\rDémarrage\n"
        self.assertEqual(" FAIL \nDémarrage\n", clean_terminal_text(value))

    def test_decodes_utf8_without_dropping_accents(self):
        self.assertEqual(
            "Connexion réussie ✔",
            decode_bytes("Connexion réussie ✔".encode()),
        )

    def test_falls_back_for_legacy_western_output(self):
        self.assertEqual("Échec", decode_bytes(b"\xC9chec"))


if __name__ == "__main__":
    unittest.main()
