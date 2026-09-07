"""Fenêtre principale de DayZ Manager.

Barre latérale de navigation + pages empilées :
Tableau de bord · Serveur · Configuration · Mods · Cartes · Console ·
Sauvegardes · Réglages · À propos.
"""

import difflib
import os
from functools import partial
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer, QSize, QUrl
from PyQt6.QtGui import QPixmap, QDesktopServices, QColor, QBrush
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QFrame, QLabel, QPushButton, QLineEdit, QListWidget,
    QListWidgetItem, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QCheckBox,
    QTabWidget, QStackedWidget, QScrollArea, QMessageBox, QInputDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout, QFileDialog,
)

from managers.config_manager import ConfigManager
from managers import (
    commands, cfg_editor, workshop, scheduler, types_editor, rcon, map_manager,
    profiles, notifications, permissions, updater,
)
from ssh.connection import connection
from ssh.ssh_worker import SSHWorker, FuncWorker
from ssh.console_worker import ConsoleWorker
from ui import theme
from version import APP_VERSION, GITHUB_REPOSITORY_URL

NAV = [
    ("Accueil", "build_dashboard_page"),
    ("Serveur", "build_server_hub_page"),
    ("Configuration", "build_config_hub_page"),
    ("Exploitation", "build_operations_hub_page"),
    ("Automatisation", "build_schedule_page"),
    ("Réglages", "build_settings_hub_page"),
]

