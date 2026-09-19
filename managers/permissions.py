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
    role = str(role or "viewer")
    if role not in _DENIED or role == "viewer":
        return action == "read"
    return action not in _DENIED[role]


def role_label(role):
    return ROLE_LABELS.get(role, ROLE_LABELS["admin"])
