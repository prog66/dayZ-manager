"""Mission import wizard with responsive progress and explicit replacement."""

from pathlib import Path
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QFileDialog, QCheckBox, QProgressBar, QPlainTextEdit,
)
from ssh.ssh_worker import FuncWorker
from managers.mission_import import import_source


class ImportWorker(FuncWorker):
    progress = pyqtSignal(int, int, str)

    def __init__(self, cfg, source, name, replace):
        super().__init__(lambda: import_source(cfg, source, name, replace, self.progress.emit))


class MissionImportDialog(QDialog):
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.worker = None
        self.result_data = None
        self.setWindowTitle("Importer une mission")
        self.resize(680, 490)
        layout = QVBoxLayout(self)
        title = QLabel("Votre mission, prête à installer")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        hint = QLabel("Choisis un dossier ou un ZIP. Le nom et la mission Alteria sont détectés automatiquement.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.source = QLineEdit()
        self.source.setPlaceholderText("Dossier de mission ou archive .zip")
        layout.addWidget(self.source)
        choices = QHBoxLayout()
        self.folder_btn = QPushButton("Choisir un dossier")
        self.zip_btn = QPushButton("Choisir un ZIP")
        self.folder_btn.clicked.connect(self.choose_folder)
        self.zip_btn.clicked.connect(self.choose_zip)
        choices.addWidget(self.folder_btn)
        choices.addWidget(self.zip_btn)
        layout.addLayout(choices)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Nom serveur : automatique (modifiable)")
        layout.addWidget(self.name)
        destination = QLabel(f"Destination : {cfg['lgsm_path'].rstrip('/')}/serverfiles/mpmissions")
        destination.setWordWrap(True)
        layout.addWidget(destination)
        self.replace = QCheckBox("Remplacer une mission existante en conservant une copie de sauvegarde")
        layout.addWidget(self.replace)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        self.messages = QPlainTextEdit()
        self.messages.setReadOnly(True)
        self.messages.setMaximumBlockCount(500)
        layout.addWidget(self.messages)
        actions = QHBoxLayout()
        self.close_btn = QPushButton("Fermer")
        self.close_btn.clicked.connect(self.reject)
        self.start_btn = QPushButton("Importer la mission")
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self.start)
        actions.addWidget(self.close_btn)
        actions.addStretch()
        actions.addWidget(self.start_btn)
        layout.addLayout(actions)

    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Mission extraite", str(Path.home() / "Downloads"))
        if path:
            self.source.setText(path)

    def choose_zip(self):
        path, _ = QFileDialog.getOpenFileName(self, "Archive de mission", str(Path.home() / "Downloads"), "Archive ZIP (*.zip)")
        if path:
            self.source.setText(path)

    def start(self):
        if not self.source.text().strip():
            self.messages.appendPlainText("Choisis d'abord un dossier ou un ZIP.")
            return
        self.result_data = None
        self._busy(True)
        self.worker = ImportWorker(self.cfg, self.source.text().strip(), self.name.text(), self.replace.isChecked())
        self.worker.progress.connect(self.update_progress)
        self.worker.completed.connect(self.succeeded)
        self.worker.error.connect(self.failed)
        self.worker.finished.connect(self.finished_worker)
        self.worker.start()

    def _busy(self, busy):
        for widget in (self.source, self.name, self.replace, self.folder_btn,
                       self.zip_btn, self.close_btn, self.start_btn):
            widget.setEnabled(not busy)

    def update_progress(self, count, total, text):
        self.progress.setRange(0, total)
        self.progress.setValue(count)
        self.messages.appendPlainText(f"{count}/{total} · {text}" if total else text)

    def succeeded(self, result):
        self.result_data = result
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.messages.appendPlainText(f"Import terminé : {result['files']} fichiers vers {result['destination']}")
        if result['backup']:
            self.messages.appendPlainText(f"Ancienne mission conservée : {result['backup']}")
        self.messages.appendPlainText("Tu peux maintenant sélectionner cette mission dans Carte.")

    def failed(self, error):
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.messages.appendPlainText(f"Échec de l'import : {error}")

    def finished_worker(self):
        self._busy(False)
        self.worker.deleteLater()
        self.worker = None

    def reject(self):
        if self.worker is not None:
            return
        super().reject()

    def closeEvent(self, event):
        if self.worker is not None:
            event.ignore()
        else:
            super().closeEvent(event)
