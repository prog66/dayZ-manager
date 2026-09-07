"""Bas niveau : un client SSH/SFTP fin au-dessus de paramiko.

Cette classe reste volontairement simple : une connexion = un client.
La réutilisation et la sécurité des threads sont gérées par
``ssh.connection.Connection``.
"""

import os
import socket
import stat

import paramiko

from ssh.text import decode_bytes


class SSHError(Exception):
    """Erreur réseau / authentification lisible côté UI."""


class SSHClient:
    def __init__(self):
        self.client = None

    # ------------------------------------------------------------------ #
    # Connexion
    # ------------------------------------------------------------------ #
    def connect(self, host, username, password, port=22, timeout=12):
        if not host or not username:
            raise SSHError("Hôte et utilisateur sont obligatoires.")

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            client.connect(
                hostname=host,
                port=port,
                username=username,
                password=password,
                timeout=timeout,
                banner_timeout=timeout,
                auth_timeout=timeout,
                look_for_keys=False,
                allow_agent=False,
            )
        except paramiko.AuthenticationException:
            raise SSHError("Authentification refusée : login ou mot de passe invalide.")
        except (socket.timeout, socket.gaierror) as exc:
            raise SSHError(f"Hôte injoignable : {exc}")
        except Exception as exc:  # paramiko.SSHException et autres
            raise SSHError(str(exc))

        self.client = client

    def is_active(self):
        if not self.client:
            return False
        transport = self.client.get_transport()
        return bool(transport and transport.is_active())

    # ------------------------------------------------------------------ #
    # Exécution
    # ------------------------------------------------------------------ #
    def execute(self, command, timeout=None):
        """Exécute une commande et renvoie (exit_code, stdout, stderr)."""
        if not self.is_active():
            raise SSHError("Connexion SSH inactive.")

        stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        out = decode_bytes(stdout.read())
        err = decode_bytes(stderr.read())
        return exit_code, out, err

    def open_shell_channel(self, command, get_pty=True):
        """Ouvre un canal pour streamer la sortie d'une commande longue."""
        if not self.is_active():
            raise SSHError("Connexion SSH inactive.")

        transport = self.client.get_transport()
        channel = transport.open_session()
        if get_pty:
            channel.get_pty()
        channel.exec_command(command)
        return channel

    # ------------------------------------------------------------------ #
    # SFTP
    # ------------------------------------------------------------------ #
    def read_file(self, remote_path):
        sftp = self.client.open_sftp()
        try:
            with sftp.open(remote_path, "r") as handle:
                return decode_bytes(handle.read())
        finally:
            sftp.close()

    def write_file(self, remote_path, content):
        sftp = self.client.open_sftp()
        try:
            with sftp.open(remote_path, "wb") as handle:
                handle.write(str(content).encode("utf-8"))
        finally:
            sftp.close()

    def file_exists(self, remote_path):
        sftp = self.client.open_sftp()
        try:
            sftp.stat(remote_path)
            return True
        except IOError:
            return False
        finally:
            sftp.close()

    def is_dir(self, remote_path):
        sftp = self.client.open_sftp()
        try:
            return stat.S_ISDIR(sftp.stat(remote_path).st_mode)
        except IOError:
            return False
        finally:
            sftp.close()

    def upload_file(self, local_file, remote_file):
        sftp = self.client.open_sftp()
        try:
            sftp.put(local_file, remote_file)
        finally:
            sftp.close()

    @staticmethod
    def _sftp_mkdirs(sftp, remote_dir):
        """Crée ``remote_dir`` et ses parents (équivalent ``mkdir -p``)."""
        parts = remote_dir.strip("/").split("/")
        path = "" if remote_dir.startswith("/") else "."
        for part in parts:
            path = f"{path}/{part}" if path else part
            try:
                sftp.stat(path)
            except IOError:
                sftp.mkdir(path)

    def upload_dir(self, local_dir, remote_dir, progress=None):
        """Téléverse récursivement ``local_dir`` dans ``remote_dir``.

        ``progress`` : callable(str) optionnel appelé à chaque fichier
        téléversé (chemin distant), pour un retour live côté UI."""
        sftp = self.client.open_sftp()
        try:
            self._sftp_mkdirs(sftp, remote_dir)
            for root, _dirs, files in os.walk(local_dir):
                rel = os.path.relpath(root, local_dir)
                rdir = remote_dir if rel == "." else (
                    remote_dir + "/" + rel.replace(os.sep, "/"))
                self._sftp_mkdirs(sftp, rdir)
                for name in files:
                    rpath = rdir + "/" + name
                    sftp.put(os.path.join(root, name), rpath)
                    if progress:
                        progress(rpath)
        finally:
            sftp.close()

    # ------------------------------------------------------------------ #
    def close(self):
        if self.client:
            self.client.close()
            self.client = None
