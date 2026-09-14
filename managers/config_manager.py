"""Chargement / sauvegarde de la configuration.

Les secrets (mots de passe SSH et Steam) sont stockés *obfusqués* en
base64 — ce n'est PAS du chiffrement fort, mais cela évite d'avoir des
mots de passe lisibles en clair dans le fichier et, surtout, plus aucun
identifiant n'est codé en dur dans le code source.
"""

import base64
import json
from pathlib import Path
import sys

from version import GITHUB_REPOSITORY

SOURCE_ROOT = Path(__file__).resolve().parent.parent
APP_DATA_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else SOURCE_ROOT
)
APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = APP_DATA_DIR / "config.json"

# Préfixe marquant une valeur obfusquée.
_OBF = "b64:"

# Champs traités comme des secrets (obfusqués sur disque).
_SECRET_KEYS = (
    "password", "steam_pass", "steam_api_key", "rcon_password",
    "discord_webhook", "notification_email_password",
)

DEFAULTS = {
    "host": "",
    "user": "",
    "password": "",
    "port": 22,
    "lgsm_path": "/home/florent",
    "steam_user": "anonymous",
    "steam_pass": "",
    "steam_api_key": "",         # clé API Web Steam (navigateur Workshop)
    "app_id": "221100",          # DayZ dédié serveur Linux
    "install_retries": 3,        # tentatives SteamCMD par mod (purge cache entre 2)
    "auto_refresh": True,
    "refresh_interval": 30,      # secondes
    # Redémarrages programmés
    "schedule_times": "",        # ex. "04:00, 16:00"
    "schedule_warn": 10,         # préavis total en minutes
    "schedule_marks": "10,5,1",  # paliers d'alerte (minutes restantes)
    "schedule_message": "Redemarrage du serveur dans {m} minute(s)",
    # RCON BattlEye (alertes joueurs)
    "rcon_enabled": False,
    "rcon_port": 2310,
    "rcon_password": "",
    # Fuseau et notifications
    "schedule_timezone": "Europe/Paris",
    "discord_webhook": "",
    "notification_email_enabled": False,
    "notification_email_host": "",
    "notification_email_port": 587,
    "notification_email_user": "",
    "notification_email_password": "",
    "notification_email_from": "",
    "notification_email_to": "",
    # Mode d'accès local à l'application.
    "user_role": "admin",
    # Dépôt public utilisé par le vérificateur de mises à jour.
    "github_repository": GITHUB_REPOSITORY,
}


def _encode(value):
    if value is None:
        return ""
    return _OBF + base64.b64encode(str(value).encode()).decode()


def _decode(value):
    if isinstance(value, str) and value.startswith(_OBF):
        try:
            return base64.b64decode(value[len(_OBF):]).decode()
        except Exception:
            return ""
    return value


class ConfigManager:
    @staticmethod
    def load():
        data = dict(DEFAULTS)

        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data.update(json.load(f))
            except (json.JSONDecodeError, OSError):
                pass

        for key in _SECRET_KEYS:
            data[key] = _decode(data.get(key, ""))

        # Garde-fous de type.
        try:
            data["port"] = int(data.get("port", 22) or 22)
        except (TypeError, ValueError):
            data["port"] = 22
        try:
            data["notification_email_port"] = int(
                data.get("notification_email_port", 587) or 587
            )
        except (TypeError, ValueError):
            data["notification_email_port"] = 587
        if data.get("user_role") not in {"admin", "operator", "viewer"}:
            data["user_role"] = "admin"
        return data

    @staticmethod
    def save(data):
        out = dict(DEFAULTS)
        out.update(data)
        for key in _SECRET_KEYS:
            out[key] = _encode(out.get(key, ""))

        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=4)
