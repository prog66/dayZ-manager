"""Worker Qt pour la console *live*.

Ouvre un canal SSH dédié et streame la sortie d'une commande longue
(``./dayzserver console`` ou un ``tail -f`` de log) en temps réel, ligne
par ligne, sans bloquer l'UI. S'arrête proprement via ``stop()``.
"""

import socket

from PyQt6.QtCore import QThread, pyqtSignal

from ssh.connection import connection
from ssh.ssh_client import SSHError
from ssh.text import decode_bytes


class ConsoleWorker(QThread):
    output = pyqtSignal(str)
    error = pyqtSignal(str)
    stopped = pyqtSignal()
    # (code de sortie, interrompue par l'utilisateur). ``code=-1`` signifie
    # qu'aucun code fiable n'a pu être récupéré.
    command_finished = pyqtSignal(int, bool)

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
            self.command_finished.emit(-1, False)
            self.stopped.emit()
            return
        except Exception as exc:  # pragma: no cover
            self.error.emit(str(exc))
            self.command_finished.emit(-1, False)
            self.stopped.emit()
            return

        self._channel.settimeout(0.5)
        buffer = b""
        failed = False

        while self._running:
            try:
                if self._channel.recv_ready():
                    chunk = self._channel.recv(4096)
                    if not chunk:
                        break
                    # LinuxGSM anime sa progression avec ``\r`` ; dans une
                    # interface graphique chaque état doit devenir une ligne.
                    chunk = chunk.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
                    buffer += chunk
                    # On émet des lignes complètes pour un rendu propre.
                    *lines, buffer = buffer.split(b"\n")
                    for line in lines:
                        text = decode_bytes(line)
                        if text:
                            self.output.emit(text)
                elif self._channel.exit_status_ready():
                    break
                else:
                    self.msleep(80)
            except socket.timeout:
                # Une lecture PTY peut expirer sans que la commande ait fini.
                continue
            except Exception as exc:
                failed = True
                if self._running:
                    self.error.emit(str(exc))
                break

        if buffer:
            text = decode_bytes(buffer)
            if text:
                self.output.emit(text)

        try:
            interrupted = not self._running
            if interrupted or failed:
                code = -1
            elif not self._channel.exit_status_ready():
                # Le canal peut se fermer sans fournir de statut SSH.
                code = -1
            else:
                code = self._channel.recv_exit_status()
            self.command_finished.emit(code, interrupted)
        except Exception as exc:
            if self._running:
                self.error.emit(str(exc))
            self.command_finished.emit(-1, not self._running)
        finally:
            try:
                self._channel.close()
            except Exception:
                pass

        self.stopped.emit()
