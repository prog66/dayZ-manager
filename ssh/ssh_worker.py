"""Workers Qt : exécutent des opérations SSH hors du thread UI.

Utilisent la connexion partagée et persistante (``ssh.connection``).
"""

from PyQt6.QtCore import QThread, pyqtSignal

from ssh.connection import connection
from ssh.ssh_client import SSHError


class SSHWorker(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, command, timeout=120):
        super().__init__()
        self.command = command
        self.timeout = timeout

    def run(self):
        try:
            exit_code, out, err = connection.execute(self.command, timeout=self.timeout)
        except SSHError as exc:
            self.error.emit(str(exc))
            return
        except Exception as exc:  # pragma: no cover - garde-fou
            self.error.emit(str(exc))
            return

        result = out or ""
        if err:
            result = (result + "\n" + err).strip()

        if exit_code == 0:
            self.finished.emit(result)
        else:
            self.error.emit(result or f"Code de sortie {exit_code}")


class FuncWorker(QThread):
    """Exécute un callable (typiquement des opérations SFTP) hors UI.

    Émet ``finished(object)`` avec la valeur de retour, ou ``error(str)``.
    """

    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self._func = func
        self._args = args
        self._kwargs = kwargs

    def run(self):
        try:
            result = self._func(*self._args, **self._kwargs)
        except SSHError as exc:
            self.error.emit(str(exc))
        except Exception as exc:
            self.error.emit(str(exc))
        else:
            self.finished.emit(result)
