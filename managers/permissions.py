"""Permissions locales de l'interface d'administration."""


ROLE_LABELS = {
    "admin": "Administrateur",
    "operator": "Opérateur",
    "viewer": "Lecture seule",
}

_DENIED = {
    "viewer": {"write", "server_control", "moderation", "console"},
    "operator": {"server_update", "restore", "security"},
    "admin": set(),
}


def can(role, action):
    return action not in _DENIED.get(str(role or "admin"), _DENIED["admin"])


def role_label(role):
    return ROLE_LABELS.get(role, ROLE_LABELS["admin"])
