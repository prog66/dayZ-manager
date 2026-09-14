"""Fenêtre de progression d'installation / mise à jour de mods.

Retour temps réel : barre de progression, étape courante, log live et
bilan coloré (réussis / échecs). Réutilisable pour un mod unique, une
liste, une collection ou une mise à jour groupée.
"""

from html import escape

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar, QPushButton,
    QVBoxLayout,
)

from ssh.install_worker import InstallWorker
from ui import theme


class InstallDialog(QDialog):
    # Émis une fois l'opération terminée (succès, échec partiel ou erreur),
    # pour que l'appelant rafraîchisse la liste des mods.
    finished_ok = pyqtSignal()

    def __init__(self, parent, command, total, title="Installation de mods",
                 names=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(740, 480)

        self._names = names or {}   # {id Workshop -> nom lisible}
        self._total = max(1, total)
        self._ok = []
        self._fail = []
        self._finished = False

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        self.status = QLabel("Préparation…")
        self.status.setStyleSheet("font-size: 12pt; font-weight: 700;")
        root.addWidget(self.status)

        self.bar = QProgressBar()
        self.bar.setRange(0, self._total)
        self.bar.setValue(0)
        self.bar.setFormat("%v / %m mod(s)")
        root.addWidget(self.bar)

        self.logview = QPlainTextEdit()
        self.logview.setReadOnly(True)
        self.logview.setMaximumBlockCount(8000)
        self.logview.setStyleSheet(
            f"background:{theme.BG}; color:#9fb4c9; "
            "font-family:Consolas, monospace; font-size:9pt; border:none;"
        )
        root.addWidget(self.logview, 1)

        btn_row = QHBoxLayout()
        self.summary = QLabel("")
        self.summary.setStyleSheet(f"color:{theme.MUTED};")
        btn_row.addWidget(self.summary, 1)
        self.close_btn = QPushButton("Annuler")
        self.close_btn.setObjectName("danger")
        self.close_btn.clicked.connect(self._on_button)
        btn_row.addWidget(self.close_btn)
        root.addLayout(btn_row)

        self.worker = InstallWorker(command)
        self.worker.line.connect(self._on_line)
        self.worker.step.connect(self._on_step)
        self.worker.mod_ok.connect(self._on_ok)
        self.worker.mod_fail.connect(self._on_fail)
        self.worker.done.connect(self._on_done)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    # ------------------------------------------------------------------ #
    def _append(self, text, color=None):
        if color:
            self.logview.appendHtml(
                f'<span style="color:{color}; white-space:pre-wrap;">{escape(text)}</span>'
            )
        else:
            self.logview.appendPlainText(text)
        self.logview.moveCursor(QTextCursor.MoveOperation.End)

    def _on_line(self, text):
        self._append(text)

    def _on_step(self, index, total, mod_id):
        self.bar.setMaximum(total)
        self.bar.setValue(index - 1)
        label = self._names.get(str(mod_id))
        who = f"{label} ({mod_id})" if label else f"mod {mod_id}"
        self.status.setText(f"[{index}/{total}] Téléchargement : {who}…")

    def _on_ok(self, mod_id, name):
        self._ok.append(name)
        self.bar.setValue(min(self.bar.value() + 1, self.bar.maximum()))
        self._append(f"✔ {name} installé.", theme.GREEN_HOVER)

    def _on_fail(self, mod_id, reason):
        self._fail.append(mod_id)
        self.bar.setValue(min(self.bar.value() + 1, self.bar.maximum()))
        self._append(f"✗ {mod_id} — {reason}", theme.RED_HOVER)

    def _on_done(self, ok, fail):
        if fail:
            self._finish(f"Terminé : {ok} réussi(s), {fail} échec(s).",
                         theme.AMBER if ok else theme.RED)
        else:
            self._finish(f"Terminé : {ok} mod(s) installé(s).", theme.GREEN_HOVER)

    def _on_error(self, message):
        self._append(f"[ERREUR] {message}", theme.RED_HOVER)
        self._finish(f"Interrompu : {message}", theme.RED)

    def _finish(self, message, color):
        if self._finished:
            return
        self._finished = True
        self.bar.setValue(self.bar.maximum())
        self.status.setText(message)
        self.status.setStyleSheet(
            f"font-size: 12pt; font-weight: 700; color:{color};"
        )
        self.summary.setText("Opération terminée — tu peux fermer cette fenêtre.")
        self.close_btn.setText("Fermer")
        self.finished_ok.emit()

    # ------------------------------------------------------------------ #
    def _on_button(self):
        if not self._finished:
            self._stop_worker()
        self.accept()

    def _stop_worker(self):
        if self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(3000)

    def closeEvent(self, event):
        self._stop_worker()
        super().closeEvent(event)
