"""Profils de serveur/cartes et export importables."""

import json
import re
from pathlib import Path

from managers.config_manager import APP_DATA_DIR


PROFILES_FILE = APP_DATA_DIR / "map_profiles.json"
PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}$")


def _read_json(path, default):
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value
    except (OSError, json.JSONDecodeError):
        return default


def load_profiles():
    value = _read_json(PROFILES_FILE, {})
    return value if isinstance(value, dict) else {}


def save_profiles(profiles):
    payload = {
        str(name): normalize_profile(str(name), profile)
        for name, profile in profiles.items()
    }
    temporary = PROFILES_FILE.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    temporary.replace(PROFILES_FILE)


def normalize_profile(name, profile):
    name = str(name or "").strip()
    if not PROFILE_NAME_RE.fullmatch(name):
        raise ValueError("Nom de profil invalide.")
    profile = profile if isinstance(profile, dict) else {}
    mods = profile.get("mods", [])
    if isinstance(mods, str):
        mods = [item.strip() for item in mods.replace(",", ";").split(";")]
    mods = list(dict.fromkeys(str(item).strip() for item in mods if str(item).strip()))
    return {
        "name": name,
        "mod_name": str(profile.get("mod_name") or "").strip() or None,
        "template": str(profile.get("template") or "").strip(),
        "mods": mods,
        "startparameters": str(profile.get("startparameters") or ""),
        "created_at": str(profile.get("created_at") or ""),
        "updated_at": str(profile.get("updated_at") or ""),
    }


def upsert_profile(name, profile):
    profiles = load_profiles()
    normalized = normalize_profile(name, profile)
    profiles[normalized["name"]] = normalized
    save_profiles(profiles)
    return normalized


def delete_profile(name):
    profiles = load_profiles()
    profiles.pop(str(name), None)
    save_profiles(profiles)


def export_bundle(path, settings, profiles, server_files=None):
    """Exporte réglages non secrets, profils et snapshot serveur optionnel."""
    safe_settings = dict(settings)
    for key in ("password", "steam_pass", "steam_api_key", "rcon_password",
                "discord_webhook", "notification_email_password"):
        safe_settings.pop(key, None)
    payload = {
        "format": "dayz-manager-profile-v1",
        "settings": safe_settings,
        "map_profiles": profiles,
        "server_files": server_files or {},
    }
    destination = Path(path)
    with destination.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def import_bundle(path):
    payload = _read_json(Path(path), {})
    if payload.get("format") != "dayz-manager-profile-v1":
        raise ValueError("Fichier de profil DayZ Manager non reconnu.")
    settings = payload.get("settings", {})
    profiles = payload.get("map_profiles", {})
    server_files = payload.get("server_files", {})
    if (not isinstance(settings, dict) or not isinstance(profiles, dict)
            or not isinstance(server_files, dict)):
        raise ValueError("Profil incomplet ou invalide.")
    normalized = {
        name: normalize_profile(name, value)
        for name, value in profiles.items()
    }
    return settings, normalized, server_files
