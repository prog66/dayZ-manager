"""Bas niveau : un client SSH/SFTP fin au-dessus de paramiko.

Cette classe reste volontairement simple : une connexion = un client.
La réutilisation et la sécurité des threads sont gérées par
``ssh.connection.Connection``.
"""

import os
import socket
import stat
import errno
import posixpath
import time
import uuid

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
        from managers.config_manager import APP_DATA_DIR
        known_hosts = APP_DATA_DIR / "known_hosts"
        client.load_system_host_keys()
        if known_hosts.exists():
            client.load_host_keys(str(known_hosts))
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
            client.close()
            raise SSHError("Authentification refusée : login ou mot de passe invalide.")
        except (socket.timeout, socket.gaierror) as exc:
            client.close()
            raise SSHError(f"Hôte injoignable : {exc}")
        except Exception as exc:  # paramiko.SSHException et autres
            client.close()
            raise SSHError(str(exc))

        try:
            client.save_host_keys(str(known_hosts))
            client.get_transport().set_keepalive(30)
        except Exception:
            client.close()
            raise
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
        channel = stdout.channel
        out, err = bytearray(), bytearray()
        deadline = time.monotonic() + (timeout if timeout is not None else 120)
        try:
            stdin.close()
            while True:
                # Drain both streams before waiting for the exit status. Large
                # outputs otherwise fill the SSH window and deadlock the server.
                if channel.recv_ready():
                    out.extend(channel.recv(65536))
                if channel.recv_stderr_ready():
                    err.extend(channel.recv_stderr(65536))
                if (channel.exit_status_ready() and not channel.recv_ready()
                        and not channel.recv_stderr_ready()):
                    return channel.recv_exit_status(), decode_bytes(bytes(out)), decode_bytes(bytes(err))
                if time.monotonic() >= deadline:
                    raise SSHError("Délai SSH dépassé ; vérifie le résultat côté serveur avant de relancer.")
                time.sleep(0.01)
        finally:
            channel.close()

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
        temporary = None
        try:
            try:
                attributes = sftp.stat(remote_path)
                mode = stat.S_IMODE(attributes.st_mode)
                remote_path = sftp.normalize(remote_path)
            except OSError as exc:
                if exc.errno != errno.ENOENT:
                    raise
                mode = 0o600
            temporary = f"{remote_path}.tmp-{uuid.uuid4().hex}"
            with sftp.open(temporary, "wb") as handle:
                handle.write(str(content).encode("utf-8"))
                handle.flush()
            sftp.chmod(temporary, mode)
            sftp.posix_rename(temporary, remote_path)
            temporary = None
        finally:
            if temporary:
                try:
                    sftp.remove(temporary)
                except OSError:
                    pass
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
        remote_dir = str(remote_dir).replace("\\", "/")
        is_absolute = remote_dir.startswith("/")
        parts = [part for part in remote_dir.strip("/").split("/") if part]
        # SFTP distingue ``/home/user/...`` de ``home/user/...``. Le second
        # chemin est relatif au répertoire courant du compte SSH et provoquait
        # Errno 2 sur les chemins Linux absolus utilisés par LGSM.
        path = "/" if is_absolute else "."
        for part in parts:
            path = f"{path.rstrip('/')}/{part}" if path != "." else f"./{part}"
            try:
                sftp.stat(path)
            except IOError as exc:
                if exc.errno != errno.ENOENT:
                    raise
                sftp.mkdir(path)

    def upload_dir(self, local_dir, remote_dir, progress=None):
        """Téléverse récursivement ``local_dir`` dans ``remote_dir``.

        ``progress`` : callable(str) optionnel appelé à chaque fichier
        téléversé (chemin distant), pour un retour live côté UI."""
        local_dir = os.path.abspath(os.path.expanduser(str(local_dir)))
        if not os.path.isdir(local_dir):
            raise SSHError(f"Dossier local introuvable : {local_dir}")
        remote_dir = str(remote_dir).replace("\\", "/").rstrip("/")

        sftp = self.client.open_sftp()
        try:
            self._sftp_mkdirs(sftp, remote_dir)
            def walk_error(exc):
                raise exc

            for root, _dirs, files in os.walk(local_dir, onerror=walk_error):
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

    def import_mission(self, local_dir, remote_dir, replace=False, progress=None):
        """Publish a complete mission; preserve an existing mission as a backup.

        A failed upload leaves only a staging directory, never a partially
        replaced live mission. Staging is retained for diagnosis on failure.
        """
        from pathlib import Path
        source = Path(local_dir)
        if not (source / "init.c").is_file():
            raise SSHError("Mission invalide : init.c manquant.")
        if not remote_dir.startswith("/"):
            raise SSHError("Le chemin LGSM doit être absolu (exemple : /home/florent).")
        for entry in source.rglob("*"):
            if entry.is_symlink():
                raise SSHError(f"Lien symbolique non accepté dans la mission : {entry.name}")
        token = uuid.uuid4().hex[:12]
        parent = posixpath.dirname(remote_dir)
        staging = f"{parent}/.import-{token}"
        backup = f"{remote_dir}.backup-{token}"
        sftp = self.client.open_sftp()
        moved_old = False
        try:
            try:
                sftp.stat(remote_dir)
                exists = True
            except OSError as exc:
                if exc.errno != errno.ENOENT:
                    raise
                exists = False
            if exists and not replace:
                raise SSHError("Cette mission existe déjà. Autorise son remplacement avec sauvegarde ou choisis un autre nom.")
            self.upload_dir(str(source), staging, progress)
            sftp.stat(f"{staging}/init.c")
            if exists:
                sftp.rename(remote_dir, backup)
                moved_old = True
            try:
                sftp.rename(staging, remote_dir)
            except OSError:
                if moved_old:
                    sftp.rename(backup, remote_dir)
                raise
            return {"destination": remote_dir, "backup": backup if moved_old else ""}
        except OSError as exc:
            raise SSHError(f"Import impossible vers {remote_dir} : {exc}. Dossier temporaire éventuel : {staging}") from exc
        finally:
            sftp.close()

    # ------------------------------------------------------------------ #
    def close(self):
        if self.client:
            self.client.close()
            self.client = None