class Dashboard(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"DayZ Manager v{APP_VERSION}")
        self.resize(1280, 820)
        self.setMinimumSize(1040, 680)

        self.workers = []
        self.console_worker = None
        self.log_tail_worker = None
        self.op_worker = None        # opération serveur longue en streaming live
        self._mods_loading = False
        self._serverdz_content = ""
        self._ws_items = []        # (id, mtime_epoch, @nom) du cache SteamCMD
        self._mod_ids = {}         # @nom -> id Workshop
        self._mod_updates = {}     # @nom -> id Workshop (MAJ disponible)
        self._map_mods = []        # mods @ installés, rafraîchis par la page Cartes
        self._map_missions = []    # missions disponibles sous mpmissions
        self._active_map_template = ""
        self._map_profiles = {}
        self._dashboard_runtime_status = ""
        self._last_dashboard_server_online = None
        self._tab_targets = {}
        self._group_indices = {}
        self._available_update = None
        self._pending_update = None
        self._update_check_running = False

        self.apply_connection()
        self._build_ui()
        self.setStyleSheet(theme.STYLESHEET)

        self.nav.setCurrentRow(0)

        self.stats_timer = QTimer(self)
        self.stats_timer.timeout.connect(self.refresh_server_stats)
        self._configure_timer()
        self.refresh_server_stats()
        QTimer.singleShot(1500, self._auto_check_for_updates)

    # ================================================================== #
    # Construction de l'ossature
    # ================================================================== #
    def _build_ui(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)

        # --- barre latérale ---
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(224)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(14, 18, 14, 14)
        side.setSpacing(6)

        brand = QLabel("DayZ Manager")
        brand.setObjectName("brand")
        brand_sub = QLabel("Gestion serveur DayZ")
        brand_sub.setObjectName("brandSub")
        side.addWidget(brand)
        side.addWidget(brand_sub)
        side.addSpacing(14)

        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        section_label = QLabel("NAVIGATION")
        section_label.setObjectName("sectionLabel")
        side.addWidget(section_label)
        for label, _ in NAV:
            self.nav.addItem(label)
        self.nav.currentRowChanged.connect(self._on_nav)
        side.addWidget(self.nav, 1)

        self.players_badge = QLabel("👥  —")
        self.players_badge.setObjectName("playersBadge")
        self.players_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_players_badge(None)
        side.addWidget(self.players_badge)

        self.status_pill = QLabel("● Non connecté")
        self.status_pill.setObjectName("statusPill")
        self.status_pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_pill("idle")
        side.addWidget(self.status_pill)

        # --- zone de contenu ---
        self.pages = QStackedWidget()
        for index, (_, builder) in enumerate(NAV):
            page = QWidget()
            container = QVBoxLayout(page)
            container.setContentsMargins(28, 24, 28, 10)
            container.setSpacing(16)
            getattr(self, builder)(container)
            self.pages.addWidget(page)
            self._group_indices[builder] = index

        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.addWidget(self.pages, 1)

        self.toast_label = QLabel("Prêt.")
        self.toast_label.setObjectName("toast")
        toast_wrap = QHBoxLayout()
        toast_wrap.setContentsMargins(28, 0, 28, 14)
        toast_wrap.addWidget(self.toast_label, 1)
        content.addLayout(toast_wrap)

        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(sidebar)
        layout.addLayout(content, 1)

        # Charge les champs Réglages depuis la config.
        self._load_settings_fields()

    def _on_nav(self, index):
        self.pages.setCurrentIndex(index)
        # Quitter l'espace Joueurs coupe son rafraîchissement automatique.
        if hasattr(self, "players_timer"):
            self.players_timer.stop()
        if 0 <= index < len(NAV):
            self._refresh_page_builder(self._active_builder(index))

    def _active_builder(self, group_index):
        group = NAV[group_index][1]
        for builder, (owner, tabs, tab_index) in self._tab_targets.items():
            if owner == group and tabs.currentIndex() == tab_index:
                return builder
        return group

    def _refresh_page_builder(self, builder):
        """Rafraîchissement paresseux de la page actuellement visible."""
        if builder == "build_dashboard_page":
            self.refresh_server_stats()
        elif builder == "build_players_page":
            self._update_rcon_status()
            self.refresh_players()
            if self.players_auto_check.isChecked():
                self.players_timer.start(15000)
        elif builder == "build_mods_page":
            self.refresh_mods()
        elif builder == "build_maps_page":
            self.refresh_maps()
        elif builder == "build_backups_page":
            self.refresh_backups()
        elif builder == "build_config_page":
            self.load_serverdz()
        elif builder == "build_workshop_page":
            if self.ws_list.count() == 0:
                self.workshop_search(1)
        elif builder == "build_schedule_page":
            self.view_schedule()
        elif builder == "build_logs_page":
            if self.log_list.count() == 0:
                self.refresh_logs()
        elif builder == "build_types_page":
            if self.types_file_combo.count() == 0:
                self.refresh_types_files()
        elif builder == "build_files_page":
            self.load_launch_params()
            if self.econ_file_combo.count() == 0:
                self.refresh_files()

    def _on_subtab(self, tabs, index):
        for builder, (owner, owner_tabs, tab_index) in self._tab_targets.items():
            if owner_tabs is tabs and tab_index == index:
                if self.nav.currentRow() == self._group_indices.get(owner):
                    if hasattr(self, "players_timer"):
                        self.players_timer.stop()
                    self._refresh_page_builder(builder)
                return

    def _add_tabbed_group(self, layout, tabs_data):
        """Ajoute un espace de travail avec des sous-onglets explicites."""
        tabs = QTabWidget()
        tabs.setObjectName("sectionTabs")
        tabs.setDocumentMode(True)
        owner = getattr(self, "_building_group", None)
        if owner is None:
            raise RuntimeError("Un groupe d'onglets doit déclarer son propriétaire.")
        for tab_index, (title, builder) in enumerate(tabs_data):
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 4, 0, 0)
            page_layout.setSpacing(12)
            self._embedded_page = True
            getattr(self, builder)(page_layout)
            self._embedded_page = False
            tabs.addTab(page, title)
            self._tab_targets[builder] = (owner, tabs, tab_index)
        tabs.currentChanged.connect(partial(self._on_subtab, tabs))
        layout.addWidget(tabs, 1)
        return tabs

    def _group_intro(self, layout, title, subtitle):
        title_label = QLabel(title)
        title_label.setObjectName("groupTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("groupSubtitle")
        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)

    def build_server_hub_page(self, layout):
        self._building_group = "build_server_hub_page"
        self._group_intro(layout, "Serveur", "Contrôler le serveur et administrer les joueurs au même endroit.")
        self._add_tabbed_group(layout, [("Contrôle", "build_server_page"), ("Joueurs", "build_players_page")])
        self._building_group = None

    def build_config_hub_page(self, layout):
        self._building_group = "build_config_hub_page"
        self._group_intro(layout, "Configuration", "Préparer la carte, les mods et les fichiers du serveur.")
        self._add_tabbed_group(layout, [
            ("Carte", "build_maps_page"),
            ("Mods", "build_mods_page"),
            ("serverDZ.cfg", "build_config_page"),
            ("Lancement & fichiers", "build_files_page"),
            ("Économie", "build_types_page"),
            ("Workshop", "build_workshop_page"),
        ])
        self._building_group = None

    def build_operations_hub_page(self, layout):
        self._building_group = "build_operations_hub_page"
        self._group_intro(layout, "Exploitation", "Suivre les opérations, les journaux et les sauvegardes.")
        self._add_tabbed_group(layout, [
            ("Opérations", "build_console_page"),
            ("Journaux", "build_logs_page"),
            ("Sauvegardes", "build_backups_page"),
        ])
        self._building_group = None

    def build_settings_hub_page(self, layout):
        self._building_group = "build_settings_hub_page"
        self._group_intro(layout, "Réglages", "Connexion, notifications, profils et informations de l’application.")
        self._add_tabbed_group(layout, [("Préférences", "build_settings_page"), ("À propos", "build_about_page")])
        self._building_group = None

    # ----- en-tête de page réutilisable -----
    def _header(self, layout, title, subtitle):
        if getattr(self, "_embedded_page", False):
            return
        t = QLabel(title)
        t.setObjectName("pageTitle")
        s = QLabel(subtitle)
        s.setObjectName("pageSubtitle")
        layout.addWidget(t)
        layout.addWidget(s)

    @staticmethod
    def _panel():
        p = QFrame()
        p.setObjectName("panel")
        return p

    # ================================================================== #
    # Connexion & helpers workers
    # ================================================================== #
    def current_config(self):
        return ConfigManager.load()

    def apply_connection(self):
        cfg = self.current_config()
        connection.configure(cfg["host"], cfg["user"], cfg["password"], cfg["port"])

    def _track(self, worker):
        worker.finished.connect(lambda *_: self._untrack(worker))
        worker.error.connect(lambda *_: self._untrack(worker))
        self.workers.append(worker)
        worker.start()
        return worker

    def _untrack(self, worker):
        if worker in self.workers:
            self.workers.remove(worker)

    def run_cmd(self, command, ok=None, err=None, timeout=120):
        worker = SSHWorker(command, timeout=timeout)
        worker.finished.connect(self._on_link_ok)
        worker.error.connect(self._on_link_err)
        worker.finished.connect(ok if ok else self.log)
        worker.error.connect(err if err else (lambda e: self.log(f"[ERREUR] {e}")))
        return self._track(worker)

    def _run_streamed(self, command, label, on_done=None, sink=None,
                      done_toast=True):
        """Exécute une commande longue avec **sortie live**.

        Comme l'install, le flux passe par un canal SSH dédié (PTY) qui ne
        retient pas le verrou de la connexion : la sortie s'affiche ligne
        par ligne au lieu d'apparaître d'un bloc à la fin. Une seule
        opération longue à la fois (verrou ``op_worker``).

        ``sink``       : callable(str) recevant chaque ligne (défaut : le
                         journal serveur ``self.log``).
        ``done_toast`` : affiche un toast « terminé » en fin d'opération.
        """
        if self.op_worker is not None and self.op_worker.isRunning():
            self.toast("Une opération est déjà en cours…", "info")
            return None

        out = sink or self.log
        worker = ConsoleWorker(command)
        stream_failed = False
        result = {"code": -1, "interrupted": False}

        def _stream_error(message):
            nonlocal stream_failed
            stream_failed = True
            out(f"[ERREUR] {message}")
            self.toast(f"{label} : {message}", "error")
            self._on_link_err(message)

        worker.output.connect(out)
        worker.error.connect(_stream_error)

        def _record_result(exit_code, interrupted):
            result["code"] = exit_code
            result["interrupted"] = interrupted

        def _finished():
            if stream_failed:
                return
            exit_code = result["code"]
            interrupted = result["interrupted"]
            if interrupted:
                self.toast(f"« {label} » interrompu.", "warn")
                return
            if exit_code != 0:
                message = f"Code de sortie {exit_code}"
                out(f"[ERREUR] {message}")
                self.toast(f"{label} : {message}", "error")
                self._on_link_err(message)
                return
            if done_toast:
                self.toast(f"« {label} » terminé.", "ok")
            self._on_link_ok()
            if on_done:
                on_done()
            if label in {"start", "stop", "restart", "update"}:
                self._notify(
                    f"DayZ Manager — {label}",
                    f"L'opération serveur « {label} » s'est terminée avec succès.",
                )

        worker.command_finished.connect(_record_result)
        # ``command_finished`` est émis avant le retour de QThread ; on
        # enchaîne donc l'action suivante seulement après ``stopped``.
        worker.stopped.connect(_finished)
        self.op_worker = worker
        return self._track(worker)

    def run_func(self, func, ok=None, err=None):
        worker = FuncWorker(func)
        worker.finished.connect(self._on_link_ok)
        worker.error.connect(self._on_link_err)
        if ok:
            worker.finished.connect(ok)
        worker.error.connect(err if err else (lambda e: self.log(f"[ERREUR] {e}")))
        return self._track(worker)

    def run_net(self, func, ok=None, err=None):
        """Comme run_func mais pour des appels HTTP (n'altère pas l'état SSH)."""
        worker = FuncWorker(func)
        if ok:
            worker.finished.connect(ok)
        worker.error.connect(err if err else (lambda e: self.toast(str(e), "error")))
        return self._track(worker)

    def _require_config(self):
        cfg = self.current_config()
        if not cfg["host"] or not cfg["user"]:
            self.toast("Configure d'abord la connexion SSH (Réglages).", "error")
            return None
        return cfg

    def _allow(self, action):
        """Bloque les actions sensibles selon le rôle local choisi."""
        role = self.current_config().get("user_role", "admin")
        if permissions.can(role, action):
            return True
        required = "administrateur" if action in {"security", "restore", "server_update"} else "opérateur"
        self.toast(
            f"Action réservée au rôle {required} ({permissions.role_label(role)}).",
            "warn",
        )
        return False

    def _notify(self, subject, message):
        cfg = self.current_config()
        if not (cfg.get("discord_webhook") or cfg.get("notification_email_enabled")):
            return
        self.run_net(
            partial(notifications.send, cfg, subject, message),
            err=lambda e: self.log(f"[NOTIFICATION] {e}"),
        )

    def _run_install(self, cfg, ids, title, on_done=None, names=None):
        """Lance une install/màj de mods avec retour temps réel (modal).

        ``names`` : dict optionnel {id Workshop -> nom lisible}, affiché à la
        place de l'ID pendant le téléchargement quand on le connaît.

        Le stream passe par un canal SSH dédié qui ne retient pas le verrou
        de la connexion : on suspend tout de même l'auto-refresh des stats
        pendant l'opération pour limiter le bruit, puis on le rétablit.
        """
        from ui.install_dialog import InstallDialog

        command = commands.install_mods(cfg, ids)
        self.stats_timer.stop()
        dlg = InstallDialog(self, command, total=len(ids), title=title, names=names)
        dlg.finished_ok.connect(lambda: self._after_install(on_done))
        try:
            dlg.exec()
        finally:
            self._configure_timer()  # rétablit l'auto-refresh selon la config

    def _after_install(self, on_done=None):
        self.refresh_mods()
        if on_done:
            on_done()

    # ----- état de connexion / toasts / log -----
    def _set_pill(self, state):
        styles = {
            "idle": (theme.MUTED, "● Non connecté"),
            "connecting": (theme.AMBER, "● Connexion…"),
            "connected": (theme.GREEN, "● Connecté"),
            "error": (theme.RED, "● Déconnecté"),
        }
        color, text = styles[state]
        self.status_pill.setText(text)
        self.status_pill.setStyleSheet(
            f"background: {color}22; color: {color}; border: 1px solid {color};"
        )

    def _set_players_badge(self, count):
        """Badge « joueurs en ligne » de la barre latérale.

        ``count`` = None ⇒ indisponible (RCON désactivée ou injoignable).
        """
        if count is None:
            text, color = "👥  —", theme.MUTED
            self.players_badge.setToolTip(
                "Active la RCON (Planification) pour voir les joueurs en ligne."
            )
        else:
            text = f"👥  {count} en ligne"
            color = theme.GREEN if count > 0 else theme.MUTED
            self.players_badge.setToolTip("Joueurs actuellement connectés (RCON).")
        self.players_badge.setText(text)
        self.players_badge.setStyleSheet(
            f"background: {color}22; color: {color}; border: 1px solid {color}; "
            "border-radius: 10px; padding: 5px 8px; font-weight: 700;"
        )

    def _refresh_players_badge(self):
        """Met à jour le badge en arrière-plan (poll RCON léger).

        Utilise ``run_net`` pour ne PAS altérer le voyant de connexion SSH
        (une erreur RCON ne signifie pas que le SSH est tombé).
        """
        cfg = self.current_config()
        if not (cfg.get("rcon_enabled") and cfg.get("rcon_password")
                and cfg["host"] and cfg["user"]):
            self._set_players_badge(None)
            return
        self.run_net(
            partial(rcon.list_players, cfg),
            ok=lambda players: self._set_players_badge(len(players)),
            err=lambda _e: self._set_players_badge(None),
        )

    def _on_link_ok(self, *_):
        self._set_pill("connected")

    def _on_link_err(self, message):
        text = str(message).lower()
        if any(k in text for k in ("injoignable", "inactive", "refus", "non configur",
                                   "timed out", "connection", "auth")):
            self._set_pill("error")

    def toast(self, message, kind="info"):
        palette = {
            "info": (theme.MUTED, "ℹ️"),
            "ok": (theme.GREEN, "✅"),
            "warn": (theme.AMBER, "⚠️"),
            "error": (theme.RED, "⛔"),
        }
        color, icon = palette.get(kind, palette["info"])
        self.toast_label.setStyleSheet(
            f"background: {theme.SURFACE}; border: 1px solid {color}; "
            f"border-radius: 10px; padding: 8px 14px; color: {color};"
        )
        self.toast_label.setText(f"{icon}  {message}")
        # Auto-effacement : les erreurs restent affichées plus longtemps.
        if not hasattr(self, "_toast_timer"):
            self._toast_timer = QTimer(self)
            self._toast_timer.setSingleShot(True)
            self._toast_timer.timeout.connect(self._clear_toast)
        self._toast_timer.start(8000 if kind == "error" else 4000)

    def _clear_toast(self):
        self.toast_label.setStyleSheet(
            f"background: {theme.SURFACE}; border: 1px solid {theme.BORDER}; "
            f"border-radius: 10px; padding: 8px 14px; color: {theme.MUTED};"
        )
        self.toast_label.setText("Prêt.")

    def _nav_to(self, builder):
        """Bascule sur la page dont le constructeur est ``builder``."""
        for i, (_, b) in enumerate(NAV):
            if b == builder:
                self.nav.setCurrentRow(i)
                return
        target = self._tab_targets.get(builder)
        if target is None:
            return
        owner, tabs, tab_index = target
        group_index = self._group_indices.get(owner)
        if group_index is None:
            return
        self.nav.setCurrentRow(group_index)
        tabs.setCurrentIndex(tab_index)

    def log(self, message):
        if not message:
            return
        if hasattr(self, "logs"):
            self.logs.appendPlainText(message)

    # ================================================================== #
    # PAGE — Tableau de bord
    # ================================================================== #
    def build_dashboard_page(self, layout):
        self._header(layout, "Tableau de bord",
                     "Vue d'ensemble du serveur en temps réel.")

        bar = QHBoxLayout()
        self.refresh_dash_btn = QPushButton("⟳  Actualiser")
        self.refresh_dash_btn.setObjectName("primary")
        self.refresh_dash_btn.clicked.connect(self.refresh_server_stats)
        self.last_update_label = QLabel("Jamais actualisé")
        self.last_update_label.setStyleSheet(f"color: {theme.MUTED};")
        bar.addWidget(self.refresh_dash_btn)
        bar.addStretch(1)
        bar.addWidget(self.last_update_label)
        layout.addLayout(bar)

        grid = QGridLayout()
        grid.setSpacing(14)

        self.card_status = self._make_card("État serveur", "—")
        self.card_players = self._make_card("👥 Processus", "—")
        self.card_ram = self._make_card("💾 Mémoire", "—")
        self.card_cpu = self._make_card("🖥️ CPU", "—")
        self.card_uptime = self._make_card("⏱️ Uptime", "—")
        self.card_version = self._make_card("🎮 Version DayZ", "—")
        self.card_os = self._make_card("🐧 OS", "—")
        self.card_host = self._make_card("🌐 Hôte", "—")
        self.card_map = self._make_card("🗺️ Carte active", "—")
        self.card_mod_updates = self._make_card("📦 Mods obsolètes", "—")
        self.card_last_backup = self._make_card("💾 Dernière sauvegarde", "—")
        self.card_health = self._make_card("🩺 Santé serveur", "—")

        cards = [
            # Les métriques techniques détaillées restent disponibles dans
            # l'état interne, mais l'accueil ne montre que les décisions
            # utiles au premier coup d'œil.
            self.card_status, self.card_map, self.card_players, self.card_health,
            self.card_mod_updates, self.card_last_backup, self.card_uptime,
            self.card_version,
        ]
        for i, (frame, _) in enumerate(cards):
            grid.addWidget(frame, i // 4, i % 4)
        layout.addLayout(grid)
        layout.addStretch(1)

    def _make_card(self, title, value):
        card = QFrame()
        card.setObjectName("card")
        v = QVBoxLayout(card)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(6)
        t = QLabel(title)
        t.setObjectName("cardTitle")
        val = QLabel(value)
        val.setObjectName("cardValue")
        val.setWordWrap(True)
        v.addWidget(t)
        v.addWidget(val)
        return card, val

    def _configure_timer(self):
        cfg = self.current_config()
        self.stats_timer.stop()
        if cfg.get("auto_refresh", True):
            interval = max(10, int(cfg.get("refresh_interval", 30))) * 1000
            self.stats_timer.start(interval)

    def refresh_server_stats(self):
        cfg = self.current_config()
        if not cfg["host"] or not cfg["user"]:
            self.card_status[1].setText("Non configuré")
            self._set_players_badge(None)
            return
        self.run_cmd(
            commands.server_stats(cfg),
            ok=self.update_stats,
            err=lambda e: self.toast(f"Stats indisponibles : {e}", "error"),
            timeout=40,
        )
        # Décompte des joueurs en ligne (badge latéral), en tâche de fond.
        self._refresh_players_badge()
        self.run_func(
            partial(cfg_editor.read_serverdz, cfg),
            ok=self._receive_dashboard_map,
            err=lambda e: self.card_map[1].setText("Indisponible"),
        )
        self.run_cmd(
            commands.last_backup(cfg),
            ok=self._receive_dashboard_backup,
            err=lambda e: self.card_last_backup[1].setText("Aucune"),
            timeout=20,
        )
        self.run_cmd(
            commands.server_health(cfg),
            ok=self._receive_dashboard_health,
            err=lambda e: self.card_health[1].setText("Indisponible"),
            timeout=40,
        )
        self.card_mod_updates[1].setText(
            str(len(self._mod_updates)) if self._mod_updates else "À vérifier"
        )
        self._refresh_dashboard_mod_updates(cfg)

    def _refresh_dashboard_mod_updates(self, cfg):
        self.run_cmd(
            commands.list_workshop_items(cfg),
            ok=lambda output: self._dashboard_workshop_items(cfg, output),
            err=lambda _e: None,
            timeout=40,
        )

    def _dashboard_workshop_items(self, cfg, output):
        items = []
        for line in output.splitlines():
            parts = line.split("\t")
            if len(parts) != 3 or not parts[0].strip().isdigit():
                continue
            try:
                items.append((parts[0].strip(), int(parts[1] or 0), parts[2].strip()))
            except ValueError:
                continue
        if not items:
            return
        ids = [item[0] for item in items]
        self.run_net(
            partial(workshop.get_update_times, ids),
            ok=lambda steam: self._set_dashboard_mod_updates(items, steam),
        )

    def _set_dashboard_mod_updates(self, items, steam):
        updates = {}
        for mod_id, mtime, name in items:
            info = steam.get(mod_id)
            if info and info["time_updated"] > mtime + 60:
                updates[name] = mod_id
        self._mod_updates = updates
        self.card_mod_updates[1].setText(str(len(updates)))
        if hasattr(self, "mod_list"):
            self._annotate_mod_updates()
        if hasattr(self, "map_list"):
            self._annotate_map_updates()

    def _receive_dashboard_map(self, content):
        template = cfg_editor.get_value(content, "template") or "Non définie"
        self.card_map[1].setText(template)

    def _receive_dashboard_backup(self, output):
        self.card_last_backup[1].setText(output.strip() or "Aucune")

    def _receive_dashboard_health(self, output):
        self._dashboard_runtime_status = output
        online = "SERVER=online" in output
        if self._last_dashboard_server_online is True and not online:
            self._notify(
                "DayZ Manager — serveur arrêté",
                "Le contrôle de santé a détecté que le processus DayZ est hors ligne. "
                "Le monitor LGSM peut tenter une reprise si activé.",
            )
        self._last_dashboard_server_online = online
        if "SERVER=offline" in output:
            value = "Hors ligne"
        elif "CRASH_SIGNS=0" in output:
            value = "OK"
        else:
            value = "À surveiller"
        self.card_health[1].setText(value)

    def update_stats(self, output):
        lines = [x.strip() for x in output.splitlines() if x.strip()]
        if len(lines) < 5:
            return

        online = lines[0].lower().startswith("online")
        self.card_status[1].setText("🟢 En ligne" if online else "🔴 Hors ligne")
        self.card_status[1].setStyleSheet(
            f"color: {theme.GREEN if online else theme.RED}; font-size:16pt; font-weight:800;"
        )
        self.card_players[1].setText(lines[1])
        self.card_ram[1].setText(lines[2])
        self.card_cpu[1].setText(lines[3])
        self.card_uptime[1].setText(lines[4])
        if len(lines) >= 6:
            self.card_version[1].setText(lines[5])
        if len(lines) >= 7:
            self.card_os[1].setText(lines[6])

        cfg = self.current_config()
        self.card_host[1].setText(f"{cfg['user']}@{cfg['host']}")

        from datetime import datetime
        self.last_update_label.setText(
            "Actualisé à " + datetime.now().strftime("%H:%M:%S")
        )

    # ================================================================== #
    # PAGE — Serveur
    # ================================================================== #
    def build_server_page(self, layout):
        self._header(layout, "Serveur", "Contrôle LGSM à distance (LinuxGSM).")

        panel = self._panel()
        grid = QGridLayout(panel)
        grid.setContentsMargins(16, 16, 16, 16)
        grid.setSpacing(12)

        def btn(text, obj=None):
            b = QPushButton(text)
            if obj:
                b.setObjectName(obj)
            return b

        self.start_btn = btn("▶  Démarrer", "success")
        self.stop_btn = btn("■  Arrêter", "danger")
        self.restart_btn = btn("⟳  Redémarrer", "primary")
        self.update_btn = btn("⬆  Mettre à jour")
        self.validate_btn = btn("✔  Valider les fichiers")
        self.details_btn = btn("ℹ  Détails")

        actions = [
            (self.start_btn, "start"), (self.stop_btn, "stop"),
            (self.restart_btn, "restart"), (self.update_btn, "update"),
            (self.validate_btn, "validate"), (self.details_btn, "details"),
        ]
        for i, (b, action) in enumerate(actions):
            b.clicked.connect(partial(self.server_action, action))
            grid.addWidget(b, i // 3, i % 3)
        layout.addWidget(panel)

        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setPlaceholderText("Journal des opérations…")
        self.logs.setMaximumBlockCount(8000)
        layout.addWidget(self.logs, 1)

    def server_action(self, action):
        cfg = self._require_config()
        if not cfg:
            return
        permission = "server_update" if action == "update" else "server_control"
        if not self._allow(permission):
            return
        if action == "stop":
            if QMessageBox.question(self, "Arrêter le serveur",
                                    "Confirmer l'arrêt du serveur ?") != \
                    QMessageBox.StandardButton.Yes:
                return
        if action in {"start", "restart", "update"}:
            self.toast("Vérification du compte Steam LGSM…", "info")
            self.run_func(
                partial(cfg_editor.ensure_steam_user, cfg),
                ok=lambda username: self._execute_server_action(
                    cfg, action, username
                ),
                err=lambda e: self.toast(
                    f"Compte Steam LGSM non configuré : {e}", "error"
                ),
            )
            return
        self._execute_server_action(cfg, action)

    def _execute_server_action(self, cfg, action, steam_user=None):
        if steam_user:
            self.log(f"Compte Steam LGSM vérifié : {steam_user}")
        self.log(f"> ./dayzserver {action}")
        self.toast(f"Commande « {action} » en cours…", "info")
        self._run_streamed(
            commands.server_action(cfg, action),
            action,
            on_done=partial(self._verify_server_action, cfg, action),
        )

    def _verify_server_action(self, cfg, action):
        if action not in {"start", "stop", "restart"}:
            self.refresh_server_stats()
            return
        expected_online = action != "stop"
        self.toast("Vérification de l'état réel du serveur…", "info")
        self.run_cmd(
            commands.wait_for_server_state(cfg, expected_online),
            ok=lambda output: self._server_state_checked(
                action, output, True
            ),
            err=lambda error: self._server_state_checked(
                action, error, False
            ),
            timeout=90,
        )

    def _server_state_checked(self, action, output, success):
        if output:
            self.log(output)
        self.refresh_server_stats()
        if success:
            self.toast(f"Serveur confirmé après « {action} ». ", "ok")
        else:
            self.toast(
                f"« {action} » accepté par LinuxGSM, mais l'état du processus "
                "n'est pas confirmé.",
                "warn",
            )

    # ================================================================== #
    # PAGE — Joueurs (administration live via RCON BattlEye)
    # ================================================================== #
    def build_players_page(self, layout):
        self._header(layout, "Joueurs",
                     "Administration live via RCON BattlEye : kick, ban, messages.")

        # Bandeau d'état RCON + accès direct à sa configuration (qui vit dans
        # la page Planification — pas toujours évident à trouver).
        rcon_bar = QHBoxLayout()
        self.rcon_status_label = QLabel("")
        self.rcon_status_label.setWordWrap(True)
        self.rcon_config_btn = QPushButton("⚙  Configurer la RCON")
        self.rcon_config_btn.clicked.connect(
            lambda: self._nav_to("build_schedule_page")
        )
        rcon_bar.addWidget(self.rcon_status_label, 1)
        rcon_bar.addWidget(self.rcon_config_btn)
        layout.addLayout(rcon_bar)
        self._update_rcon_status()

        # Rafraîchissement automatique de la liste (actif uniquement sur cette page).
        self.players_timer = QTimer(self)
        self.players_timer.timeout.connect(self.refresh_players)

        self.players_tabs = QTabWidget()

        # ---- Onglet « En ligne » ----
        online = QWidget()
        ov = QVBoxLayout(online)
        ov.setContentsMargins(0, 12, 0, 0)
        ov.setSpacing(12)

        bar = QHBoxLayout()
        self.refresh_players_btn = QPushButton("⟳  Actualiser")
        self.refresh_players_btn.setObjectName("primary")
        self.refresh_players_btn.clicked.connect(self.refresh_players)
        self.players_auto_check = QCheckBox("Auto (15 s)")
        self.players_auto_check.setChecked(True)
        self.players_auto_check.toggled.connect(self._on_players_auto)
        self.players_count_label = QLabel("—")
        self.players_count_label.setStyleSheet(f"color: {theme.MUTED};")
        bar.addWidget(self.refresh_players_btn)
        bar.addWidget(self.players_auto_check)
        bar.addStretch(1)
        bar.addWidget(self.players_count_label)
        ov.addLayout(bar)

        # Diffusion à tous les joueurs.
        broadcast = QHBoxLayout()
        self.broadcast_edit = QLineEdit()
        self.broadcast_edit.setPlaceholderText("Message diffusé à tous les joueurs…")
        self.broadcast_edit.returnPressed.connect(self.broadcast_message)
        self.broadcast_btn = QPushButton("📢  Diffuser")
        self.broadcast_btn.clicked.connect(self.broadcast_message)
        broadcast.addWidget(self.broadcast_edit, 1)
        broadcast.addWidget(self.broadcast_btn)
        ov.addLayout(broadcast)

        cols = ["#", "Nom", "GUID", "Ping", "IP"]
        self.players_table = QTableWidget(0, len(cols))
        self.players_table.setHorizontalHeaderLabels(cols)
        self.players_table.verticalHeader().setVisible(False)
        self.players_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.players_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.players_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.players_table.doubleClicked.connect(lambda _: self.message_player())
        header = self.players_table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for i in (0, 3, 4):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        ov.addWidget(self.players_table, 1)

        actions = QHBoxLayout()
        self.msg_player_btn = QPushButton("✉  Message privé")
        self.kick_player_btn = QPushButton("👢  Expulser")
        self.ban_player_btn = QPushButton("⛔  Bannir")
        self.ban_player_btn.setObjectName("danger")
        self.msg_player_btn.clicked.connect(self.message_player)
        self.kick_player_btn.clicked.connect(self.kick_player)
        self.ban_player_btn.clicked.connect(self.ban_player)
        actions.addWidget(self.msg_player_btn)
        actions.addWidget(self.kick_player_btn)
        actions.addWidget(self.ban_player_btn)
        actions.addStretch(1)
        ov.addLayout(actions)
        self.players_tabs.addTab(online, "En ligne")

        # ---- Onglet « Bannissements » ----
        bans = QWidget()
        bv = QVBoxLayout(bans)
        bv.setContentsMargins(0, 12, 0, 0)
        bv.setSpacing(12)

        bbar = QHBoxLayout()
        self.refresh_bans_btn = QPushButton("⟳  Actualiser")
        self.refresh_bans_btn.setObjectName("primary")
        self.offline_ban_btn = QPushButton("⛔  Ban hors-ligne")
        self.offline_ban_btn.setObjectName("danger")
        self.reload_bans_btn = QPushButton("♻  Recharger")
        self.remove_ban_btn = QPushButton("🗑  Retirer le ban")
        self.import_bans_btn = QPushButton("⬆  Importer")
        self.export_bans_btn = QPushButton("⬇  Exporter")
        self.refresh_bans_btn.clicked.connect(self.refresh_bans)
        self.offline_ban_btn.clicked.connect(self.offline_ban)
        self.reload_bans_btn.clicked.connect(self.reload_bans)
        self.remove_ban_btn.clicked.connect(self.remove_selected_ban)
        self.import_bans_btn.clicked.connect(self.import_bans)
        self.export_bans_btn.clicked.connect(self.export_bans)
        for b in (self.refresh_bans_btn, self.offline_ban_btn, self.reload_bans_btn,
                  self.remove_ban_btn, self.import_bans_btn, self.export_bans_btn):
            bbar.addWidget(b)
        bbar.addStretch(1)
        bv.addLayout(bbar)

        bcols = ["#", "Type", "Cible", "Restant", "Raison"]
        self.bans_table = QTableWidget(0, len(bcols))
        self.bans_table.setHorizontalHeaderLabels(bcols)
        self.bans_table.verticalHeader().setVisible(False)
        self.bans_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.bans_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        bheader = self.bans_table.horizontalHeader()
        bheader.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        bheader.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        for i in (0, 1, 3):
            bheader.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        bv.addWidget(self.bans_table, 1)
        self.players_tabs.addTab(bans, "Bannissements")
        self.players_tabs.currentChanged.connect(self._on_players_tab)

        layout.addWidget(self.players_tabs, 1)

        note = QLabel(
            "ℹ️ Nécessite la RCON BattlEye activée côté serveur (BEServer*.cfg) et "
            "les identifiants RCON renseignés dans Planification. Les commandes "
            "passent par SSH (RCON locale 127.0.0.1)."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {theme.MUTED}; font-size: 9.5pt;")
        layout.addWidget(note)

    def _on_players_auto(self, checked):
        active = self._active_builder(self.nav.currentRow()) if self.nav.currentRow() >= 0 else ""
        if checked and active == "build_players_page":
            self.players_timer.start(15000)
        else:
            self.players_timer.stop()

    def _on_players_tab(self, index):
        if index == 1 and self.bans_table.rowCount() == 0:
            self.refresh_bans()

    def _rcon_ready(self):
        cfg = self._require_config()
        if not cfg:
            return None
        if not cfg.get("rcon_enabled"):
            self.toast("Active la RCON dans Planification pour gérer les joueurs.",
                       "error")
            return None
        return cfg

    def _update_rcon_status(self):
        """Met à jour le bandeau d'état RCON de la page Joueurs."""
        cfg = self.current_config()
        if cfg.get("rcon_enabled") and cfg.get("rcon_password"):
            self.rcon_status_label.setText(
                f"🔌 RCON activée · port {cfg.get('rcon_port', 2310)} "
                "(commandes via SSH sur 127.0.0.1)."
            )
            self.rcon_status_label.setStyleSheet(f"color: {theme.GREEN};")
            self.rcon_config_btn.setText("⚙  Modifier la RCON")
        else:
            missing = ("activée" if not cfg.get("rcon_enabled")
                       else "complète (mot de passe manquant)")
            self.rcon_status_label.setText(
                f"⚠️ RCON non {missing} — clique « Configurer la RCON » pour "
                "renseigner port et mot de passe."
            )
            self.rcon_status_label.setStyleSheet(f"color: {theme.AMBER};")
            self.rcon_config_btn.setText("⚙  Configurer la RCON")

    def refresh_players(self):
        cfg = self.current_config()
        if not cfg["host"] or not cfg["user"]:
            return
        if not cfg.get("rcon_enabled"):
            self.players_table.setRowCount(0)
            self.players_count_label.setText("RCON désactivée (Planification)")
            self._set_players_badge(None)
            return
        self.run_func(
            partial(rcon.list_players, cfg),
            ok=self._populate_players,
            err=lambda e: (self.players_count_label.setText("—"),
                           self._set_players_badge(None),
                           self.toast(f"RCON : {e}", "error")),
        )

    def _populate_players(self, players):
        self.players_table.setRowCount(len(players))
        for row, p in enumerate(players):
            name = p["name"] + ("  (lobby)" if p["lobby"] else "")
            values = [p["num"], name, p["guid"], p["ping"], p["ip"]]
            for col, value in enumerate(values):
                self.players_table.setItem(row, col, QTableWidgetItem(str(value)))
        self.players_count_label.setText(f"{len(players)} joueur(s) en ligne")
        # Réutilise ce résultat pour le badge latéral (évite un 2e appel RCON).
        self._set_players_badge(len(players))

    def _selected_player(self):
        row = self.players_table.currentRow()
        if row < 0:
            self.toast("Sélectionne un joueur.", "error")
            return None
        num = self.players_table.item(row, 0).text()
        name = self.players_table.item(row, 1).text()
        return num, name

    def broadcast_message(self):
        cfg = self._rcon_ready()
        if not cfg:
            return
        msg = self.broadcast_edit.text().strip()
        if not msg:
            self.toast("Saisis un message à diffuser.", "error")
            return
        self.run_func(
            partial(rcon.say_all, cfg, msg),
            ok=lambda _: (self.broadcast_edit.clear(),
                          self.toast("Message diffusé.", "ok")),
            err=lambda e: self.toast(f"Échec : {e}", "error"),
        )

    def message_player(self):
        cfg = self._rcon_ready()
        if not cfg:
            return
        sel = self._selected_player()
        if not sel:
            return
        num, name = sel
        text, ok = QInputDialog.getText(self, "Message privé", f"Message à {name} :")
        if not ok or not text.strip():
            return
        self.run_func(
            partial(rcon.say_player, cfg, num, text.strip()),
            ok=lambda _: self.toast(f"Message envoyé à {name}.", "ok"),
            err=lambda e: self.toast(f"Échec : {e}", "error"),
        )

    def kick_player(self):
        cfg = self._rcon_ready()
        if not cfg:
            return
        sel = self._selected_player()
        if not sel:
            return
        num, name = sel
        reason, ok = QInputDialog.getText(
            self, "Expulser", f"Raison (optionnelle) pour expulser {name} :"
        )
        if not ok:
            return
        self.run_func(
            partial(rcon.kick, cfg, num, reason.strip()),
            ok=lambda _: (self.toast(f"{name} expulsé.", "ok"), self.refresh_players()),
            err=lambda e: self.toast(f"Échec : {e}", "error"),
        )

    def ban_player(self):
        cfg = self._rcon_ready()
        if not cfg:
            return
        sel = self._selected_player()
        if not sel:
            return
        num, name = sel
        minutes, ok = QInputDialog.getInt(
            self, "Bannir", f"Durée du ban de {name} en minutes (0 = permanent) :",
            0, 0, 525600
        )
        if not ok:
            return
        reason, ok = QInputDialog.getText(self, "Bannir", "Raison du bannissement :")
        if not ok:
            return
        duree = "permanent" if minutes == 0 else f"{minutes} min"
        if QMessageBox.question(
            self, "Bannir le joueur",
            f"Bannir {name} ({duree}) ?"
        ) != QMessageBox.StandardButton.Yes:
            return
        self.run_func(
            partial(rcon.ban_player, cfg, num, minutes, reason.strip()),
            ok=lambda _: (self.toast(f"{name} banni ({duree}).", "ok"),
                          self.refresh_players()),
            err=lambda e: self.toast(f"Échec : {e}", "error"),
        )

    def refresh_bans(self):
        cfg = self._rcon_ready()
        if not cfg:
            return
        self.run_func(
            partial(rcon.list_bans, cfg),
            ok=self._populate_bans,
            err=lambda e: self.toast(f"RCON : {e}", "error"),
        )

    def _populate_bans(self, bans):
        self.bans_table.setRowCount(len(bans))
        for row, b in enumerate(bans):
            values = [b["id"], b["kind"], b["target"], b["remaining"], b["reason"]]
            for col, value in enumerate(values):
                self.bans_table.setItem(row, col, QTableWidgetItem(str(value)))

    def remove_selected_ban(self):
        cfg = self._rcon_ready()
        if not cfg:
            return
        row = self.bans_table.currentRow()
        if row < 0:
            self.toast("Sélectionne un bannissement.", "error")
            return
        ban_id = self.bans_table.item(row, 0).text()
        target = self.bans_table.item(row, 2).text()
        if QMessageBox.question(self, "Retirer le ban",
                                f"Retirer le bannissement de {target} ?") != \
                QMessageBox.StandardButton.Yes:
            return
        self.run_func(
            partial(rcon.remove_ban, cfg, ban_id),
            ok=lambda _: (self.toast("Bannissement retiré.", "ok"), self.refresh_bans()),
            err=lambda e: self.toast(f"Échec : {e}", "error"),
        )

    def reload_bans(self):
        cfg = self._rcon_ready()
        if not cfg:
            return
        self.run_func(
            partial(rcon.reload_bans, cfg),
            ok=lambda _: (self.toast("Bans rechargés.", "ok"), self.refresh_bans()),
            err=lambda e: self.toast(f"Échec : {e}", "error"),
        )

    # ----- Ban hors-ligne (GUID / SteamID64 / IP) -----
    def offline_ban(self):
        cfg = self._rcon_ready()
        if not cfg:
            return
        target, ok = QInputDialog.getText(
            self, "Ban hors-ligne",
            "GUID BattlEye, SteamID64 (7656…) ou IP à bannir :"
        )
        if not ok or not target.strip():
            return
        minutes, ok = QInputDialog.getInt(
            self, "Durée", "Durée en minutes (0 = permanent) :", 0, 0, 525600
        )
        if not ok:
            return
        reason, ok = QInputDialog.getText(self, "Raison", "Raison :", text="Banni")
        if not ok:
            return
        self.run_func(
            partial(rcon.add_ban, cfg, target.strip(), minutes, reason.strip()),
            ok=lambda _: (self.toast(f"{target.strip()} banni.", "ok"),
                          self.refresh_bans()),
            err=lambda e: self.toast(f"Échec : {e}", "error"),
        )

    def export_bans(self):
        cfg = self._rcon_ready()
        if not cfg:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Exporter les bans", "bans.txt", "Texte (*.txt)"
        )
        if not path:
            return
        self.run_func(
            partial(rcon.export_bans, cfg),
            ok=lambda text: self._write_local(path, text, "bans exportés"),
            err=lambda e: self.toast(f"Échec : {e}", "error"),
        )

    def _write_local(self, path, text, label):
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text or "")
        except OSError as exc:
            self.toast(f"Écriture impossible : {exc}", "error")
            return
        self.toast(f"{label} → {path}", "ok")

    def import_bans(self):
        cfg = self._rcon_ready()
        if not cfg:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Importer des bans", "", "Texte (*.txt *.cfg);;Tous (*)"
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.read().splitlines()
        except OSError as exc:
            self.toast(f"Lecture impossible : {exc}", "error")
            return
        if QMessageBox.question(
            self, "Importer des bans",
            f"Bannir (permanent) les cibles listées dans {path.split('/')[-1]} ?"
        ) != QMessageBox.StandardButton.Yes:
            return
        self.toast("Import des bans…", "info")
        self.run_func(
            partial(rcon.import_bans, cfg, lines),
            ok=lambda n: (self.toast(f"{n} ban(s) importé(s).", "ok"),
                          self.refresh_bans()),
            err=lambda e: self.toast(f"Échec : {e}", "error"),
        )

    # ================================================================== #
    # PAGE — Configuration (serverDZ.cfg)
    # ================================================================== #
    def build_config_page(self, layout):
        self._header(layout, "Configuration",
                     "Éditeur de serverDZ.cfg — formulaire ou texte brut.")

        bar = QHBoxLayout()
        self.load_cfg_btn = QPushButton("⟳  Charger")
        self.save_cfg_btn = QPushButton("💾  Enregistrer")
        self.save_cfg_btn.setObjectName("success")
        self.compare_cfg_btn = QPushButton("⇄  Comparer local / serveur")
        self.load_cfg_btn.clicked.connect(self.load_serverdz)
        self.save_cfg_btn.clicked.connect(self.save_serverdz)
        self.compare_cfg_btn.clicked.connect(self.compare_server_config)
        bar.addWidget(self.load_cfg_btn)
        bar.addWidget(self.save_cfg_btn)
        bar.addWidget(self.compare_cfg_btn)
        bar.addStretch(1)
        layout.addLayout(bar)

        self.config_tabs = QTabWidget()

        # Onglet formulaire
        form_scroll = QScrollArea()
        form_scroll.setWidgetResizable(True)
        form_scroll.setFrameShape(QFrame.Shape.NoFrame)
        form_host = QWidget()
        form = QFormLayout(form_host)
        form.setContentsMargins(16, 16, 16, 16)
        form.setVerticalSpacing(12)
        self.cfg_fields = {}
        for key, label, _ in cfg_editor.SERVERDZ_FIELDS:
            edit = QLineEdit()
            self.cfg_fields[key] = edit
            form.addRow(label, edit)
        form_scroll.setWidget(form_host)
        self.config_tabs.addTab(form_scroll, "Formulaire")

        # Onglet brut
        self.cfg_raw = QPlainTextEdit()
        self.cfg_raw.setStyleSheet("font-family: Consolas, monospace;")
        self.config_tabs.addTab(self.cfg_raw, "Texte brut")

        layout.addWidget(self.config_tabs, 1)
        self.cfg_diff_view = QPlainTextEdit()
        self.cfg_diff_view.setReadOnly(True)
        self.cfg_diff_view.setPlaceholderText(
            "La comparaison avec un fichier local apparaîtra ici."
        )
        self.cfg_diff_view.setMaximumBlockCount(5000)
        layout.addWidget(self.cfg_diff_view, 1)

    def load_serverdz(self):
        cfg = self._require_config()
        if not cfg:
            return
        self.toast("Chargement de serverDZ.cfg…", "info")
        self.run_func(
            partial(cfg_editor.read_serverdz, cfg),
            ok=self._populate_serverdz,
            err=lambda e: self.toast(f"Lecture impossible : {e}", "error"),
        )

    def compare_server_config(self):
        path, _filter = QFileDialog.getOpenFileName(
            self, "Fichier local à comparer", "", "Fichiers CFG (*.cfg);;Tous (*.*)"
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                local_content = handle.read().splitlines()
        except (OSError, UnicodeError) as exc:
            self.toast(f"Lecture locale impossible : {exc}", "error")
            return
        cfg = self._require_config()
        if not cfg:
            return
        self.run_func(
            partial(cfg_editor.read_serverdz, cfg),
            ok=lambda server: self._show_config_diff(
                local_content, server.splitlines(), path
            ),
            err=lambda e: self.toast(f"Lecture serveur impossible : {e}", "error"),
        )

    def _show_config_diff(self, local_lines, server_lines, local_path):
        diff = difflib.unified_diff(
            local_lines,
            server_lines,
            fromfile=local_path,
            tofile="serveur: serverDZ.cfg",
            lineterm="",
        )
        output = "\n".join(diff) or "Aucune différence : les fichiers sont identiques."
        self.cfg_diff_view.setPlainText(output)
        self.toast("Comparaison terminée.", "ok")

    def _populate_serverdz(self, content):
        self._serverdz_content = content
        self.cfg_raw.setPlainText(content)
        for key, edit in self.cfg_fields.items():
            value = cfg_editor.get_value(content, key)
            edit.setText("" if value is None else str(value))
        self.toast("serverDZ.cfg chargé.", "ok")

    def save_serverdz(self):
        if not self._allow("write"):
            return
        cfg = self._require_config()
        if not cfg:
            return

        if self.config_tabs.currentIndex() == 1:
            content = self.cfg_raw.toPlainText()
        else:
            content = self._serverdz_content
            quoted_keys = {k for k, _, t in cfg_editor.SERVERDZ_FIELDS if t == "str"}
            for key, edit in self.cfg_fields.items():
                value = edit.text().strip()
                if value == "" and cfg_editor.get_value(content, key) is None:
                    continue
                content = cfg_editor.set_value(content, key, value, key in quoted_keys)
            self.cfg_raw.setPlainText(content)

        self.run_func(
            partial(cfg_editor.write_serverdz, cfg, content),
            ok=lambda _: (self._populate_serverdz(content),
                          self.toast("serverDZ.cfg enregistré.", "ok")),
            err=lambda e: self.toast(f"Écriture impossible : {e}", "error"),
        )

    # ================================================================== #
    # PAGE — Économie (types.xml)
    # ================================================================== #
    def build_types_page(self, layout):
        self._header(layout, "Économie (types.xml)",
                     "Édite le loot : quantités, durées de vie, rareté…")

        bar = QHBoxLayout()
        self.types_file_combo = QComboBox()
        self.types_load_btn = QPushButton("⟳  Charger")
        self.types_save_btn = QPushButton("💾  Enregistrer")
        self.types_save_btn.setObjectName("success")
        self.types_load_btn.clicked.connect(self.load_types)
        self.types_save_btn.clicked.connect(self.save_types)
        bar.addWidget(self.types_file_combo, 1)
        bar.addWidget(self.types_load_btn)
        bar.addWidget(self.types_save_btn)
        layout.addLayout(bar)

        search_row = QHBoxLayout()
        self.types_search = QLineEdit()
        self.types_search.setPlaceholderText("Filtrer par nom d'objet…")
        self.types_search.textChanged.connect(self._filter_types)
        self.types_count_label = QLabel("—")
        self.types_count_label.setStyleSheet(f"color: {theme.MUTED};")
        search_row.addWidget(self.types_search, 1)
        search_row.addWidget(self.types_count_label)
        layout.addLayout(search_row)

        columns = ["Nom"] + [f.capitalize() for f in types_editor.FIELDS]
        self.types_table = QTableWidget(0, len(columns))
        self.types_table.setHorizontalHeaderLabels(columns)
        self.types_table.verticalHeader().setVisible(False)
        self.types_table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
        )
        header = self.types_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, len(columns)):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.types_table, 1)

        self._types_root = None
        self._types_elements = []  # élément XML par ligne de table

    def refresh_types_files(self):
        cfg = self._require_config()
        if not cfg:
            return
        self.run_cmd(
            commands.list_types_files(cfg),
            ok=self._populate_types_files,
            err=lambda e: self.toast(f"Recherche types.xml : {e}", "error"),
        )

    def _populate_types_files(self, output):
        self.types_file_combo.clear()
        paths = [p.strip() for p in output.splitlines() if p.strip()]
        if not paths:
            self.toast("Aucun types.xml trouvé sous mpmissions.", "error")
            return
        self.types_file_combo.addItems(paths)
        self.toast(f"{len(paths)} fichier(s) types.xml trouvé(s).", "ok")

    def load_types(self):
        cfg = self._require_config()
        if not cfg:
            return
        path = self.types_file_combo.currentText().strip()
        if not path:
            self.toast("Sélectionne un fichier types.xml.", "error")
            return
        self._types_path = path
        self.toast("Chargement de types.xml…", "info")
        self.run_func(
            partial(connection.read_file, path),
            ok=self._populate_types_table,
            err=lambda e: self.toast(f"Lecture impossible : {e}", "error"),
        )

    def _populate_types_table(self, text):
        try:
            root = types_editor.parse(text)
        except Exception as exc:
            self.toast(f"XML invalide : {exc}", "error")
            return
        self._types_root = root
        elements = types_editor.iter_types(root)
        self._types_elements = elements

        self.types_table.setSortingEnabled(False)
        self.types_table.setRowCount(len(elements))
        for row, el in enumerate(elements):
            name_item = QTableWidgetItem(el.get("name", ""))
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.types_table.setItem(row, 0, name_item)
            for col, field in enumerate(types_editor.FIELDS, start=1):
                self.types_table.setItem(
                    row, col, QTableWidgetItem(types_editor.get_field(el, field))
                )
        self.types_count_label.setText(f"{len(elements)} objets")
        self.toast(f"types.xml chargé ({len(elements)} objets).", "ok")

    def _filter_types(self, text):
        text = text.lower().strip()
        for row in range(self.types_table.rowCount()):
            item = self.types_table.item(row, 0)
            visible = text in item.text().lower() if item else True
            self.types_table.setRowHidden(row, not visible)

    def save_types(self):
        if not self._allow("write"):
            return
        cfg = self._require_config()
        if not cfg or self._types_root is None:
            self.toast("Charge d'abord un types.xml.", "error")
            return

        # Validation + application des modifications aux éléments.
        for row, el in enumerate(self._types_elements):
            for col, field in enumerate(types_editor.FIELDS, start=1):
                item = self.types_table.item(row, col)
                value = item.text().strip() if item else ""
                if value == "":
                    continue
                try:
                    int(value)
                except ValueError:
                    name = el.get("name", f"ligne {row + 1}")
                    self.toast(f"Valeur non entière pour {name} / {field} : {value}",
                               "error")
                    return
                types_editor.set_field(el, field, value)

        content = types_editor.serialize(self._types_root)
        self.toast("Enregistrement de types.xml…", "info")
        self.run_func(
            partial(connection.write_file, self._types_path, content),
            ok=lambda _: self.toast("types.xml enregistré.", "ok"),
            err=lambda e: self.toast(f"Écriture impossible : {e}", "error"),
        )

    # ================================================================== #
    # PAGE — Fichiers serveur & paramètres de lancement
    # ================================================================== #
    def build_files_page(self, layout):
        self._header(layout, "Fichiers & lancement",
                     "Paramètres de lancement, mission active et éditeurs "
                     "d'économie (events.xml, globals.xml, cfgspawnabletypes.xml…).")
        self._econ_path = ""

        # ---- Paramètres de lancement + mission active ----
        top = self._panel()
        tv = QVBoxLayout(top)
        tv.setContentsMargins(16, 16, 16, 16)
        tv.setSpacing(10)

        lp_row = QHBoxLayout()
        lp_row.addWidget(QLabel("Paramètres de lancement (LGSM) :"))
        self.launch_params_edit = QLineEdit()
        self.launch_params_edit.setPlaceholderText('-cpuCount=4 -limitFPS=60 …')
        self.launch_reload_btn = QPushButton("⟳")
        self.launch_reload_btn.setToolTip("Recharger depuis common.cfg")
        self.launch_save_btn = QPushButton("💾  Enregistrer")
        self.launch_save_btn.setObjectName("success")
        self.launch_reload_btn.clicked.connect(self.load_launch_params)
        self.launch_save_btn.clicked.connect(self.save_launch_params)
        lp_row.addWidget(self.launch_params_edit, 1)
        lp_row.addWidget(self.launch_reload_btn)
        lp_row.addWidget(self.launch_save_btn)
        tv.addLayout(lp_row)

        m_row = QHBoxLayout()
        m_row.addWidget(QLabel("Mission active (template) :"))
        self.mission_combo = QComboBox()
        self.set_mission_btn = QPushButton("🗺️  Définir comme active")
        self.set_mission_btn.setObjectName("primary")
        self.set_mission_btn.clicked.connect(self.set_active_mission)
        m_row.addWidget(self.mission_combo, 1)
        m_row.addWidget(self.set_mission_btn)
        tv.addLayout(m_row)
        layout.addWidget(top)

        # ---- Éditeur de fichiers d'économie / config ----
        bar = QHBoxLayout()
        self.econ_file_combo = QComboBox()
        self.refresh_files_btn = QPushButton("⟳  Actualiser")
        self.load_econ_btn = QPushButton("📂  Charger")
        self.load_econ_btn.setObjectName("primary")
        self.save_econ_btn = QPushButton("💾  Enregistrer")
        self.save_econ_btn.setObjectName("success")
        self.refresh_files_btn.clicked.connect(self.refresh_files)
        self.load_econ_btn.clicked.connect(self.load_economy_file)
        self.save_econ_btn.clicked.connect(self.save_economy_file)
        bar.addWidget(self.econ_file_combo, 1)
        bar.addWidget(self.refresh_files_btn)
        bar.addWidget(self.load_econ_btn)
        bar.addWidget(self.save_econ_btn)
        layout.addLayout(bar)

        self.econ_editor = QPlainTextEdit()
        self.econ_editor.setStyleSheet("font-family: Consolas, monospace; font-size: 10pt;")
        self.econ_editor.setPlaceholderText(
            "Charge un fichier pour l'éditer. Le XML/JSON est validé avant "
            "l'enregistrement."
        )
        layout.addWidget(self.econ_editor, 1)

        note = QLabel(
            "ℹ️ Sauvegarde recommandée avant édition (page Sauvegardes). "
            "Le serveur doit être redémarré pour appliquer ces changements."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {theme.MUTED}; font-size: 9.5pt;")
        layout.addWidget(note)

    # ----- Paramètres de lancement -----
    def load_launch_params(self):
        cfg = self._require_config()
        if not cfg:
            return
        self.run_func(
            partial(cfg_editor.get_startparameters, cfg),
            ok=lambda v: self.launch_params_edit.setText(v or ""),
            err=lambda e: self.toast(f"Lecture lancement : {e}", "error"),
        )

    def save_launch_params(self):
        if not self._allow("write"):
            return
        cfg = self._require_config()
        if not cfg:
            return
        params = self.launch_params_edit.text().strip()
        self.toast("Enregistrement des paramètres de lancement…", "info")
        self.run_func(
            partial(cfg_editor.set_startparameters, cfg, params),
            ok=lambda _: self.toast("Paramètres de lancement enregistrés "
                                    "(redémarre le serveur).", "ok"),
            err=lambda e: self.toast(f"Échec : {e}", "error"),
        )

    # ----- Mission active -----
    @staticmethod
    def _write_active_mission(cfg, mission):
        if not cfg_editor.mission_exists(cfg, mission):
            raise IOError(
                f"Mission « {mission} » introuvable sous mpmissions. "
                f"Le template doit correspondre exactement au nom du dossier."
            )
        content = cfg_editor.read_serverdz(cfg)
        content = cfg_editor.set_value(content, "template", mission, quoted=True)
        cfg_editor.write_serverdz(cfg, content)
        return mission

    def set_active_mission(self):
        if not self._allow("write"):
            return
        cfg = self._require_config()
        if not cfg:
            return
        mission = self.mission_combo.currentText().strip()
        if not mission:
            self.toast("Sélectionne une mission.", "error")
            return
        self.run_func(
            partial(self._write_active_mission, cfg, mission),
            ok=lambda m: self.toast(f"Mission active : {m} (redémarre le serveur).", "ok"),
            err=lambda e: self.toast(f"Échec : {e}", "error"),
        )

    # ----- Éditeur de fichiers économie -----
    def refresh_files(self):
        cfg = self._require_config()
        if not cfg:
            return
        self.run_cmd(
            commands.list_economy_files(cfg),
            ok=self._populate_econ_files,
            err=lambda e: self.toast(f"Recherche fichiers : {e}", "error"),
        )
        self.run_cmd(
            commands.list_missions(cfg),
            ok=self._populate_missions,
            err=lambda e: self.toast(f"Missions : {e}", "error"),
        )

    def _populate_econ_files(self, output):
        self.econ_file_combo.clear()
        paths = [p.strip() for p in output.splitlines() if p.strip()]
        if not paths:
            self.toast("Aucun fichier d'économie trouvé sous mpmissions.", "warn")
            return
        self.econ_file_combo.addItems(paths)
        self.toast(f"{len(paths)} fichier(s) trouvé(s).", "ok")

    def _populate_missions(self, output):
        self.mission_combo.clear()
        names = [n.strip() for n in output.splitlines() if n.strip()]
        self.mission_combo.addItems(names)

    def load_economy_file(self):
        cfg = self._require_config()
        if not cfg:
            return
        path = self.econ_file_combo.currentText().strip()
        if not path:
            self.toast("Sélectionne un fichier.", "error")
            return
        self.toast("Chargement…", "info")
        self.run_func(
            partial(connection.read_file, path),
            ok=lambda content: self._on_econ_loaded(path, content),
            err=lambda e: self.toast(f"Lecture impossible : {e}", "error"),
        )

    def _on_econ_loaded(self, path, content):
        self._econ_path = path
        self.econ_editor.setPlainText(content)
        self.toast(f"{path.split('/')[-1]} chargé.", "ok")

    def save_economy_file(self):
        if not self._allow("write"):
            return
        cfg = self._require_config()
        if not cfg or not self._econ_path:
            self.toast("Charge d'abord un fichier.", "error")
            return
        text = self.econ_editor.toPlainText()
        lower = self._econ_path.lower()
        if lower.endswith(".xml"):
            import xml.etree.ElementTree as ET
            try:
                ET.fromstring(text)
            except ET.ParseError as exc:
                self.toast(f"XML invalide : {exc}", "error")
                return
        elif lower.endswith(".json"):
            import json
            try:
                json.loads(text)
            except ValueError as exc:
                self.toast(f"JSON invalide : {exc}", "error")
                return
        self.toast("Enregistrement…", "info")
        self.run_func(
            partial(connection.write_file, self._econ_path, text),
            ok=lambda _: self.toast(f"{self._econ_path.split('/')[-1]} enregistré "
                                    "(redémarre le serveur).", "ok"),
            err=lambda e: self.toast(f"Écriture impossible : {e}", "error"),
        )

    # ================================================================== #
    # PAGE — Mods
    # ================================================================== #
    def build_mods_page(self, layout):
        self._header(layout, "Mods",
                     "Installe, active/désactive et ordonne les mods Workshop.")

        panel = self._panel()
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(16, 16, 16, 16)
        pv.setSpacing(10)
        self.mod_input = QLineEdit()
        self.mod_input.setPlaceholderText("ID(s) Workshop séparés par ; ou ,")
        row = QHBoxLayout()
        self.install_mod_btn = QPushButton("⬇  Installer")
        self.install_mod_btn.setObjectName("primary")
        self.refresh_mods_btn = QPushButton("⟳  Actualiser")
        self.check_mod_updates_btn = QPushButton("🔄  Vérifier les MAJ")
        self.update_all_btn = QPushButton("⬆  Tout mettre à jour")
        self.update_all_btn.setObjectName("success")
        self.dependencies_btn = QPushButton("🔗  Analyser dépendances")
        self.install_mod_btn.clicked.connect(self.install_mods)
        self.refresh_mods_btn.clicked.connect(self.refresh_mods)
        self.check_mod_updates_btn.clicked.connect(self.check_mod_updates)
        self.update_all_btn.clicked.connect(self.update_all_mods)
        self.dependencies_btn.clicked.connect(self.analyze_mod_dependencies)
        row.addWidget(self.install_mod_btn)
        row.addWidget(self.refresh_mods_btn)
        row.addWidget(self.check_mod_updates_btn)
        row.addWidget(self.update_all_btn)
        row.addWidget(self.dependencies_btn)
        row.addStretch(1)
        pv.addWidget(self.mod_input)
        pv.addLayout(row)
        layout.addWidget(panel)

        self.mods_count_label = QLabel("0 mod")
        self.mods_count_label.setStyleSheet(f"color: {theme.MUTED};")
        layout.addWidget(self.mods_count_label)

        body = QHBoxLayout()
        self.mod_list = QListWidget()
        self.mod_list.itemChanged.connect(self._on_mod_toggled)
        body.addWidget(self.mod_list, 1)

        side = QVBoxLayout()
        self.mod_up_btn = QPushButton("▲  Monter")
        self.mod_down_btn = QPushButton("▼  Descendre")
        self.mod_remove_btn = QPushButton("🗑  Supprimer")
        self.mod_remove_btn.setObjectName("danger")
        self.mod_up_btn.clicked.connect(lambda: self._move_mod(-1))
        self.mod_down_btn.clicked.connect(lambda: self._move_mod(1))
        self.mod_remove_btn.clicked.connect(self.remove_selected_mod)
        for b in (self.mod_up_btn, self.mod_down_btn, self.mod_remove_btn):
            side.addWidget(b)
        side.addStretch(1)
        hint = QLabel("Coché = actif\n(ligne mods=)")
        hint.setStyleSheet(f"color: {theme.MUTED}; font-size: 9pt;")
        side.addWidget(hint)
        body.addLayout(side)
        layout.addLayout(body, 1)
        self.mod_dependency_view = QPlainTextEdit()
        self.mod_dependency_view.setReadOnly(True)
        self.mod_dependency_view.setPlaceholderText(
            "Les dépendances requiredAddons apparaîtront ici."
        )
        self.mod_dependency_view.setMaximumBlockCount(1000)
        layout.addWidget(self.mod_dependency_view)

    def refresh_mods(self):
        cfg = self._require_config()
        if not cfg:
            return
        self.run_cmd(
            commands.list_mods(cfg),
            ok=lambda out: self.run_func(
                partial(cfg_editor.get_mods, cfg),
                ok=lambda enabled: self._populate_mods(out, enabled),
                err=lambda e: self._populate_mods(out, []),
            ),
            err=lambda e: self.toast(f"Liste des mods : {e}", "error"),
        )

    def analyze_mod_dependencies(self):
        if not self._allow("read"):
            return
        cfg = self._require_config()
        if not cfg:
            return
        self.mod_dependency_view.setPlainText("Analyse des requiredAddons…")
        self.run_cmd(
            commands.list_mod_dependencies(cfg),
            ok=lambda output: self.mod_dependency_view.setPlainText(
                output.strip() or "Aucune dépendance déclarée trouvée."
            ),
            err=lambda e: self.mod_dependency_view.setPlainText(f"[ERREUR] {e}"),
            timeout=60,
        )

    def _populate_mods(self, list_output, enabled):
        self._mods_loading = True
        self.mod_list.clear()
        installed = [x.strip() for x in list_output.splitlines() if x.strip()]
        # Mods activés d'abord (dans leur ordre), puis le reste.
        ordered = [m for m in enabled if m in installed]
        ordered += [m for m in installed if m not in enabled]
        for name in ordered:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if name in enabled else Qt.CheckState.Unchecked
            )
            self.mod_list.addItem(item)
        active = sum(1 for m in installed if m in enabled)
        self.mods_count_label.setText(
            f"{len(installed)} mod(s) installé(s) · {active} actif(s)"
        )
        self._mods_loading = False
        self._annotate_mod_updates()

    def _enabled_mods(self):
        return [
            self.mod_list.item(i).text()
            for i in range(self.mod_list.count())
            if self.mod_list.item(i).checkState() == Qt.CheckState.Checked
        ]

    def _persist_mods_order(self):
        cfg = self._require_config()
        if not cfg:
            return
        self.run_func(
            partial(cfg_editor.set_mods, cfg, self._enabled_mods()),
            ok=lambda _: self.toast("Liste des mods mise à jour.", "ok"),
            err=lambda e: self.toast(f"Mise à jour impossible : {e}", "error"),
        )

    def _on_mod_toggled(self, _item):
        if self._mods_loading:
            return
        self._persist_mods_order()
        # Recalcule le compteur actif.
        count = self.mod_list.count()
        self.mods_count_label.setText(
            f"{count} mod(s) installé(s) · {len(self._enabled_mods())} actif(s)"
        )

    def _move_mod(self, delta):
        row = self.mod_list.currentRow()
        if row < 0:
            return
        new_row = row + delta
        if not (0 <= new_row < self.mod_list.count()):
            return
        self._mods_loading = True
        item = self.mod_list.takeItem(row)
        self.mod_list.insertItem(new_row, item)
        self.mod_list.setCurrentRow(new_row)
        self._mods_loading = False
        self._persist_mods_order()

    def install_mods(self):
        if not self._allow("write"):
            return
        cfg = self._require_config()
        if not cfg:
            return
        ids = [x.strip() for x in self.mod_input.text().replace(",", ";").split(";")
               if x.strip()]
        if not ids:
            self.toast("Saisis au moins un ID Workshop.", "error")
            return
        if not all(i.isdigit() for i in ids):
            self.toast("Les ID Workshop doivent être numériques.", "error")
            return
        self._run_install(cfg, ids, f"Installation de {len(ids)} mod(s)")

    def remove_selected_mod(self):
        if not self._allow("write"):
            return
        item = self.mod_list.currentItem()
        if not item:
            self.toast("Aucun mod sélectionné.", "error")
            return
        mod_name = item.text()
        if QMessageBox.question(self, "Supprimer le mod",
                                f"Supprimer définitivement {mod_name} ?") != \
                QMessageBox.StandardButton.Yes:
            return
        cfg = self._require_config()
        if not cfg:
            return
        self.run_func(
            partial(cfg_editor.get_mods, cfg),
            ok=lambda enabled: self._remove_mod_if_inactive(
                cfg, mod_name, enabled
            ),
            err=lambda e: self.toast(
                f"Vérification du mod impossible : {e}", "error"
            ),
        )

    def _remove_mod_if_inactive(self, cfg, mod_name, enabled):
        if mod_name in enabled:
            self.toast(
                f"Impossible de supprimer {mod_name} : il est encore actif. "
                "Désactive-le d'abord puis réessaie.",
                "warn",
            )
            return
        self.run_cmd(
            commands.remove_mod(cfg, mod_name),
            ok=lambda _: (
                self.toast(f"{mod_name} supprimé.", "ok"),
                self.refresh_mods(),
            ),
            err=lambda e: self.toast(f"Échec : {e}", "error"),
        )

    # ----- Détection des mises à jour Workshop (mods & cartes) -----
    def check_mod_updates(self):
        cfg = self._require_config()
        if not cfg:
            return
        self.toast("Recherche des mises à jour Workshop…", "info")
        self.run_cmd(
            commands.list_workshop_items(cfg),
            ok=self._on_workshop_items,
            err=lambda e: self.toast(f"MAJ : {e}", "error"),
        )

    def _on_workshop_items(self, output):
        items = []
        for line in output.splitlines():
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            mod_id, mtime, name = parts
            if not mod_id.strip().isdigit():
                continue
            try:
                items.append((mod_id.strip(), int(mtime or 0), name.strip()))
            except ValueError:
                continue
        if not items:
            self.toast("Aucun item Workshop traçable (cache SteamCMD absent).", "info")
            return
        self._ws_items = items
        ids = [it[0] for it in items]
        self.run_net(
            partial(workshop.get_update_times, ids),
            ok=self._apply_update_status,
            err=lambda e: self.toast(f"MAJ : {e}", "error"),
        )

    def _apply_update_status(self, steam):
        self._mod_ids = {}
        updates = {}
        for mod_id, mtime, name in self._ws_items:
            self._mod_ids[name] = mod_id
            info = steam.get(mod_id)
            # Marge de 60 s pour absorber l'écart d'horloge / temps de copie.
            if info and info["time_updated"] > mtime + 60:
                updates[name] = mod_id
        self._mod_updates = updates
        if hasattr(self, "card_mod_updates"):
            self.card_mod_updates[1].setText(str(len(updates)))
        self._annotate_mod_updates()
        self._annotate_map_updates()
        n = len(updates)
        if n:
            self.toast(f"{n} mise(s) à jour disponible(s).", "ok")
        else:
            self.toast("Tous les mods/cartes sont à jour.", "ok")

    def _annotate_mod_updates(self):
        """Colore en ambre les mods à mettre à jour (sans toucher au texte)."""
        amber = QBrush(QColor(theme.AMBER))
        default = QBrush(QColor(theme.TEXT))
        outdated = 0
        for i in range(self.mod_list.count()):
            item = self.mod_list.item(i)
            name = item.text()
            if name in self._mod_updates:
                item.setForeground(amber)
                item.setToolTip("⬆ Mise à jour disponible sur le Workshop")
                outdated += 1
            else:
                item.setForeground(default)
                item.setToolTip("")
        if outdated and hasattr(self, "mods_count_label"):
            base = self.mods_count_label.text().split("  ·  ⬆")[0]
            self.mods_count_label.setText(f"{base}  ·  ⬆ {outdated} MAJ")

    def update_all_mods(self):
        if not self._allow("write"):
            return
        cfg = self._require_config()
        if not cfg:
            return
        if not self._mod_updates:
            self.toast("Lance d'abord « Vérifier les MAJ ».", "info")
            return
        ids = list(dict.fromkeys(self._mod_updates.values()))
        if QMessageBox.question(
            self, "Mettre à jour",
            f"Re-télécharger et mettre à jour {len(ids)} mod(s)/carte(s) ?"
        ) != QMessageBox.StandardButton.Yes:
            return
        # _mod_updates est {nom -> id} : on inverse pour afficher les noms.
        names = {mod_id: name for name, mod_id in self._mod_updates.items()}
        self._run_install(cfg, ids, f"Mise à jour de {len(ids)} item(s)",
                          on_done=self.check_mod_updates, names=names)

    # ================================================================== #
    # PAGE — Workshop (navigateur Steam)
    # ================================================================== #
    def build_workshop_page(self, layout):
        self._header(layout, "Steam Workshop",
                     "Cherche des mods et des cartes, puis installe en un clic.")

        bar = QHBoxLayout()
        self.ws_search_edit = QLineEdit()
        self.ws_search_edit.setPlaceholderText("Rechercher un mod ou une carte…")
        self.ws_search_edit.returnPressed.connect(lambda: self.workshop_search(1))
        self.ws_maps_check = QCheckBox("Cartes uniquement")
        self.ws_search_btn = QPushButton("🔎  Rechercher")
        self.ws_search_btn.setObjectName("primary")
        self.ws_search_btn.clicked.connect(lambda: self.workshop_search(1))
        bar.addWidget(self.ws_search_edit, 1)
        bar.addWidget(self.ws_maps_check)
        bar.addWidget(self.ws_search_btn)
        layout.addLayout(bar)

        coll = QHBoxLayout()
        self.ws_collection_edit = QLineEdit()
        self.ws_collection_edit.setPlaceholderText(
            "ID ou URL d'une collection Workshop…"
        )
        self.ws_collection_edit.returnPressed.connect(self.install_collection)
        self.ws_collection_btn = QPushButton("📚  Installer la collection")
        self.ws_collection_btn.clicked.connect(self.install_collection)
        coll.addWidget(self.ws_collection_edit, 1)
        coll.addWidget(self.ws_collection_btn)
        layout.addLayout(coll)

        self.ws_list = QListWidget()
        self.ws_list.setSpacing(6)
        layout.addWidget(self.ws_list, 1)

        nav = QHBoxLayout()
        self.ws_prev_btn = QPushButton("◀  Précédent")
        self.ws_next_btn = QPushButton("Suivant  ▶")
        self.ws_page_label = QLabel("—")
        self.ws_page_label.setStyleSheet(f"color: {theme.MUTED};")
        self.ws_prev_btn.clicked.connect(lambda: self.workshop_search(self._ws_page - 1))
        self.ws_next_btn.clicked.connect(lambda: self.workshop_search(self._ws_page + 1))
        nav.addWidget(self.ws_prev_btn)
        nav.addWidget(self.ws_next_btn)
        nav.addStretch(1)
        nav.addWidget(self.ws_page_label)
        layout.addLayout(nav)

        self._ws_page = 1
        self._ws_total = 0
        self._ws_per_page = 20

    def workshop_search(self, page):
        page = max(1, int(page))
        cfg = self.current_config()
        key = cfg.get("steam_api_key", "").strip()
        if not key:
            self.ws_list.clear()
            self.ws_list.addItem(
                "Renseigne ta clé API Steam dans Réglages "
                "(https://steamcommunity.com/dev/apikey) pour parcourir le Workshop."
            )
            self.toast("Clé API Steam manquante (Réglages).", "error")
            return

        self._ws_page = page
        query = self.ws_search_edit.text()
        maps_only = self.ws_maps_check.isChecked()
        self.ws_list.clear()
        self.ws_list.addItem("Recherche en cours…")
        self.toast("Recherche Workshop…", "info")
        self.run_net(
            partial(workshop.search, key, query, page, self._ws_per_page, maps_only),
            ok=self._render_workshop,
            err=lambda e: (self.ws_list.clear(), self.toast(f"Workshop : {e}", "error")),
        )

    def _render_workshop(self, result):
        items, total = result
        self._ws_total = total
        self.ws_list.clear()

        if not items:
            self.ws_list.addItem("Aucun résultat.")
        for it in items:
            row, thumb = self._workshop_row(it)
            list_item = QListWidgetItem()
            list_item.setSizeHint(QSize(0, 96))
            list_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.ws_list.addItem(list_item)
            self.ws_list.setItemWidget(list_item, row)
            if it["preview_url"]:
                self.run_net(
                    partial(workshop.download_image, it["preview_url"]),
                    ok=partial(self._set_thumb, thumb),
                )

        pages = max(1, -(-total // self._ws_per_page)) if total else self._ws_page
        self.ws_page_label.setText(f"Page {self._ws_page} / {pages}  ·  ~{total} résultats")
        self.ws_prev_btn.setEnabled(self._ws_page > 1)
        self.ws_next_btn.setEnabled(self._ws_page < pages)

    def _workshop_row(self, item):
        frame = QFrame()
        frame.setObjectName("card")
        h = QHBoxLayout(frame)
        h.setContentsMargins(10, 8, 10, 8)
        h.setSpacing(12)

        thumb = QLabel("…")
        thumb.setFixedSize(128, 72)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb.setStyleSheet(
            f"background: {theme.SURFACE_2}; border-radius: 8px; color: {theme.MUTED};"
        )
        h.addWidget(thumb)

        info = QVBoxLayout()
        info.setSpacing(3)
        title = QLabel(item["title"])
        title.setStyleSheet("font-weight: 700; font-size: 11.5pt;")
        title.setWordWrap(True)
        meta_bits = []
        if item["size_mb"]:
            meta_bits.append(f"{item['size_mb']} Mo")
        if item["subscriptions"]:
            meta_bits.append(f"{item['subscriptions']:,} abonnés".replace(",", " "))
        if item["tags"]:
            meta_bits.append(" · ".join(item["tags"][:3]))
        meta = QLabel("   ·   ".join(meta_bits) or f"ID {item['id']}")
        meta.setStyleSheet(f"color: {theme.MUTED}; font-size: 9.5pt;")
        info.addWidget(title)
        info.addWidget(meta)
        info.addStretch(1)
        h.addLayout(info, 1)

        buttons = QVBoxLayout()
        install_btn = QPushButton("⬇  Installer")
        install_btn.setObjectName("primary")
        install_btn.clicked.connect(
            partial(self.install_from_workshop, item["id"], item["title"])
        )
        page_btn = QPushButton("Page Steam")
        page_btn.clicked.connect(partial(self._open_workshop_page, item["id"]))
        buttons.addWidget(install_btn)
        buttons.addWidget(page_btn)
        h.addLayout(buttons)

        return frame, thumb

    def _set_thumb(self, label, data):
        if not data:
            return
        pix = QPixmap()
        if pix.loadFromData(data):
            label.setPixmap(
                pix.scaled(128, 72, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                           Qt.TransformationMode.SmoothTransformation)
            )

    @staticmethod
    def _open_workshop_page(mod_id):
        QDesktopServices.openUrl(
            QUrl(f"https://steamcommunity.com/sharedfiles/filedetails/?id={mod_id}")
        )

    def install_from_workshop(self, mod_id, title):
        if not self._allow("write"):
            return
        cfg = self._require_config()
        if not cfg:
            return
        if QMessageBox.question(
            self, "Installer le mod",
            f"Télécharger et installer « {title} » (ID {mod_id}) sur le serveur ?"
        ) != QMessageBox.StandardButton.Yes:
            return
        self._run_install(cfg, [mod_id], f"Installation : {title}",
                          names={str(mod_id): title})

    @staticmethod
    def _extract_id(text):
        """Extrait un ID Workshop numérique depuis un ID brut ou une URL."""
        import re
        text = text.strip()
        m = re.search(r"(?:\?id=|/)(\d{4,})", text)
        if m:
            return m.group(1)
        return text if text.isdigit() else ""

    def install_collection(self):
        if not self._allow("write"):
            return
        cfg = self._require_config()
        if not cfg:
            return
        collection_id = self._extract_id(self.ws_collection_edit.text())
        if not collection_id:
            self.toast("ID de collection invalide.", "error")
            return
        self.toast("Résolution de la collection…", "info")
        self.run_net(
            partial(workshop.get_collection, collection_id),
            ok=lambda ids: self._install_collection_ids(cfg, ids),
            err=lambda e: self.toast(f"Collection : {e}", "error"),
        )

    def _install_collection_ids(self, cfg, ids, on_done=None):
        if not ids:
            self.toast("Collection vide ou introuvable.", "error")
            return
        if QMessageBox.question(
            self, "Installer la collection",
            f"La collection contient {len(ids)} mod(s).\n"
            "Tout télécharger et installer sur le serveur ?"
        ) != QMessageBox.StandardButton.Yes:
            return
        self._run_install(
            cfg, ids, f"Collection — {len(ids)} mod(s)", on_done=on_done
        )

    # ================================================================== #
    # PAGE — Cartes
    # ================================================================== #
    def build_maps_page(self, layout):
        self._header(layout, "Cartes",
                     "Change la mission active, le mod de carte et redémarre le serveur.")

        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("Profil carte"))
        self.map_profile_combo = QComboBox()
        self.map_profile_name_edit = QLineEdit()
        self.map_profile_name_edit.setPlaceholderText("Nom du profil")
        self.save_map_profile_btn = QPushButton("💾 Enregistrer")
        self.apply_map_profile_btn = QPushButton("▶ Appliquer")
        self.delete_map_profile_btn = QPushButton("🗑 Supprimer")
        self.save_map_profile_btn.clicked.connect(self.save_map_profile)
        self.apply_map_profile_btn.clicked.connect(self.apply_map_profile)
        self.delete_map_profile_btn.clicked.connect(self.delete_map_profile)
        profile_row.addWidget(self.map_profile_combo, 1)
        profile_row.addWidget(self.map_profile_name_edit)
        profile_row.addWidget(self.save_map_profile_btn)
        profile_row.addWidget(self.apply_map_profile_btn)
        profile_row.addWidget(self.delete_map_profile_btn)
        layout.addLayout(profile_row)

        bar = QHBoxLayout()
        self.refresh_maps_btn = QPushButton("⟳  Actualiser")
        self.set_map_btn = QPushButton("🗺️  Définir comme carte active")
        self.set_map_btn.setObjectName("primary")
        self.import_mission_btn = QPushButton("📥  Importer une mission")
        self.refresh_maps_btn.clicked.connect(self.refresh_maps)
        self.set_map_btn.clicked.connect(self.set_selected_map)
        self.import_mission_btn.clicked.connect(self.import_mission_dialog)
        bar.addWidget(self.refresh_maps_btn)
        bar.addWidget(self.set_map_btn)
        bar.addWidget(self.import_mission_btn)
        bar.addStretch(1)
        layout.addLayout(bar)

        workshop_hint_row = QHBoxLayout()
        workshop_hint = QLabel(
            "Installation d’une collection de carte : ouvre l’onglet Workshop."
        )
        workshop_hint.setObjectName("subtleHint")
        open_workshop_btn = QPushButton("Ouvrir Workshop")
        open_workshop_btn.clicked.connect(
            lambda: self._nav_to("build_workshop_page")
        )
        workshop_hint_row.addWidget(workshop_hint, 1)
        workshop_hint_row.addWidget(open_workshop_btn)
        layout.addLayout(workshop_hint_row)

        self.map_status_label = QLabel("Carte active : —")
        self.map_status_label.setStyleSheet(f"color: {theme.MUTED};")
        layout.addWidget(self.map_status_label)

        self.map_list = QListWidget()
        layout.addWidget(self.map_list, 1)

        rotation_row = QHBoxLayout()
        rotation_row.addWidget(QLabel("Rotation automatique"))
        self.rotation_profiles_edit = QLineEdit()
        self.rotation_profiles_edit.setPlaceholderText("Profils dans l'ordre : Soir, Nuit, Event")
        self.rotation_times_edit = QLineEdit()
        self.rotation_times_edit.setPlaceholderText("Heures : 18:00, 23:00, 04:00")
        self.rotation_apply_btn = QPushButton("⏱ Activer")
        self.rotation_disable_btn = QPushButton("Désactiver")
        self.rotation_view_btn = QPushButton("Voir")
        self.rotation_apply_btn.clicked.connect(self.apply_map_rotation)
        self.rotation_disable_btn.clicked.connect(self.disable_map_rotation)
        self.rotation_view_btn.clicked.connect(self.view_map_rotation)
        rotation_row.addWidget(self.rotation_profiles_edit, 1)
        rotation_row.addWidget(self.rotation_times_edit, 1)
        rotation_row.addWidget(self.rotation_apply_btn)
        rotation_row.addWidget(self.rotation_disable_btn)
        rotation_row.addWidget(self.rotation_view_btn)
        layout.addLayout(rotation_row)
        self._load_map_profiles()

    def _load_map_profiles(self):
        self._map_profiles = profiles.load_profiles()
        if not hasattr(self, "map_profile_combo"):
            return
        self.map_profile_combo.clear()
        for name in sorted(self._map_profiles, key=str.lower):
            self.map_profile_combo.addItem(name, self._map_profiles[name])

    def _selected_map_data(self):
        item = self.map_list.currentItem()
        if not item:
            return None
        data = item.data(Qt.ItemDataRole.UserRole) or {}
        return data if isinstance(data, dict) else {"mod_name": data}

    def save_map_profile(self):
        if not self._allow("write"):
            return
        data = self._selected_map_data()
        if not data or not data.get("template"):
            self.toast("Sélectionne d'abord une carte avec sa mission.", "warn")
            return
        name = self.map_profile_name_edit.text().strip()
        if not name:
            name, ok = QInputDialog.getText(
                self, "Nouveau profil", "Nom du profil de carte :"
            )
            if not ok:
                return
            name = name.strip()
        cfg = self._require_config()
        if not cfg:
            return
        self.run_func(
            partial(cfg_editor.get_mods, cfg),
            ok=lambda mods: self.run_func(
                partial(cfg_editor.get_startparameters, cfg),
                ok=lambda params: self._save_map_profile_data(
                    name, data, mods, params
                ),
                err=lambda e: self.toast(f"Lecture du lancement : {e}", "error"),
            ),
            err=lambda e: self.toast(f"Lecture des mods : {e}", "error"),
        )

    def _save_map_profile_data(self, name, data, mods, params):
        try:
            saved = profiles.upsert_profile(name, {
                "mod_name": data.get("mod_name"),
                "template": data.get("template"),
                "mods": mods,
                "startparameters": params,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            })
        except ValueError as exc:
            self.toast(str(exc), "error")
            return
        self._load_map_profiles()
        index = self.map_profile_combo.findText(saved["name"])
        self.map_profile_combo.setCurrentIndex(max(0, index))
        self.map_profile_name_edit.clear()
        self.toast(f"Profil « {saved['name']} » enregistré.", "ok")

    def delete_map_profile(self):
        if not self._allow("write"):
            return
        name = self.map_profile_combo.currentText().strip()
        if not name:
            self.toast("Aucun profil sélectionné.", "warn")
            return
        if QMessageBox.question(
            self, "Supprimer le profil", f"Supprimer le profil « {name} » ?"
        ) != QMessageBox.StandardButton.Yes:
            return
        profiles.delete_profile(name)
        self._load_map_profiles()
        self.toast(f"Profil « {name} » supprimé.", "ok")

    def apply_map_profile(self):
        if not self._allow("write"):
            return
        profile = self.map_profile_combo.currentData()
        if not isinstance(profile, dict) or not profile.get("template"):
            self.toast("Sélectionne un profil de carte valide.", "warn")
            return
        cfg = self._require_config()
        if not cfg:
            return
        name = self.map_profile_combo.currentText()
        if QMessageBox.question(
            self, "Appliquer le profil",
            f"Appliquer « {name} » avec ses mods et paramètres de lancement ?\n\n"
            "Une sauvegarde sera créée avant le redémarrage.",
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            command = commands.create_backup(cfg, "before-profile")
        except ValueError as exc:
            self.toast(str(exc), "error")
            return
        self._run_streamed(
            command,
            "Sauvegarde avant profil",
            on_done=lambda: self._apply_map_profile_after_backup(cfg, profile),
            sink=self._backup_progress,
        )

    def _apply_map_profile_after_backup(self, cfg, profile):
        self.run_func(
            partial(cfg_editor.apply_profile, cfg, profile),
            ok=lambda result: self._restart_after_map_change(cfg, result),
            err=lambda e: self.toast(f"Profil non appliqué : {e}", "error"),
        )

    def apply_map_rotation(self):
        if not self._allow("write"):
            return
        cfg = self._require_config()
        if not cfg:
            return
        names = [item.strip() for item in self.rotation_profiles_edit.text().replace(";", ",").split(",") if item.strip()]
        selected = [self._map_profiles.get(name) for name in names]
        if not names or any(profile is None for profile in selected):
            self.toast("Tous les profils de rotation doivent exister.", "error")
            return
        try:
            times = scheduler.parse_times(self.rotation_times_edit.text())
            if not times:
                raise ValueError("Renseigne au moins une heure valide (HH:MM).")
            if len(times) != len(selected):
                raise ValueError("Il faut exactement un profil par heure de rotation.")
            timezone = self.current_config().get("schedule_timezone", "Europe/Paris")
        except (TypeError, ValueError) as exc:
            self.toast(str(exc), "error")
            return
        self.run_func(
            partial(
                scheduler.apply_map_rotation,
                cfg,
                selected,
                self.rotation_times_edit.text(),
                timezone,
            ),
            ok=lambda summary: self.toast(summary, "ok"),
            err=lambda e: self.toast(f"Rotation : {e}", "error"),
        )

    def view_map_rotation(self):
        cfg = self._require_config()
        if not cfg:
            return
        self.run_cmd(
            scheduler.view_map_rotation_command(),
            ok=lambda out: self.toast(out.strip() or "Rotation inactive", "info"),
            err=lambda e: self.toast(f"Rotation : {e}", "error"),
            timeout=20,
        )

    def disable_map_rotation(self):
        if not self._allow("write"):
            return
        cfg = self._require_config()
        if not cfg:
            return
        self.run_cmd(
            scheduler.disable_map_rotation_command(),
            ok=lambda _: self.toast("Rotation des cartes désactivée.", "ok"),
            err=lambda e: self.toast(f"Rotation : {e}", "error"),
            timeout=20,
        )

    def refresh_maps(self):
        cfg = self._require_config()
        if not cfg:
            return
        self._map_mods = []
        self._map_missions = []
        self._active_map_template = ""
        self.map_status_label.setText("Carte active : lecture en cours…")
        self.run_cmd(commands.list_mods(cfg), ok=self.display_maps,
                     err=lambda e: self.toast(f"Cartes : {e}", "error"))
        self.run_cmd(commands.list_missions(cfg), ok=self._receive_map_missions,
                     err=lambda e: self.toast(f"Missions : {e}", "error"))
        self.run_func(
            partial(cfg_editor.read_serverdz, cfg),
            ok=self._receive_active_map,
            err=lambda e: self.toast(f"Carte active : {e}", "error"),
        )

    def display_maps(self, output):
        self._map_mods = [
            m.strip() for m in output.splitlines()
            if m.strip().startswith("@")
        ]
        self._render_maps()

    def _receive_map_missions(self, output):
        self._map_missions = [
            mission.strip() for mission in output.splitlines() if mission.strip()
        ]
        self._render_maps()

    def _receive_active_map(self, content):
        self._active_map_template = cfg_editor.get_value(content, "template") or ""
        self.map_status_label.setText(
            f"Carte active : {self._active_map_template or 'non définie'}"
        )
        self._render_maps()

    def _render_maps(self):
        """Affiche uniquement les cartes/missions réellement disponibles."""
        if not hasattr(self, "map_list"):
            return

        self.map_list.clear()
        entries = map_manager.discover_maps(
            self._map_mods, self._map_missions
        )

        if not entries:
            item = QListWidgetItem(
                "Aucune carte disponible — importe une mission ou installe un mod."
            )
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.map_list.addItem(item)
            return

        for entry in entries:
            label = entry.label
            mod_name = entry.mod_name
            template = entry.template
            available = entry.available
            active = bool(template and template == self._active_map_template)
            if template:
                suffix = "  ·  ACTIVE" if active else ""
                if available:
                    text = f"{label}  →  {template}{suffix}"
                else:
                    text = f"{label}  →  {template}  ·  mission absente"
            else:
                text = f"{label}  →  (template à définir)"
            item = QListWidgetItem(text)
            item.setData(
                Qt.ItemDataRole.UserRole,
                {"mod_name": mod_name, "template": template},
            )
            if not available:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                item.setToolTip(
                    "Importe d'abord ce dossier dans mpmissions."
                )
            self.map_list.addItem(item)
        self._annotate_map_updates()

    def _annotate_map_updates(self):
        """Colore en ambre les cartes à mettre à jour."""
        if not hasattr(self, "map_list"):
            return
        amber = QBrush(QColor(theme.AMBER))
        default = QBrush(QColor(theme.TEXT))
        for i in range(self.map_list.count()):
            item = self.map_list.item(i)
            name = item.text().split("→")[0].strip()
            if name in self._mod_updates:
                item.setForeground(amber)
                item.setToolTip("⬆ Mise à jour disponible sur le Workshop")
            else:
                item.setForeground(default)
                if item.flags() & Qt.ItemFlag.ItemIsEnabled:
                    item.setToolTip("")

    def set_selected_map(self):
        if not self._allow("write"):
            return
        item = self.map_list.currentItem()
        if not item:
            self.toast("Sélectionne une carte.", "error")
            return
        if not (item.flags() & Qt.ItemFlag.ItemIsEnabled):
            self.toast("Cette mission n'est pas encore disponible sur le serveur.", "warn")
            return

        data = item.data(Qt.ItemDataRole.UserRole) or {}
        if not isinstance(data, dict):
            data = {"mod_name": data, "template": ""}
        mod_name = data.get("mod_name")
        template = (data.get("template") or "").strip()
        cfg = self._require_config()
        if not cfg:
            return
        if not template:
            # Carte inconnue : on demande le dossier mpmissions à utiliser,
            # avec une proposition basée sur le nom du mod.
            guess = map_manager.guess_template(mod_name)
            template, ok = QInputDialog.getText(
                self, "Template de mission",
                f"Dossier mpmissions à activer pour {mod_name} :", text=guess
            )
            if not ok or not template.strip():
                return
            template = template.strip()

        if self.op_worker is not None and self.op_worker.isRunning():
            self.toast("Une opération serveur est déjà en cours.", "warn")
            return
        map_name = mod_name or template
        if QMessageBox.question(
            self,
            "Changer de carte",
            f"Activer « {map_name} » avec la mission « {template} » ?\n\n"
            "La configuration sera écrite puis le serveur sera redémarré "
            "pour charger la nouvelle carte.",
        ) != QMessageBox.StandardButton.Yes:
            return

        # Une sauvegarde complète est obligatoire avant toute modification.
        # Si elle échoue, la configuration de carte ne bouge pas.
        self.toast("Sauvegarde préventive avant changement de carte…", "info")
        self._run_streamed(
            commands.create_backup(cfg),
            "Sauvegarde préventive",
            on_done=lambda: self._write_selected_map(cfg, mod_name, template),
            sink=self._backup_progress,
        )

    def _write_selected_map(self, cfg, mod_name, template):
        self.toast("Écriture de la nouvelle carte sur le serveur…", "info")
        self.run_func(
            partial(
                cfg_editor.set_active_map,
                cfg,
                mod_name,
                template,
                map_manager.map_mod_names(),
            ),
            ok=lambda result: self._restart_after_map_change(
                cfg, result
            ),
            err=lambda e: self.toast(f"Échec : {e}", "error"),
        )

    def _restart_after_map_change(self, cfg, result):
        """Redémarre LGSM après l'écriture et vérifie le template relu."""
        template = result["template"]
        mod_name = result.get("mod_name") or "carte officielle"
        removed = result.get("removed_mods") or []
        self._active_map_template = template
        self._render_maps()
        details = f"Carte « {mod_name} » configurée."
        if removed:
            details += f" Ancienne(s) carte(s) retirée(s) : {', '.join(removed)}."
        self.log(details)
        self.toast("Redémarrage du serveur pour appliquer la carte…", "info")
        self.run_cmd(
            commands.server_action(cfg, "restart"),
            ok=lambda output: self._verify_map_after_restart(
                cfg, template, output
            ),
            err=lambda e: self.toast(f"Redémarrage impossible : {e}", "error"),
            timeout=180,
        )

    def _verify_map_after_restart(self, cfg, template, output):
        if output:
            self.log(output)
        self.run_cmd(
            commands.verify_map_loaded(cfg, template),
            ok=lambda status: self._read_map_after_runtime_check(
                cfg, template, status
            ),
            err=lambda e: self.toast(
                f"Redémarrage terminé, contrôle des logs impossible : {e}",
                "warn",
            ),
            timeout=45,
        )

    def _read_map_after_runtime_check(self, cfg, template, runtime_status):
        self.log(runtime_status)
        self.run_func(
            partial(cfg_editor.read_serverdz, cfg),
            ok=lambda content: self._on_map_verified(
                content, template, runtime_status
            ),
            err=lambda e: self.toast(
                f"Serveur redémarré, mais vérification impossible : {e}",
                "warn",
            ),
        )

    def _on_map_verified(self, content, expected_template, runtime_status):
        actual = cfg_editor.get_value(content, "template") or ""
        self.refresh_server_stats()
        self.refresh_maps()
        process_online = "PROCESS=online" in runtime_status
        runtime_ready = "MAP_READY" in runtime_status
        if actual == expected_template and runtime_ready:
            self.toast(
                f"Carte chargée sur le serveur : {expected_template}", "ok"
            )
            self._notify(
                "DayZ Manager — carte chargée",
                f"La carte {expected_template} est chargée sur le serveur.",
            )
        elif actual == expected_template and process_online:
            self.toast(
                f"Configuration correcte, mais chargement de « {expected_template} » "
                "non confirmé dans les logs.",
                "warn",
            )
        else:
            self.toast(
                f"Le serveur répond, mais le template relu est « {actual or 'vide'} ».",
                "error",
            )

    def import_mission_dialog(self):
        """Téléverse un dossier de mission local dans mpmissions.

        Beaucoup de mods de carte (dont @DeerIsle) n'embarquent pas la
        mission serveur : on permet de l'importer ici pour que le
        ``template`` posé par « Définir comme carte active » pointe sur un
        dossier réel."""
        cfg = self._require_config()
        if not cfg:
            return
        local_dir = QFileDialog.getExistingDirectory(
            self, "Dossier de mission à importer (ex. dayzOffline.deerisle)"
        )
        if not local_dir:
            return
        default_name = os.path.basename(os.path.normpath(local_dir))
        name, ok = QInputDialog.getText(
            self, "Nom du dossier de mission",
            "Nom du dossier sous mpmissions (doit correspondre au template) :",
            text=default_name,
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        try:
            _unused_mod, name = cfg_editor._validate_map_names(None, name)
        except ValueError as exc:
            self.toast(str(exc), "error")
            return
        self.toast(f"Import de « {name} » en cours…", "info")
        self.run_func(
            partial(cfg_editor.import_mission, cfg, local_dir, name),
            ok=lambda _: (self.toast(f"Mission « {name} » importée.", "ok"),
                          self.refresh_maps()),
            err=lambda e: self.toast(f"Échec de l'import : {e}", "error"),
        )

    # ================================================================== #
    # PAGE — Console
    # ================================================================== #
    def build_console_page(self, layout):
        self._header(layout, "Console", "Flux console live + exécution de commandes.")

        bar = QHBoxLayout()
        self.start_console_btn = QPushButton("▶  Démarrer")
        self.start_console_btn.setObjectName("success")
        self.stop_console_btn = QPushButton("■  Arrêter")
        self.stop_console_btn.setObjectName("danger")
        self.clear_console_btn = QPushButton("Vider")
        self.start_console_btn.clicked.connect(self.start_live_console)
        self.stop_console_btn.clicked.connect(self.stop_live_console)
        bar.addWidget(self.start_console_btn)
        bar.addWidget(self.stop_console_btn)
        bar.addWidget(self.clear_console_btn)
        bar.addStretch(1)
        layout.addLayout(bar)

        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(5000)
        self.console.setStyleSheet(
            f"background:{theme.BG}; color:#58a6ff; font-family:Consolas, monospace;"
        )
        self.clear_console_btn.clicked.connect(self.console.clear)
        layout.addWidget(self.console, 1)

        cmd_row = QHBoxLayout()
        self.console_cmd = QLineEdit()
        self.console_cmd.setPlaceholderText("Commande shell à exécuter (dans le dossier LGSM)…")
        self.console_cmd.returnPressed.connect(self.send_console_command)
        self.console_send_btn = QPushButton("Exécuter")
        self.console_send_btn.setObjectName("primary")
        self.console_send_btn.clicked.connect(self.send_console_command)
        cmd_row.addWidget(self.console_cmd, 1)
        cmd_row.addWidget(self.console_send_btn)
        layout.addLayout(cmd_row)

    def _console_append(self, line):
        self.console.appendPlainText(line)

    def start_live_console(self):
        if self.console_worker and self.console_worker.isRunning():
            self.toast("Console déjà active.", "info")
            return
        cfg = self._require_config()
        if not cfg:
            return
        command = commands.server_action(cfg, "console")
        self.console_worker = ConsoleWorker(command)
        self.console_worker.output.connect(self._console_append)
        self.console_worker.error.connect(
            lambda e: (self._console_append(f"[ERREUR] {e}"),
                       self.toast(f"Console : {e}", "error")))
        self.console_worker.stopped.connect(lambda: self.toast("Console arrêtée.", "info"))
        self.console_worker.start()
        self.toast("Console live démarrée.", "ok")

    def stop_live_console(self):
        if self.console_worker and self.console_worker.isRunning():
            self.console_worker.stop()
            self.console_worker.wait(2000)
        else:
            self.toast("Console non active.", "info")

    def send_console_command(self):
        if not self._allow("console"):
            return
        cmd = self.console_cmd.text().strip()
        if not cmd:
            return
        cfg = self._require_config()
        if not cfg:
            return
        self._console_append(f"$ {cmd}")
        self.console_cmd.clear()
        full = f"{commands.lgsm(cfg)} {cmd}"
        # Sortie live dans la console (les commandes peuvent être longues).
        self._run_streamed(
            full, "Commande", sink=self._console_append, done_toast=False,
        )

    # ================================================================== #
    # PAGE — Logs serveur
    # ================================================================== #
    def build_logs_page(self, layout):
        self._header(layout, "Logs serveur",
                     "Lecture des journaux .RPT / .ADM / .log (affichage ou suivi live).")

        bar = QHBoxLayout()
        self.refresh_logs_btn = QPushButton("⟳  Actualiser")
        self.view_log_btn = QPushButton("👁  Afficher (200 lignes)")
        self.view_log_btn.setObjectName("primary")
        self.follow_log_btn = QPushButton("▶  Suivre (live)")
        self.follow_log_btn.setObjectName("success")
        self.stop_log_btn = QPushButton("■  Arrêter")
        self.stop_log_btn.setObjectName("danger")
        self.clear_log_btn = QPushButton("Vider")
        self.log_search_edit = QLineEdit()
        self.log_search_edit.setPlaceholderText("Rechercher dans les logs…")
        self.log_filter_combo = QComboBox()
        self.log_filter_combo.addItems(["Tous", "Erreurs", "Crash", "Mods", "Joueurs"])
        self.log_search_btn = QPushButton("🔎 Filtrer")
        self.refresh_logs_btn.clicked.connect(self.refresh_logs)
        self.view_log_btn.clicked.connect(self.view_selected_log)
        self.follow_log_btn.clicked.connect(self.follow_selected_log)
        self.stop_log_btn.clicked.connect(self.stop_log_follow)
        self.log_search_btn.clicked.connect(self.search_logs)
        for b in (self.refresh_logs_btn, self.view_log_btn, self.follow_log_btn,
                  self.stop_log_btn, self.clear_log_btn, self.log_search_btn):
            bar.addWidget(b)
        bar.addWidget(self.log_filter_combo)
        bar.addWidget(self.log_search_edit, 1)
        bar.addStretch(1)
        layout.addLayout(bar)

        body = QHBoxLayout()
        self.log_list = QListWidget()
        self.log_list.setFixedWidth(360)
        self.log_list.itemDoubleClicked.connect(lambda _: self.view_selected_log())
        body.addWidget(self.log_list)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(8000)
        self.log_view.setStyleSheet(
            f"background:{theme.BG}; color:{theme.TEXT}; font-family:Consolas, monospace;"
        )
        self.clear_log_btn.clicked.connect(self.log_view.clear)
        body.addWidget(self.log_view, 1)
        layout.addLayout(body, 1)

    def refresh_logs(self):
        cfg = self._require_config()
        if not cfg:
            return
        self.run_cmd(commands.list_logs(cfg), ok=self._populate_logs,
                     err=lambda e: self.toast(f"Logs : {e}", "error"))

    def search_logs(self):
        cfg = self._require_config()
        if not cfg:
            return
        self.log_view.setPlainText("Recherche dans les logs…")
        self.run_cmd(
            commands.search_logs(
                cfg,
                self.log_search_edit.text(),
                self.log_filter_combo.currentText(),
            ),
            ok=lambda output: self.log_view.setPlainText(
                output.strip() or "Aucun résultat."
            ),
            err=lambda e: self.toast(f"Recherche logs : {e}", "error"),
            timeout=45,
        )

    def _populate_logs(self, output):
        self.log_list.clear()
        rows = [ln for ln in output.splitlines() if ln.strip()]
        if not rows:
            self.log_list.addItem("Aucun log trouvé")
            return
        for line in rows:
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            _mtime, size, path = parts
            try:
                size_kb = int(size) / 1024
            except ValueError:
                size_kb = 0
            name = path.rsplit("/", 1)[-1]
            item = QListWidgetItem(f"{name}   ({size_kb:,.0f} Ko)".replace(",", " "))
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path)
            self.log_list.addItem(item)

    def _selected_log_path(self):
        item = self.log_list.currentItem()
        if not item:
            self.toast("Sélectionne un fichier de log.", "error")
            return None
        path = item.data(Qt.ItemDataRole.UserRole)
        if not path:
            self.toast("Élément invalide.", "error")
            return None
        return path

    def view_selected_log(self):
        path = self._selected_log_path()
        if not path:
            return
        cfg = self._require_config()
        if not cfg:
            return
        self.stop_log_follow()
        self.run_cmd(
            commands.tail_log(cfg, path, 200),
            ok=lambda out: self.log_view.setPlainText(out or "(fichier vide)"),
            err=lambda e: self.toast(f"Lecture : {e}", "error"),
            timeout=30,
        )

    def follow_selected_log(self):
        path = self._selected_log_path()
        if not path:
            return
        cfg = self._require_config()
        if not cfg:
            return
        if self.log_tail_worker and self.log_tail_worker.isRunning():
            self.toast("Suivi déjà actif.", "info")
            return
        self.log_view.clear()
        self.log_tail_worker = ConsoleWorker(commands.follow_log(cfg, path))
        self.log_tail_worker.output.connect(self.log_view.appendPlainText)
        self.log_tail_worker.error.connect(lambda e: self.toast(f"Suivi : {e}", "error"))
        self.log_tail_worker.stopped.connect(lambda: self.toast("Suivi arrêté.", "info"))
        self.log_tail_worker.start()
        self.toast(f"Suivi live de {path.rsplit('/', 1)[-1]}…", "ok")

    def stop_log_follow(self):
        if self.log_tail_worker and self.log_tail_worker.isRunning():
            self.log_tail_worker.stop()
            self.log_tail_worker.wait(2000)

    # ================================================================== #
    # PAGE — Sauvegardes
    # ================================================================== #
    def build_backups_page(self, layout):
        self._header(layout, "Sauvegardes",
                     "Archive mpmissions + serverDZ.cfg, puis restaure au besoin.")

        bar = QHBoxLayout()
        self.create_backup_btn = QPushButton("➕  Créer une sauvegarde")
        self.create_backup_btn.setObjectName("success")
        self.refresh_backups_btn = QPushButton("⟳  Actualiser")
        self.restore_backup_btn = QPushButton("↩  Restaurer")
        self.restore_backup_btn.setObjectName("primary")
        self.delete_backup_btn = QPushButton("🗑  Supprimer")
        self.delete_backup_btn.setObjectName("danger")
        self.create_backup_btn.clicked.connect(self.create_backup)
        self.refresh_backups_btn.clicked.connect(self.refresh_backups)
        self.restore_backup_btn.clicked.connect(self.restore_backup)
        self.delete_backup_btn.clicked.connect(self.delete_backup)
        for b in (self.create_backup_btn, self.refresh_backups_btn,
                  self.restore_backup_btn, self.delete_backup_btn):
            bar.addWidget(b)
        bar.addStretch(1)
        layout.addLayout(bar)

        self.backup_list = QListWidget()
        layout.addWidget(self.backup_list, 1)

    def refresh_backups(self):
        cfg = self._require_config()
        if not cfg:
            return
        self.run_cmd(commands.list_backups(cfg), ok=self._populate_backups,
                     err=lambda e: self.toast(f"Sauvegardes : {e}", "error"))

    def _populate_backups(self, output):
        self.backup_list.clear()
        items = [x.strip() for x in output.splitlines() if x.strip()]
        if not items:
            self.backup_list.addItem("Aucune sauvegarde")
            return
        for it in items:
            self.backup_list.addItem(it)

    def _backup_progress(self, line):
        """Affiche en direct l'élément en cours d'archivage/restauration."""
        line = line.strip()
        if line:
            self.toast(line[:70], "info")

    def create_backup(self):
        if not self._allow("write"):
            return
        cfg = self._require_config()
        if not cfg:
            return
        label, ok = QInputDialog.getText(
            self,
            "Nom de la sauvegarde",
            "Libellé optionnel (ex. avant-maj ou avant-event) :",
        )
        if not ok:
            return
        try:
            command = commands.create_backup(cfg, label)
        except ValueError as exc:
            self.toast(str(exc), "error")
            return
        self.toast("Création de la sauvegarde…", "info")
        self._run_streamed(
            command, "Sauvegarde",
            on_done=self.refresh_backups, sink=self._backup_progress,
        )

    def _selected_backup(self):
        item = self.backup_list.currentItem()
        if not item or not item.text().endswith(".tar.gz"):
            self.toast("Sélectionne une sauvegarde.", "error")
            return None
        return item.text()

    def restore_backup(self):
        if not self._allow("restore"):
            return
        name = self._selected_backup()
        if not name:
            return
        if QMessageBox.question(self, "Restaurer",
                                f"Restaurer {name} ? Les fichiers actuels seront écrasés.") \
                != QMessageBox.StandardButton.Yes:
            return
        cfg = self._require_config()
        if not cfg:
            return
        self.toast("Restauration en cours…", "info")
        self._run_streamed(
            commands.restore_backup(cfg, name), "Restauration",
            sink=self._backup_progress,
        )

    def delete_backup(self):
        if not self._allow("restore"):
            return
        name = self._selected_backup()
        if not name:
            return
        if QMessageBox.question(self, "Supprimer", f"Supprimer {name} ?") != \
                QMessageBox.StandardButton.Yes:
            return
        cfg = self._require_config()
        if not cfg:
            return
        self.run_cmd(
            commands.delete_backup(cfg, name),
            ok=lambda _: (self.toast("Sauvegarde supprimée.", "ok"), self.refresh_backups()),
            err=lambda e: self.toast(f"Échec : {e}", "error"),
        )

    # ================================================================== #
    # PAGE — Planification (redémarrages programmés)
    # ================================================================== #
    def build_schedule_page(self, layout):
        self._header(layout, "Planification",
                     "Redémarrages automatiques (cron serveur) + alertes joueurs.")

        panel = self._panel()
        form = QFormLayout(panel)
        form.setContentsMargins(16, 16, 16, 16)
        form.setVerticalSpacing(12)

        self.sched_times_edit = QLineEdit()
        self.sched_times_edit.setPlaceholderText("Ex : 04:00, 12:00, 20:00")
        self.sched_warn_spin = QSpinBox()
        self.sched_warn_spin.setRange(0, 120)
        self.sched_warn_spin.setSuffix(" min avant")
        self.sched_marks_edit = QLineEdit()
        self.sched_marks_edit.setPlaceholderText("10,5,1")
        self.sched_message_edit = QLineEdit()
        self.sched_message_edit.setPlaceholderText("Redemarrage dans {m} minute(s)")
        self.sched_timezone_edit = QLineEdit()
        self.sched_timezone_edit.setPlaceholderText("Europe/Paris")

        form.addRow("Heures de redémarrage", self.sched_times_edit)
        form.addRow("Préavis", self.sched_warn_spin)
        form.addRow("Paliers d'alerte (min)", self.sched_marks_edit)
        form.addRow("Message ({m} = minutes)", self.sched_message_edit)
        form.addRow("Fuseau horaire cron", self.sched_timezone_edit)
        layout.addWidget(panel)

        rcon_panel = self._panel()
        rform = QFormLayout(rcon_panel)
        rform.setContentsMargins(16, 16, 16, 16)
        rform.setVerticalSpacing(12)
        self.rcon_enabled_check = QCheckBox("Activer les alertes RCON BattlEye (say -1)")
        self.rcon_port_spin = QSpinBox()
        self.rcon_port_spin.setRange(1, 65535)
        self.rcon_pass_edit = QLineEdit()
        self.rcon_pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        rform.addRow("", self.rcon_enabled_check)
        rform.addRow("Port RCON", self.rcon_port_spin)
        rform.addRow("Mot de passe RCON", self.rcon_pass_edit)
        self.rcon_setup_btn = QPushButton("🔌  Activer la RCON sur le serveur")
        self.rcon_setup_btn.setToolTip(
            "Écrit beserver_x64.cfg (port + mot de passe) dans le dossier "
            "BattlEye auto-détecté, puis propose le redémarrage."
        )
        self.rcon_setup_btn.clicked.connect(self.enable_rcon_on_server)
        rform.addRow("Config serveur", self.rcon_setup_btn)
        layout.addWidget(rcon_panel)

        # ---- Auto-restart en cas de crash (LGSM monitor) ----
        mon_panel = self._panel()
        mv = QVBoxLayout(mon_panel)
        mv.setContentsMargins(16, 16, 16, 16)
        mv.setSpacing(10)
        mtitle = QLabel("🔁  Auto-restart en cas de crash (LGSM monitor)")
        mtitle.setStyleSheet("font-weight: 700;")
        mv.addWidget(mtitle)
        mdesc = QLabel(
            "Un cron vérifie le serveur à intervalle régulier et le relance "
            "automatiquement s'il est tombé."
        )
        mdesc.setWordWrap(True)
        mdesc.setStyleSheet(f"color: {theme.MUTED}; font-size: 9.5pt;")
        mv.addWidget(mdesc)
        mrow = QHBoxLayout()
        mrow.addWidget(QLabel("Vérifier toutes les"))
        self.monitor_interval_spin = QSpinBox()
        self.monitor_interval_spin.setRange(1, 60)
        self.monitor_interval_spin.setValue(5)
        self.monitor_interval_spin.setSuffix(" min")
        mrow.addWidget(self.monitor_interval_spin)
        mrow.addStretch(1)
        self.enable_monitor_btn = QPushButton("✔  Activer")
        self.enable_monitor_btn.setObjectName("success")
        self.disable_monitor_btn = QPushButton("✖  Désactiver")
        self.disable_monitor_btn.setObjectName("danger")
        self.enable_monitor_btn.clicked.connect(self.enable_monitor)
        self.disable_monitor_btn.clicked.connect(self.disable_monitor)
        mrow.addWidget(self.enable_monitor_btn)
        mrow.addWidget(self.disable_monitor_btn)
        mv.addLayout(mrow)
        layout.addWidget(mon_panel)

        row = QHBoxLayout()
        self.apply_sched_btn = QPushButton("✔  Appliquer la planification")
        self.apply_sched_btn.setObjectName("success")
        self.view_sched_btn = QPushButton("👁  Voir le crontab")
        self.disable_sched_btn = QPushButton("✖  Désactiver")
        self.disable_sched_btn.setObjectName("danger")
        self.apply_sched_btn.clicked.connect(self.apply_schedule)
        self.view_sched_btn.clicked.connect(self.view_schedule)
        self.disable_sched_btn.clicked.connect(self.disable_schedule)
        row.addWidget(self.apply_sched_btn)
        row.addWidget(self.view_sched_btn)
        row.addWidget(self.disable_sched_btn)
        row.addStretch(1)
        layout.addLayout(row)

        self.sched_output = QPlainTextEdit()
        self.sched_output.setReadOnly(True)
        self.sched_output.setMaximumBlockCount(200)
        self.sched_output.setStyleSheet("font-family: Consolas, monospace;")
        layout.addWidget(self.sched_output, 1)

        note = QLabel(
            "ℹ️ La planification s'installe dans le crontab du serveur : elle "
            "fonctionne même application fermée. Les alertes en jeu nécessitent "
            "que la RCON BattlEye soit activée côté serveur (BEServer*.cfg)."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {theme.MUTED}; font-size: 9.5pt;")
        layout.addWidget(note)

        self._load_schedule_fields()

    def _load_schedule_fields(self):
        cfg = self.current_config()
        self.sched_times_edit.setText(cfg.get("schedule_times", ""))
        self.sched_warn_spin.setValue(int(cfg.get("schedule_warn", 10) or 0))
        self.sched_marks_edit.setText(cfg.get("schedule_marks", "10,5,1"))
        self.sched_message_edit.setText(cfg.get("schedule_message", ""))
        self.sched_timezone_edit.setText(
            cfg.get("schedule_timezone", "Europe/Paris")
        )
        self.rcon_enabled_check.setChecked(bool(cfg.get("rcon_enabled", False)))
        self.rcon_port_spin.setValue(int(cfg.get("rcon_port", 2310) or 2310))
        self.rcon_pass_edit.setText(cfg.get("rcon_password", ""))

    def _save_schedule_fields(self):
        cfg = self.current_config()
        cfg.update({
            "schedule_times": self.sched_times_edit.text().strip(),
            "schedule_warn": self.sched_warn_spin.value(),
            "schedule_marks": self.sched_marks_edit.text().strip() or "10,5,1",
            "schedule_message": self.sched_message_edit.text().strip()
                or "Redemarrage du serveur dans {m} minute(s)",
            "schedule_timezone": self.sched_timezone_edit.text().strip()
                or "Europe/Paris",
            "rcon_enabled": self.rcon_enabled_check.isChecked(),
            "rcon_port": self.rcon_port_spin.value(),
            "rcon_password": self.rcon_pass_edit.text(),
        })
        ConfigManager.save(cfg)
        return cfg

    def apply_schedule(self):
        if not self._allow("write"):
            return
        cfg = self._require_config()
        if not cfg:
            return
        if not scheduler.parse_times(self.sched_times_edit.text()):
            self.toast("Renseigne au moins une heure valide (HH:MM).", "error")
            return
        cfg = self._save_schedule_fields()
        marks = [m.strip() for m in self.sched_marks_edit.text().replace(";", ",").split(",")
                 if m.strip().isdigit()]
        self.toast("Installation de la planification…", "info")
        self.run_func(
            partial(scheduler.apply, cfg, cfg["schedule_times"], cfg["schedule_warn"],
                    marks, cfg["schedule_message"], cfg.get("schedule_timezone", "")),
            ok=lambda summary: (self.toast(summary, "ok"), self.view_schedule()),
            err=lambda e: self.toast(f"Échec : {e}", "error"),
        )

    def view_schedule(self):
        cfg = self._require_config()
        if not cfg:
            return
        self.run_cmd(
            scheduler.view_command(),
            ok=lambda out: self.sched_output.setPlainText(out or "(aucune planification)"),
            err=lambda e: self.sched_output.setPlainText(f"[ERREUR] {e}"),
            timeout=20,
        )

    def disable_schedule(self):
        if not self._allow("write"):
            return
        cfg = self._require_config()
        if not cfg:
            return
        if QMessageBox.question(self, "Désactiver",
                                "Retirer tous les redémarrages programmés ?") != \
                QMessageBox.StandardButton.Yes:
            return
        self.run_cmd(
            scheduler.disable_command(),
            ok=lambda _: (self.toast("Planification désactivée.", "ok"), self.view_schedule()),
            err=lambda e: self.toast(f"Échec : {e}", "error"),
            timeout=20,
        )

    # ----- Activation RCON côté serveur (écrit beserver_x64.cfg) -----
    def enable_rcon_on_server(self):
        if not self._allow("security"):
            return
        cfg = self._require_config()
        if not cfg:
            return
        if not self.rcon_pass_edit.text().strip():
            self.toast("Saisis un mot de passe RCON d'abord.", "warn")
            return
        if QMessageBox.question(
            self, "Activer la RCON",
            "Écrire la config BattlEye (beserver_x64.cfg) sur le serveur avec "
            "ce port et ce mot de passe ?\n\n"
            "Le serveur devra être redémarré ensuite pour prise en compte."
        ) != QMessageBox.StandardButton.Yes:
            return
        # Active aussi la RCON dans l'appli et persiste port/mot de passe.
        self.rcon_enabled_check.setChecked(True)
        cfg = self._save_schedule_fields()
        self.toast("Écriture de la config RCON…", "info")
        self.run_func(
            partial(rcon.enable_on_server, cfg),
            ok=self._on_rcon_enabled,
            err=lambda e: self.toast(f"RCON : {e}", "error"),
        )

    def _on_rcon_enabled(self, path):
        self._update_rcon_status()
        self.toast(f"Config RCON écrite : {path}", "ok")
        if QMessageBox.question(
            self, "Redémarrer le serveur",
            f"Config RCON écrite :\n{path}\n\n"
            "Redémarrer le serveur maintenant pour activer la RCON ?"
        ) == QMessageBox.StandardButton.Yes:
            self._nav_to("build_server_page")
            self.server_action("restart")

    # ----- Auto-restart (LGSM monitor) -----
    def enable_monitor(self):
        if not self._allow("write"):
            return
        cfg = self._require_config()
        if not cfg:
            return
        every = self.monitor_interval_spin.value()
        self.toast("Activation de l'auto-restart…", "info")
        self.run_func(
            partial(scheduler.apply_monitor, cfg, every),
            ok=lambda summary: (self.toast(summary, "ok"), self.view_schedule()),
            err=lambda e: self.toast(f"Échec : {e}", "error"),
        )

    def disable_monitor(self):
        if not self._allow("write"):
            return
        cfg = self._require_config()
        if not cfg:
            return
        self.run_cmd(
            scheduler.disable_monitor_command(),
            ok=lambda _: (self.toast("Auto-restart désactivé.", "ok"), self.view_schedule()),
            err=lambda e: self.toast(f"Échec : {e}", "error"),
            timeout=20,
        )

    # ================================================================== #
    # PAGE — Réglages
    # ================================================================== #
    def build_settings_page(self, layout):
        self._header(layout, "Réglages", "Connexion SSH, SteamCMD et options.")

        # La page Préférences contient beaucoup de champs. Dans un sous-onglet
        # de hauteur limitée, laisser les panneaux directement dans le layout
        # les comprimait jusqu'à écraser la hauteur des libellés. Un scroll
        # vertical conserve une taille lisible pour chaque ligne.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 6, 0)
        content_layout.setSpacing(12)

        panel = self._panel()
        form = QFormLayout(panel)
        form.setContentsMargins(16, 16, 16, 16)
        form.setVerticalSpacing(12)
        form.setHorizontalSpacing(24)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.host_edit = QLineEdit()
        self.port_edit = QSpinBox()
        self.port_edit.setRange(1, 65535)
        self.port_edit.setValue(22)
        self.user_edit = QLineEdit()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.path_edit = QLineEdit()
        self.steam_user_edit = QLineEdit()
        self.steam_pass_edit = QLineEdit()
        self.steam_pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.steam_api_key_edit = QLineEdit()
        self.steam_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.steam_api_key_edit.setPlaceholderText("steamcommunity.com/dev/apikey")
        self.app_id_edit = QLineEdit()
        self.install_retries_edit = QSpinBox()
        self.install_retries_edit.setRange(1, 10)
        self.install_retries_edit.setSuffix(" tentative(s)")
        self.install_retries_edit.setToolTip(
            "Nombre d'essais SteamCMD par mod. Entre deux essais, le cache de "
            "téléchargement obsolète est purgé (corrige l'erreur « chunk "
            "indicies out of date »)."
        )
        self.auto_refresh_check = QCheckBox("Actualiser automatiquement le tableau de bord")
        self.interval_edit = QSpinBox()
        self.interval_edit.setRange(10, 600)
        self.interval_edit.setSuffix(" s")
        self.role_combo = QComboBox()
        for role, label in permissions.ROLE_LABELS.items():
            self.role_combo.addItem(label, role)
        self.timezone_edit = QLineEdit()
        self.timezone_edit.setPlaceholderText("Europe/Paris")

        form.addRow("IP / Hôte", self.host_edit)
        form.addRow("Port SSH", self.port_edit)
        form.addRow("Utilisateur", self.user_edit)
        form.addRow("Mot de passe", self.password_edit)
        form.addRow("Chemin LGSM", self.path_edit)
        form.addRow("Steam : utilisateur", self.steam_user_edit)
        form.addRow("Steam : mot de passe", self.steam_pass_edit)

        self.sync_steam_btn = QPushButton("🔧  Enregistrer l'identifiant dans LGSM")
        self.sync_steam_btn.setObjectName("primary")
        self.sync_steam_btn.clicked.connect(self.sync_steam_with_lgsm)
        self.lgsm_steam_status = QLabel("LGSM : compte non vérifié")
        self.lgsm_steam_status.setStyleSheet(f"color: {theme.MUTED};")
        steam_row = QWidget()
        steam_layout = QHBoxLayout(steam_row)
        steam_layout.setContentsMargins(0, 0, 0, 0)
        steam_layout.addWidget(self.sync_steam_btn)
        steam_layout.addWidget(self.lgsm_steam_status, 1)
        form.addRow("Configuration distante", steam_row)

        form.addRow("Clé API Steam (Workshop)", self.steam_api_key_edit)
        form.addRow("App ID Workshop", self.app_id_edit)
        form.addRow("Tentatives d'installation", self.install_retries_edit)
        form.addRow("", self.auto_refresh_check)
        form.addRow("Intervalle d'actualisation", self.interval_edit)
        form.addRow("Rôle local", self.role_combo)
        form.addRow("Fuseau des planifications", self.timezone_edit)
        content_layout.addWidget(panel)

        notify_panel = self._panel()
        notify_form = QFormLayout(notify_panel)
        notify_form.setContentsMargins(16, 16, 16, 16)
        notify_form.setVerticalSpacing(8)
        notify_form.setHorizontalSpacing(24)
        notify_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        notify_form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        notify_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.discord_webhook_edit = QLineEdit()
        self.discord_webhook_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.discord_webhook_edit.setPlaceholderText("Webhook Discord")
        self.email_enabled_check = QCheckBox("Activer les notifications e-mail")
        self.email_host_edit = QLineEdit()
        self.email_port_spin = QSpinBox()
        self.email_port_spin.setRange(1, 65535)
        self.email_user_edit = QLineEdit()
        self.email_password_edit = QLineEdit()
        self.email_password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.email_from_edit = QLineEdit()
        self.email_to_edit = QLineEdit()
        notify_form.addRow("Webhook Discord", self.discord_webhook_edit)
        notify_form.addRow("", self.email_enabled_check)
        notify_form.addRow("Serveur SMTP", self.email_host_edit)
        notify_form.addRow("Port SMTP", self.email_port_spin)
        notify_form.addRow("Utilisateur SMTP", self.email_user_edit)
        notify_form.addRow("Mot de passe SMTP", self.email_password_edit)
        notify_form.addRow("Expéditeur", self.email_from_edit)
        notify_form.addRow("Destinataire", self.email_to_edit)
        content_layout.addWidget(notify_panel)

        row = QHBoxLayout()
        self.test_btn = QPushButton("🔌  Tester la connexion")
        self.save_settings_btn = QPushButton("💾  Enregistrer")
        self.save_settings_btn.setObjectName("success")
        self.test_btn.clicked.connect(self.test_connection)
        self.save_settings_btn.clicked.connect(self.save_settings)
        row.addWidget(self.test_btn)
        row.addWidget(self.save_settings_btn)
        row.addStretch(1)
        content_layout.addLayout(row)

        profile_row = QHBoxLayout()
        self.export_profile_btn = QPushButton("📤  Exporter le profil")
        self.import_profile_btn = QPushButton("📥  Importer le profil")
        self.test_notification_btn = QPushButton("🔔  Tester les notifications")
        self.export_profile_btn.clicked.connect(self.export_profile)
        self.import_profile_btn.clicked.connect(self.import_profile)
        self.test_notification_btn.clicked.connect(self.test_notification)
        profile_row.addWidget(self.export_profile_btn)
        profile_row.addWidget(self.import_profile_btn)
        profile_row.addWidget(self.test_notification_btn)
        profile_row.addStretch(1)
        content_layout.addLayout(profile_row)

        note = QLabel(
            "🔒 Les mots de passe sont stockés obfusqués (base64) dans config.json — "
            "ce n'est pas un chiffrement fort. Ne partage pas ce fichier."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {theme.MUTED}; font-size: 9.5pt;")
        content_layout.addWidget(note)
        content_layout.addStretch(1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

    def _load_settings_fields(self):
        cfg = self.current_config()
        self.host_edit.setText(cfg["host"])
        self.port_edit.setValue(int(cfg.get("port", 22)))
        self.user_edit.setText(cfg["user"])
        self.password_edit.setText(cfg["password"])
        self.path_edit.setText(cfg["lgsm_path"])
        self.steam_user_edit.setText(cfg.get("steam_user", "anonymous"))
        self.steam_pass_edit.setText(cfg.get("steam_pass", ""))
        self.steam_api_key_edit.setText(cfg.get("steam_api_key", ""))
        self.app_id_edit.setText(str(cfg.get("app_id", "221100")))
        self.install_retries_edit.setValue(int(cfg.get("install_retries", 3) or 3))
        self.auto_refresh_check.setChecked(bool(cfg.get("auto_refresh", True)))
        self.interval_edit.setValue(int(cfg.get("refresh_interval", 30)))
        role_index = self.role_combo.findData(cfg.get("user_role", "admin"))
        self.role_combo.setCurrentIndex(max(0, role_index))
        self.timezone_edit.setText(cfg.get("schedule_timezone", "Europe/Paris"))
        self.discord_webhook_edit.setText(cfg.get("discord_webhook", ""))
        self.email_enabled_check.setChecked(bool(cfg.get("notification_email_enabled")))
        self.email_host_edit.setText(cfg.get("notification_email_host", ""))
        self.email_port_spin.setValue(int(cfg.get("notification_email_port", 587) or 587))
        self.email_user_edit.setText(cfg.get("notification_email_user", ""))
        self.email_password_edit.setText(cfg.get("notification_email_password", ""))
        self.email_from_edit.setText(cfg.get("notification_email_from", ""))
        self.email_to_edit.setText(cfg.get("notification_email_to", ""))
        repository = (
            cfg.get("github_repository", GITHUB_REPOSITORY_URL)
            or GITHUB_REPOSITORY_URL
        )
        try:
            repository = (
                "https://github.com/"
                + updater.normalize_repository(repository)
            )
        except updater.UpdateError:
            # Laisser une valeur personnalisée invalide visible afin que
            # l'utilisateur puisse la corriger dans l'interface.
            pass
        self.github_repository_edit.setText(repository)

    def _gather_settings(self):
        return {
            "host": self.host_edit.text().strip(),
            "port": self.port_edit.value(),
            "user": self.user_edit.text().strip(),
            "password": self.password_edit.text(),
            "lgsm_path": self.path_edit.text().strip() or "/home/florent",
            "steam_user": self.steam_user_edit.text().strip() or "anonymous",
            "steam_pass": self.steam_pass_edit.text(),
            "steam_api_key": self.steam_api_key_edit.text().strip(),
            "app_id": self.app_id_edit.text().strip() or "221100",
            "install_retries": self.install_retries_edit.value(),
            "auto_refresh": self.auto_refresh_check.isChecked(),
            "refresh_interval": self.interval_edit.value(),
            "user_role": self.role_combo.currentData() or "admin",
            "schedule_timezone": self.timezone_edit.text().strip() or "Europe/Paris",
            "discord_webhook": self.discord_webhook_edit.text().strip(),
            "notification_email_enabled": self.email_enabled_check.isChecked(),
            "notification_email_host": self.email_host_edit.text().strip(),
            "notification_email_port": self.email_port_spin.value(),
            "notification_email_user": self.email_user_edit.text().strip(),
            "notification_email_password": self.email_password_edit.text(),
            "notification_email_from": self.email_from_edit.text().strip(),
            "notification_email_to": self.email_to_edit.text().strip(),
            "github_repository": self.github_repository_edit.text().strip(),
        }

    def save_settings(self):
        # On part de la config complète pour ne pas écraser les réglages
        # gérés par d'autres pages (RCON, planification…) avec les valeurs
        # par défaut lors de la fusion dans ConfigManager.save.
        cfg = self.current_config()
        gathered = self._gather_settings()
        if gathered["user_role"] != cfg.get("user_role", "admin") \
                and not permissions.can(cfg.get("user_role"), "security"):
            self.toast("Seul un administrateur peut modifier le rôle local.", "warn")
            gathered["user_role"] = cfg.get("user_role", "admin")
        cfg.update(gathered)
        ConfigManager.save(cfg)
        self.apply_connection()
        self._configure_timer()
        self.toast("Réglages enregistrés.", "ok")

    def sync_steam_with_lgsm(self):
        """Écrit l'identifiant Steam de l'interface dans le common.cfg distant."""
        if not self._allow("write"):
            return
        cfg = self.current_config()
        cfg.update(self._gather_settings())
        if not cfg.get("host") or not cfg.get("user"):
            self.toast("Configure d'abord la connexion SSH.", "error")
            return
        username = (cfg.get("steam_user") or "").strip()
        if not username or username.lower() in {"anonymous", "username"}:
            self.toast(
                "Renseigne un véritable identifiant Steam avant la synchronisation.",
                "error",
            )
            return
        self.sync_steam_btn.setEnabled(False)
        self.toast("Écriture de steamuser dans LGSM…", "info")

        def on_ok(value):
            self.sync_steam_btn.setEnabled(True)
            self.lgsm_steam_status.setText(f"LGSM : {value}")
            self.lgsm_steam_status.setStyleSheet(f"color: {theme.GREEN};")
            self.toast("Identifiant Steam enregistré dans LGSM.", "ok")

        def on_err(error):
            self.sync_steam_btn.setEnabled(True)
            self.lgsm_steam_status.setText("LGSM : échec de synchronisation")
            self.lgsm_steam_status.setStyleSheet(f"color: {theme.RED};")
            self.toast(f"Synchronisation Steam impossible : {error}", "error")

        self.run_func(
            partial(cfg_editor.set_steam_user, cfg, username),
            ok=on_ok,
            err=on_err,
        )

    def test_notification(self):
        cfg = self.current_config()
        cfg.update(self._gather_settings())
        if not (cfg.get("discord_webhook") or cfg.get("notification_email_enabled")):
            self.toast("Configure au moins un canal de notification.", "warn")
            return
        self.toast("Envoi du test de notification…", "info")
        self.run_net(
            partial(
                notifications.send,
                cfg,
                "DayZ Manager — test",
                "Les notifications DayZ Manager fonctionnent.",
            ),
            ok=lambda result: self.toast(result, "ok"),
            err=lambda e: self.toast(f"Notification : {e}", "error"),
        )

    def export_profile(self):
        path, _filter = QFileDialog.getSaveFileName(
            self, "Exporter le profil", "dayz-manager-profile.json",
            "Profil JSON (*.json)",
        )
        if not path:
            return
        cfg = self.current_config()
        if not cfg.get("host") or not cfg.get("user"):
            try:
                profiles.export_bundle(path, cfg, profiles.load_profiles())
            except OSError as exc:
                self.toast(f"Export impossible : {exc}", "error")
                return
            self.toast("Profil exporté (secrets exclus).", "ok")
            return
        self.toast("Lecture de la configuration serveur pour export…", "info")
        self.run_func(
            partial(cfg_editor.read_serverdz, cfg),
            ok=lambda server: self._export_profile_with_server(
                path, cfg, server
            ),
            err=lambda e: self.toast(f"Export serveur impossible : {e}", "error"),
        )

    def _export_profile_with_server(self, path, cfg, server_content):
        self.run_func(
            partial(connection.read_file, cfg_editor.common_cfg_path(cfg)),
            ok=lambda common: self._write_profile_export(
                path, cfg, server_content, common
            ),
            err=lambda e: self.toast(f"Export common.cfg impossible : {e}", "error"),
        )

    def _write_profile_export(self, path, cfg, server_content, common_content):
        try:
            profiles.export_bundle(
                path,
                cfg,
                profiles.load_profiles(),
                {"serverDZ": server_content, "common.cfg": common_content},
            )
        except OSError as exc:
            self.toast(f"Export impossible : {exc}", "error")
            return
        self.toast("Profil serveur exporté (secrets exclus).", "ok")

    def import_profile(self):
        if not self._allow("security"):
            return
        path, _filter = QFileDialog.getOpenFileName(
            self, "Importer le profil", "", "Profil JSON (*.json)"
        )
        if not path:
            return
        try:
            settings, map_profiles, server_files = profiles.import_bundle(path)
            cfg = self.current_config()
            cfg.update(settings)
            ConfigManager.save(cfg)
            profiles.save_profiles(map_profiles)
        except (OSError, ValueError, TypeError) as exc:
            self.toast(f"Import impossible : {exc}", "error")
            return
        self._load_settings_fields()
        if hasattr(self, "map_profile_combo"):
            self._load_map_profiles()
        self.apply_connection()
        self._configure_timer()
        if server_files and cfg.get("host") and cfg.get("user"):
            if QMessageBox.question(
                self,
                "Restaurer la configuration serveur",
                "Cet export contient serverDZ.cfg et common.cfg. "
                "Créer une sauvegarde puis les restaurer sur le serveur ?",
            ) == QMessageBox.StandardButton.Yes:
                self._run_streamed(
                    commands.create_backup(cfg, "before-import"),
                    "Sauvegarde avant import",
                    on_done=lambda: self.run_func(
                        partial(cfg_editor.restore_snapshot, cfg, server_files),
                        ok=lambda _: self.toast(
                            "Configuration serveur restaurée.", "ok"
                        ),
                        err=lambda e: self.toast(
                            f"Restauration serveur impossible : {e}", "error"
                        ),
                    ),
                    sink=self._backup_progress,
                )
            else:
                self.toast("Profil local importé, configuration serveur conservée.", "ok")
        else:
            self.toast("Profil importé. Les secrets locaux ont été conservés.", "ok")

    def test_connection(self):
        data = self._gather_settings()
        if not data["host"] or not data["user"]:
            self.toast("IP et utilisateur obligatoires.", "error")
            return
        connection.configure(data["host"], data["user"], data["password"], data["port"])
        self._set_pill("connecting")
        self.toast("Test de connexion…", "info")
        self.run_cmd(
            "echo CONNECTED",
            ok=lambda _: (self.toast("Connexion SSH réussie ✔", "ok"),
                          QMessageBox.information(self, "Connexion", "Connexion SSH réussie.")),
            err=lambda e: (self.toast("Connexion échouée.", "error"),
                           QMessageBox.critical(self, "Erreur SSH", str(e))),
            timeout=20,
        )

    # ================================================================== #
    # Mises à jour GitHub
    # ================================================================== #
    def _update_repository(self):
        value = self.github_repository_edit.text().strip()
        if value:
            return value
        return (
            ConfigManager.load().get("github_repository")
            or GITHUB_REPOSITORY_URL
        )

    def _auto_check_for_updates(self):
        if self._update_repository():
            self.check_for_updates(silent=True)

    def save_update_repository(self):
        repository = (
            self.github_repository_edit.text().strip()
            or GITHUB_REPOSITORY_URL
        )
        try:
            repository = (
                "https://github.com/"
                + updater.normalize_repository(repository)
            )
        except updater.UpdateError as exc:
            self.toast(str(exc), "error")
            return
        cfg = self.current_config()
        cfg["github_repository"] = repository
        ConfigManager.save(cfg)
        self.github_repository_edit.setText(repository)
        self.update_status_label.setText(
            "Dépôt enregistré. Lance une vérification pour rechercher une release."
        )
        self.toast("Dépôt GitHub enregistré.", "ok")

    def check_for_updates(self, silent=False):
        if self._update_check_running:
            return
        repository = self._update_repository()
        if not repository:
            self.update_status_label.setText(
                "Configure d’abord le dépôt GitHub des releases."
            )
            if not silent:
                self.toast("Dépôt GitHub non configuré.", "warn")
            return
        self._update_check_running = True
        self.check_updates_btn.setEnabled(False)
        self.download_update_btn.setEnabled(False)
        self.install_update_btn.setEnabled(False)
        self.update_status_label.setText("Vérification de la dernière release GitHub…")
        self.run_net(
            partial(updater.fetch_latest_release, repository, APP_VERSION),
            ok=lambda info: self._on_update_info(info, silent),
            err=lambda error: self._on_update_error(error, silent),
        )

    def _on_update_info(self, info, silent=False):
        self._update_check_running = False
        self.check_updates_btn.setEnabled(True)
        self._available_update = info if info.is_newer else None
        self._pending_update = None
        self.install_update_btn.setEnabled(False)
        self.download_update_btn.setEnabled(bool(info.is_newer))
        if info.is_newer:
            self.update_status_label.setText(
                f"Mise à jour disponible : v{info.version} ({info.asset_name})."
            )
            self.toast(f"Mise à jour v{info.version} disponible sur GitHub.", "info")
        else:
            self.update_status_label.setText(
                f"Application à jour — v{APP_VERSION}. Dernière release : v{info.version}."
            )
            if not silent:
                self.toast("DayZ Manager est déjà à jour.", "ok")

    def _on_update_error(self, error, silent=False):
        self._update_check_running = False
        self.check_updates_btn.setEnabled(True)
        self.download_update_btn.setEnabled(bool(self._available_update))
        message = str(error)
        self.update_status_label.setText(f"Vérification impossible : {message}")
        if not silent:
            self.toast(message, "error")

    def download_available_update(self):
        info = self._available_update
        if not info or not info.is_newer:
            self.toast("Aucune mise à jour disponible.", "warn")
            return
        self.check_updates_btn.setEnabled(False)
        self.download_update_btn.setEnabled(False)
        self.install_update_btn.setEnabled(False)
        self.update_status_label.setText(
            f"Téléchargement et vérification de v{info.version}…"
        )
        self.run_net(
            partial(updater.prepare_update, info),
            ok=self._on_update_ready,
            err=self._on_update_download_error,
        )

    def _on_update_ready(self, plan):
        self.check_updates_btn.setEnabled(True)
        self._pending_update = plan
        self.download_update_btn.setEnabled(False)
        self.install_update_btn.setEnabled(True)
        self.update_status_label.setText(
            f"v{plan.info.version} téléchargée et vérifiée. Prête à installer."
        )
        self.toast("Mise à jour téléchargée et vérifiée.", "ok")

    def _on_update_download_error(self, error):
        self.check_updates_btn.setEnabled(True)
        self.download_update_btn.setEnabled(bool(self._available_update))
        message = str(error)
        self.update_status_label.setText(f"Téléchargement impossible : {message}")
        self.toast(message, "error")

    def install_pending_update(self):
        plan = self._pending_update
        if plan is None:
            self.toast("Télécharge d’abord une mise à jour.", "warn")
            return
        if QMessageBox.question(
            self,
            "Installer la mise à jour",
            f"Installer v{plan.info.version} maintenant ?\n\n"
            "DayZ Manager va se fermer puis redémarrer automatiquement. "
            "Les réglages locaux seront conservés.",
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            updater.launch_update(plan)
        except updater.UpdateError as exc:
            self.toast(str(exc), "error")
            return
        self.toast("Installation en cours. L'application va redémarrer…", "ok")
        self.close()

    # ================================================================== #
    # PAGE — À propos
    # ================================================================== #
    def build_about_page(self, layout):
        self._header(layout, "À propos", "DayZ Manager")

        update_panel = self._panel()
        update_layout = QVBoxLayout(update_panel)
        update_layout.setContentsMargins(16, 16, 16, 16)
        update_layout.setSpacing(10)
        update_title = QLabel("Mises à jour")
        update_title.setStyleSheet("font-weight: 700; font-size: 12pt;")
        update_layout.addWidget(update_title)
        update_description = QLabel(
            f"Version installée : v{APP_VERSION}. Vérifie GitHub, télécharge "
            "le paquet vérifié par son hash SHA-256, puis redémarre pour l’installer."
        )
        update_description.setWordWrap(True)
        update_description.setStyleSheet(f"color: {theme.MUTED};")
        update_layout.addWidget(update_description)

        repository_row = QHBoxLayout()
        repository_row.addWidget(QLabel("Dépôt GitHub"))
        self.github_repository_edit = QLineEdit()
        self.github_repository_edit.setPlaceholderText(
            "https://github.com/owner/repository"
        )
        self.github_repository_edit.setToolTip(
            "Dépôt public contenant les releases GitHub. URL complète acceptée, "
            "par exemple https://github.com/owner/repository."
        )
        self.save_update_repository_btn = QPushButton("Enregistrer")
        self.save_update_repository_btn.clicked.connect(self.save_update_repository)
        repository_row.addWidget(self.github_repository_edit, 1)
        repository_row.addWidget(self.save_update_repository_btn)
        update_layout.addLayout(repository_row)

        self.update_status_label = QLabel("Aucune vérification effectuée.")
        self.update_status_label.setObjectName("updateStatus")
        update_layout.addWidget(self.update_status_label)
        update_buttons = QHBoxLayout()
        self.check_updates_btn = QPushButton("Vérifier maintenant")
        self.check_updates_btn.setObjectName("primary")
        self.download_update_btn = QPushButton("Télécharger la mise à jour")
        self.download_update_btn.setEnabled(False)
        self.install_update_btn = QPushButton("Installer et redémarrer")
        self.install_update_btn.setObjectName("success")
        self.install_update_btn.setEnabled(False)
        self.check_updates_btn.clicked.connect(self.check_for_updates)
        self.download_update_btn.clicked.connect(self.download_available_update)
        self.install_update_btn.clicked.connect(self.install_pending_update)
        update_buttons.addWidget(self.check_updates_btn)
        update_buttons.addWidget(self.download_update_btn)
        update_buttons.addWidget(self.install_update_btn)
        update_buttons.addStretch(1)
        update_layout.addLayout(update_buttons)
        layout.addWidget(update_panel)

        panel = self._panel()
        v = QVBoxLayout(panel)
        v.setContentsMargins(20, 20, 20, 20)
        text = QTextEdit()
        text.setReadOnly(True)
        text.setPlainText(
            f"DayZ Manager — v{APP_VERSION}\n"
            "Auteur : Yann Escarbassière\n\n"
            "Nouveautés v0.9.2 :\n"
            "  • Page de connexion corrigée : les libellés restent lisibles\n"
            "    quelle que soit la hauteur de la fenêtre\n"
            "  • URL officielle GitHub préremplie pour les mises à jour\n"
            "  • Build automatique après chaque push sur main\n"
            "  • Profils de cartes : mission, mods ordonnés et paramètres LGSM\n"
            "  • Rotation automatique des cartes par horaires et fuseau\n"
            "  • Installation d'une carte depuis une collection Workshop\n"
            "  • Dépendances requiredAddons et comparaison local/serveur\n"
            "  • Recherche des logs par erreurs, crashs, mods ou joueurs\n"
            "  • Santé serveur, dernière sauvegarde et mods obsolètes sur l'accueil\n"
            "  • Notifications Discord/e-mail, export de profil et rôles locaux\n"
            "  • Sauvegardes nommées et détection contrôlée des arrêts\n\n"
            "  • Changement de carte complet : mission disponible, mod de carte,\n"
            "    retrait de l'ancienne carte, redémarrage LGSM et vérification\n"
            "    du template actif côté serveur\n"
            "  • Modération avancée : ban hors-ligne (GUID/SteamID64/IP),\n"
            "    import/export de bans\n"
            "  • Page « Fichiers & lancement » : paramètres de lancement LGSM,\n"
            "    mission active, éditeurs events.xml/globals.xml/cfgspawnable…\n"
            "    (validation XML/JSON avant enregistrement)\n\n"
            "Nouveautés v0.6.0 :\n"
            "  • Activation RCON en 1 clic (écrit beserver_x64.cfg côté serveur)\n"
            "  • Auto-restart en cas de crash (cron LGSM monitor)\n"
            "  • Badge « joueurs en ligne » dans la barre latérale\n"
            "  • Script de redémarrage programmé durci pour cron (HOME/PATH + log)\n\n"
            "Nouveautés v0.5.0 :\n"
            "  • Installation/MAJ de mods en TEMPS RÉEL (flux SteamCMD live,\n"
            "    barre de progression, bilan réussis/échecs)\n"
            "  • Fiabilité install : retry auto + purge du cache SteamCMD\n"
            "    (corrige « chunk indicies out of date »), nb d'essais réglable\n"
            "  • Actions serveur, console et sauvegardes streamées en direct\n"
            "  • Workshop : filtre cartes corrigé (tag « Terrain »)\n"
            "  • Page Cartes : toutes les cartes installées listées par nom\n"
            "  • Accès rapide à la config RCON depuis la page Joueurs\n"
            "  • Feedback amélioré (toasts auto-effacés, icônes d'état)\n\n"
            "Fonctionnalités :\n"
            "  • Connexion SSH persistante et réutilisée\n"
            "  • Tableau de bord temps réel (état, RAM, CPU, uptime…)\n"
            "  • Contrôle serveur LGSM (start/stop/restart/update/validate)\n"
            "  • Administration live des joueurs via RCON BattlEye\n"
            "    (liste en ligne, message privé, broadcast, kick, ban, bans)\n"
            "  • Éditeur de serverDZ.cfg (formulaire + texte brut)\n"
            "  • Éditeur d'économie types.xml (loot, quantités, rareté)\n"
            "  • Lecture des logs serveur (.RPT/.ADM/.log) + suivi live\n"
            "  • Gestion des mods : install, activation, ordre, suppression\n"
            "  • Détection des MAJ Workshop (mods & cartes) + maj groupée\n"
            "  • Navigateur Steam Workshop intégré (recherche, vignettes,\n"
            "    filtre cartes, collections, installation en un clic)\n"
            "  • Gestion des cartes\n"
            "  • Console live + exécution de commandes\n"
            "  • Sauvegardes : création / restauration / suppression\n"
            "  • Redémarrages programmés (cron serveur) + alertes RCON\n\n"
            "Technologies : Python · PyQt6 · Paramiko · API Web Steam · LinuxGSM\n\n"
            "© 2026"
        )
        v.addWidget(text)
        layout.addWidget(panel, 1)

    # ================================================================== #
    def closeEvent(self, event):
        try:
            self.players_timer.stop()
            self.stop_live_console()
            self.stop_log_follow()
            if self.op_worker is not None and self.op_worker.isRunning():
                self.op_worker.stop()
                self.op_worker.wait(2000)
        finally:
            super().closeEvent(event)
