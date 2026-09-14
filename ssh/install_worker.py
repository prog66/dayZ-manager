"""Worker Qt streamant l'installation / mise à jour de mods en temps réel.

Ouvre un canal SSH dédié (PTY) et streame la sortie du script SteamCMD
ligne par ligne, sans bloquer l'UI **ni monopoliser la connexion
partagée** : contrairement à ``connection.execute`` (qui retient le verrou
pendant toute la commande), ``open_shell_channel`` ne le tient que le
temps de l'ouverture, puis le stream lit sur son propre canal.

Le script (``commands.install_mods``) émet des marqueurs
``@@DZM@@<TYPE>|<champs>`` que ce worker traduit en signaux Qt typés, pour
un retour visuel précis (étape courante, succès, échec, bilan final).
"""

from PyQt6.QtCore import QThread, pyqtSignal

from managers.commands import INSTALL_MARK
from ssh.connection import connection
from ssh.ssh_client import SSHError


class InstallWorker(QThread):
    line = pyqtSignal(str)            # ligne de sortie brute (log live)
    step = pyqtSignal(int, int, str)  # (index, total, mod_id)
    mod_ok = pyqtSignal(str, str)     # (mod_id, @nom)
    mod_fail = pyqtSignal(str, str)   # (mod_id, raison)
    done = pyqtSignal(int, int)       # (réussis, échoués)
    error = pyqtSignal(str)

    def __init__(self, command):
        super().__init__()
        self.command = command
        self._running = True
        self._channel = None

    def stop(self):
        self._running = False
        if self._channel is not None:
            try:
                self._channel.close()
            except Exception:
                pass

    def run(self):
        try:
            self._channel = connection.open_shell_channel(self.command, get_pty=True)
        except SSHError as exc:
            self.error.emit(str(exc))
            return
        except Exception as exc:  # pragma: no cover - garde-fou
            self.error.emit(str(exc))
            return

        self._channel.settimeout(0.5)
        buffer = b""
        saw_done = False

        while self._running:
            try:
                if self._channel.recv_ready():
                    chunk = self._channel.recv(4096)
                    if not chunk:
                        break
                    # La progression SteamCMD se termine par `\r` : on la
                    # traite comme une fin de ligne pour un affichage live.
                    chunk = chunk.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
                    buffer += chunk
                    *lines, buffer = buffer.split(b"\n")
                    for raw in lines:
                        if self._dispatch(raw.decode(errors="ignore")):
                            saw_done = True
                            self._running = False
                            break
                elif self._channel.exit_status_ready():
                    break
                else:
                    self.msleep(60)
            except Exception:
                break

        if buffer:
            if self._dispatch(buffer.decode(errors="ignore")):
                saw_done = True

        try:
            self._channel.close()
        except Exception:
            pass

        # Le script s'est terminé sans bilan : interruption ou erreur shell.
        if not saw_done and self._running:
            self.error.emit("Installation interrompue avant la fin.")

    def _dispatch(self, text):
        """Traduit une ligne. Renvoie True si c'était le marqueur DONE."""
        stripped = text.strip()
        if INSTALL_MARK in stripped:
            payload = stripped.split(INSTALL_MARK, 1)[1]
            kind, _, rest = payload.partition("|")
            parts = rest.split("|")
            if kind == "STEP" and len(parts) >= 3:
                try:
                    self.step.emit(int(parts[0]), int(parts[1]), parts[2])
                except ValueError:
                    pass
            elif kind == "OK" and len(parts) >= 2:
                self.mod_ok.emit(parts[0], parts[1])
            elif kind == "FAIL" and len(parts) >= 2:
                self.mod_fail.emit(parts[0], parts[1])
            elif kind == "DONE" and len(parts) >= 2:
                try:
                    self.done.emit(int(parts[0]), int(parts[1]))
                except ValueError:
                    self.done.emit(0, 0)
                return True
            return False

        if stripped:
            self.line.emit(text.rstrip())
        return False
