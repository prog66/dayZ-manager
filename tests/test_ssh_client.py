import unittest

from ssh.ssh_client import SSHClient


class FakeSFTP:
    def __init__(self, existing=()):
        self.existing = set(existing)
        self.created = []

    def stat(self, path):
        if path not in self.existing:
            raise IOError(2, "No such file or directory")

    def mkdir(self, path):
        self.created.append(path)
        self.existing.add(path)


class SSHClientTests(unittest.TestCase):
    def test_mkdirs_preserves_absolute_linux_path(self):
        sftp = FakeSFTP({"/"})

        SSHClient._sftp_mkdirs(sftp, "/home/florent/lgsm/serverfiles/mpmissions")

        self.assertEqual(
            [
                "/home",
                "/home/florent",
                "/home/florent/lgsm",
                "/home/florent/lgsm/serverfiles",
                "/home/florent/lgsm/serverfiles/mpmissions",
            ],
            sftp.created,
        )

    def test_mkdirs_keeps_relative_path_relative(self):
        sftp = FakeSFTP({"."})

        SSHClient._sftp_mkdirs(sftp, "serverfiles/mpmissions")

        self.assertEqual(["./serverfiles", "./serverfiles/mpmissions"], sftp.created)


if __name__ == "__main__":
    unittest.main()
