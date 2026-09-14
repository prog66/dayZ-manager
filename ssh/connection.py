"""Connexion SSH partagée, persistante et thread-safe.

Un seul ``Connection`` vit pour toute l'application. Les workers Qt
(threads) appellent ``execute`` / ``read_file`` / ``write_file`` à travers
un verrou : la connexion est ouverte paresseusement et réutilisée au lieu
d'être recréée à chaque commande.
"""

import threading

from ssh.ssh_client import SSHClient, SSHError


class Connection:
    def __init__(self):
        self._client = SSHClient()
        self._lock = threading.RLock()
        self._params = {"host": "", "user": "", "password": "", "port": 22}

    def configure(self, host, user, password, port=22):
        """Met à jour les identifiants. Coupe la session si elle change."""
        with self._lock:
            changed = (
                host != self._params["host"]
                or user != self._params["user"]
                or password != self._params["password"]
                or port != self._params["port"]
            )
            self._params = {
                "host": host,
                "user": user,
                "password": password,
                "port": port,
            }
            if changed:
                self._client.close()

    def is_connected(self):
        with self._lock:
            return self._client.is_active()

    def _ensure(self):
        if self._client.is_active():
            return
        p = self._params
        if not p["host"] or not p["user"]:
            raise SSHError("Connexion non configurée (IP / utilisateur manquants).")
        self._client.connect(p["host"], p["user"], p["password"], port=p["port"])

    # ------------------------------------------------------------------ #
    def execute(self, command, timeout=None):
        with self._lock:
            self._ensure()
            return self._client.execute(command, timeout=timeout)

    def open_shell_channel(self, command, get_pty=True):
        with self._lock:
            self._ensure()
            return self._client.open_shell_channel(command, get_pty=get_pty)

    def read_file(self, remote_path):
        with self._lock:
            self._ensure()
            return self._client.read_file(remote_path)

    def write_file(self, remote_path, content):
        with self._lock:
            self._ensure()
            self._client.write_file(remote_path, content)

    def file_exists(self, remote_path):
        with self._lock:
            self._ensure()
            return self._client.file_exists(remote_path)

    def is_dir(self, remote_path):
        with self._lock:
            self._ensure()
            return self._client.is_dir(remote_path)

    def upload_dir(self, local_dir, remote_dir, progress=None):
        with self._lock:
            self._ensure()
            self._client.upload_dir(local_dir, remote_dir, progress=progress)

    def close(self):
        with self._lock:
            self._client.close()


# Instance partagée par toute l'application.
connection = Connection()
