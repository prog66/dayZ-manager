"""Lecture / écriture des fichiers de configuration DayZ via SFTP.

- ``serverDZ.cfg`` : paramètres du serveur (hostname, maxPlayers, ...).
- ``common.cfg`` (LGSM) : contient la ligne ``mods="@A;@B"``.

On édite ces fichiers en Python (parsing + réécriture) plutôt qu'avec des
``sed`` distants : c'est plus sûr et on préserve le reste du fichier.
"""

import re

from ssh.connection import connection


# Ces noms sont utilisés dans des chemins SFTP. Ils doivent rester des noms
# simples afin qu'une saisie ne puisse viser un autre dossier distant.
_MISSION_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_MOD_NAME_RE = re.compile(r"^@[A-Za-z0-9][A-Za-z0-9_.-]*$")


def serverdz_path(cfg):
    # IMPORTANT : LGSM lance le serveur avec ``-config`` pointant sur
    # ``servercfgfullpath`` = ``${systemdir}/cfg/${selfname}.server.cfg``
    # (systemdir = serverfiles, selfname = dayzserver), et PAS sur
    # ``serverfiles/serverDZ.cfg``. Éditer serverDZ.cfg n'a aucun effet :
    # le serveur ne le lit jamais. On vise donc le vrai fichier.
    return f"{cfg['lgsm_path']}/serverfiles/cfg/dayzserver.server.cfg"


def common_cfg_path(cfg):
    return f"{cfg['lgsm_path']}/lgsm/config-lgsm/dayzserver/common.cfg"


def get_common_value(content, key):
    """Lit une valeur simple ``key="value"`` dans un fichier LGSM."""
    match = re.search(
        rf'^\s*{re.escape(key)}\s*=\s*(?:"([^"]*)"|([^\s#;]+))\s*$',
        content,
        re.MULTILINE,
    )
    if not match:
        return None
    return match.group(1) if match.group(1) is not None else match.group(2)


def _set_common_value_content(content, key, value):
    """Retourne ``common.cfg`` après remplacement d'une valeur simple."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
        raise ValueError("Clé LGSM invalide.")
    value = str(value).strip()
    if not value or any(char in value for char in '\r\n"'):
        raise ValueError("Valeur LGSM invalide.")
    line = f'{key}="{value}"'
    pattern = rf'^\s*{re.escape(key)}\s*=.*$'
    if re.search(pattern, content, re.MULTILINE):
        return re.sub(pattern, line, content, count=1, flags=re.MULTILINE)
    return (content.rstrip("\n") + "\n" if content else "") + line + "\n"


# --------------------------------------------------------------------- #
# serverDZ.cfg
# --------------------------------------------------------------------- #
# Champs exposés dans le formulaire : (clé, libellé, type).
SERVERDZ_FIELDS = [
    ("hostname", "Nom du serveur", "str"),
    ("password", "Mot de passe (joueurs)", "str"),
    ("passwordAdmin", "Mot de passe admin", "str"),
    ("maxPlayers", "Joueurs max", "int"),
    ("serverTime", "Heure serveur", "str"),
    ("serverTimePersistent", "Heure persistante", "int"),
    ("serverTimeAcceleration", "Accélération du temps", "int"),
    ("serverNightTimeAcceleration", "Accélération (nuit)", "int"),
    ("disableVoN", "Désactiver VoN", "int"),
    ("disable3rdPerson", "Désactiver 3e personne", "int"),
    ("disableCrosshair", "Désactiver viseur", "int"),
    ("respawnTime", "Temps de respawn", "int"),
    ("motd", "Message du jour", "str"),
]


def read_serverdz(cfg):
    return connection.read_file(serverdz_path(cfg))


def write_serverdz(cfg, content):
    connection.write_file(serverdz_path(cfg), content)


def get_value(content, key):
    """Renvoie la valeur d'une clé ``key = valeur;`` (sans guillemets)."""
    m = re.search(rf'^\s*{re.escape(key)}\s*=\s*(.+?);', content, re.MULTILINE)
    if not m:
        return None
    value = m.group(1).strip()
    if value.startswith('"') and value.endswith('"'):
        value = value[1:-1]
    return value


def set_value(content, key, value, quoted):
    """Remplace (ou ajoute) ``key = value;`` dans le contenu."""
    formatted = f'"{value}"' if quoted else str(value)
    line = f"{key} = {formatted};"
    pattern = rf'^\s*{re.escape(key)}\s*=\s*.+?;'
    if re.search(pattern, content, re.MULTILINE):
        return re.sub(pattern, line, content, count=1, flags=re.MULTILINE)
    # Clé absente : on l'ajoute en fin de fichier.
    sep = "" if content.endswith("\n") or not content else "\n"
    return content + sep + line + "\n"


# --------------------------------------------------------------------- #
# common.cfg : ligne mods=
# --------------------------------------------------------------------- #
def _read_common(cfg):
    try:
        return connection.read_file(common_cfg_path(cfg))
    except IOError:
        return ""


def get_steam_user(cfg):
    """Renvoie le compte Steam actuellement enregistré dans LGSM."""
    return get_common_value(_read_common(cfg), "steamuser")


def set_steam_user(cfg, username):
    """Écrit puis relit ``steamuser`` dans le ``common.cfg`` actif."""
    username = str(username or "").strip()
    if not username or username.lower() in {"anonymous", "username"}:
        raise ValueError(
            "Un véritable identifiant Steam est nécessaire pour LinuxGSM."
        )
    if any(char.isspace() for char in username):
        raise ValueError("L'identifiant Steam ne doit pas contenir d'espace.")

    path = common_cfg_path(cfg)
    content = _read_common(cfg)
    connection.write_file(
        path, _set_common_value_content(content, "steamuser", username)
    )
    written = get_steam_user(cfg)
    if written != username:
        raise IOError("La valeur steamuser n'a pas pu être vérifiée dans LGSM.")
    return written


def ensure_steam_user(cfg):
    """Garantit un ``steamuser`` utilisable avant start/restart/update.

    Une valeur déjà valide sur le serveur reste prioritaire. Les valeurs
    ``username`` et ``anonymous`` sont considérées comme des placeholders et
    sont remplacées avec le compte renseigné dans les réglages de l'app.
    """
    current = (get_steam_user(cfg) or "").strip()
    if current and current.lower() not in {"anonymous", "username"}:
        return current
    configured = (cfg.get("steam_user") or "").strip()
    if not configured or configured.lower() in {"anonymous", "username"}:
        raise ValueError(
            "Compte Steam manquant : renseigne-le dans Réglages puis "
            "synchronise-le avec LGSM."
        )
    return set_steam_user(cfg, configured)


def get_mods(cfg):
    """Liste ordonnée des mods dans la ligne ``mods="..."``.

    LGSM sépare les mods par ``\\;`` (point-virgule échappé) pour que le
    shell ne coupe pas la commande de lancement. On tolère aussi ``;`` nu
    et on retire l'antislash de séparation."""
    content = _read_common(cfg)
    m = re.search(r'^\s*mods\s*=\s*"([^"]*)"', content, re.MULTILINE)
    if not m:
        return []
    return [x.strip() for x in re.split(r'\\?;', m.group(1)) if x.strip()]


def _set_mods_content(content, mods):
    """Retourne ``common.cfg`` avec la liste de mods fournie."""
    value = "\\;".join(mods)
    line = f'mods="{value}"'
    if re.search(r'^\s*mods\s*=', content, re.MULTILINE):
        return re.sub(
            r'^\s*mods\s*=.*$', line, content, count=1, flags=re.MULTILINE
        )
    return (content.rstrip("\n") + "\n" if content else "") + line + "\n"


def set_mods(cfg, mods):
    """Réécrit la ligne ``mods="..."`` avec la liste fournie (ordre conservé).

    Les mods sont joints par ``\\;`` : LGSM passe ``-mod=${mods}`` à un
    shell, donc un ``;`` nu serait interprété comme fin de commande (le
    serveur ne chargerait que le 1er mod)."""
    content = _read_common(cfg)
    connection.write_file(common_cfg_path(cfg), _set_mods_content(content, mods))


def add_mod(cfg, mod_name):
    mods = get_mods(cfg)
    if mod_name not in mods:
        mods.append(mod_name)
        set_mods(cfg, mods)


# --------------------------------------------------------------------- #
# common.cfg : paramètres de lancement LGSM (startparameters="...")
# --------------------------------------------------------------------- #
def get_startparameters(cfg):
    content = _read_common(cfg)
    m = re.search(r'^\s*startparameters\s*=\s*"([^"]*)"', content, re.MULTILINE)
    return m.group(1) if m else ""


def _set_startparameters_content(content, params):
    line = f'startparameters="{params}"'
    if re.search(r'^\s*startparameters\s*=', content, re.MULTILINE):
        return re.sub(
            r'^\s*startparameters\s*=.*$', line, content,
            count=1, flags=re.MULTILINE,
        )
    return (content.rstrip("\n") + "\n" if content else "") + line + "\n"


def set_startparameters(cfg, params):
    content = _read_common(cfg)
    connection.write_file(
        common_cfg_path(cfg), _set_startparameters_content(content, params)
    )


def apply_profile(cfg, profile):
    """Applique une carte, sa liste de mods et ses paramètres de lancement."""
    profile = profile if isinstance(profile, dict) else {}
    mod_name, template = _validate_map_names(
        profile.get("mod_name"), profile.get("template")
    )
    if not mission_exists(cfg, template):
        raise IOError(
            f"Mission « {template} » introuvable sous {mpmissions_path(cfg)}."
        )
    mods = profile.get("mods", [])
    if isinstance(mods, str):
        mods = [item.strip() for item in re.split(r"[,;]", mods)]
    mods = list(dict.fromkeys(str(item).strip() for item in mods if str(item).strip()))
    for mod in mods:
        if not _MOD_NAME_RE.fullmatch(mod):
            raise ValueError(f"Nom de mod invalide dans le profil : {mod}")
    if mod_name and mod_name not in mods:
        mods.append(mod_name)
    params = str(profile.get("startparameters") or "")

    common_path = common_cfg_path(cfg)
    old_server = read_serverdz(cfg)
    old_common = _read_common(cfg)
    old_mods = get_mods(cfg)
    new_server = set_value(old_server, "template", template, quoted=True)
    new_common = _set_mods_content(old_common, mods)
    new_common = _set_startparameters_content(new_common, params)
    try:
        write_serverdz(cfg, new_server)
        connection.write_file(common_path, new_common)
        if get_value(read_serverdz(cfg), "template") != template:
            raise IOError("Le template du profil n'a pas pu être vérifié.")
        if get_mods(cfg) != mods:
            raise IOError("La liste des mods du profil n'a pas pu être vérifiée.")
    except Exception:
        try:
            write_serverdz(cfg, old_server)
        except Exception:
            pass
        try:
            connection.write_file(common_path, old_common)
        except Exception:
            pass
        raise
    return {
        "mod_name": mod_name,
        "template": template,
        "removed_mods": [mod for mod in old_mods if mod not in mods],
    }


def restore_snapshot(cfg, server_files):
    """Restaure les deux fichiers principaux d'un export de profil."""
    server_content = str(server_files.get("serverDZ", ""))
    common_content = str(server_files.get("common.cfg", ""))
    if not server_content or not common_content:
        raise ValueError("Snapshot serveur incomplet.")
    server_path = serverdz_path(cfg)
    common_path = common_cfg_path(cfg)
    old_server = read_serverdz(cfg)
    old_common = _read_common(cfg)
    try:
        write_serverdz(cfg, server_content)
        connection.write_file(common_path, common_content)
        if read_serverdz(cfg) != server_content or _read_common(cfg) != common_content:
            raise IOError("Le snapshot restauré n'a pas pu être vérifié.")
    except Exception:
        try:
            write_serverdz(cfg, old_server)
        except Exception:
            pass
        try:
            connection.write_file(common_path, old_common)
        except Exception:
            pass
        raise
    return {"server_path": server_path, "common_path": common_path}


def mpmissions_path(cfg):
    return f"{cfg['lgsm_path']}/serverfiles/mpmissions"


def mission_exists(cfg, template):
    """Vrai si le dossier de mission ``template`` existe sous mpmissions."""
    path = f"{mpmissions_path(cfg)}/{template}"
    checker = getattr(connection, "is_dir", connection.file_exists)
    return checker(path)


def import_mission(cfg, local_dir, name, progress=None):
    """Téléverse un dossier de mission local dans ``mpmissions/<name>``.

    ``name`` est le nom du dossier distant (ex. ``dayzOffline.deerisle``),
    qui doit correspondre au ``template`` posé dans serverDZ.cfg."""
    _unused_mod, name = _validate_map_names(None, name)
    remote = f"{mpmissions_path(cfg)}/{name}"
    connection.upload_dir(local_dir, remote, progress=progress)
    return name


def _validate_map_names(mod_name, template):
    """Valide les noms de mission et de mod avant tout accès distant."""
    template = str(template or "").strip()
    if not _MISSION_NAME_RE.fullmatch(template):
        raise ValueError(
            "Nom de mission invalide : utilise uniquement lettres, chiffres, "
            "points, tirets et underscores."
        )

    if mod_name in (None, ""):
        return None, template

    mod_name = str(mod_name).strip()
    if not _MOD_NAME_RE.fullmatch(mod_name):
        raise ValueError("Nom de mod de carte invalide.")
    return mod_name, template


def set_active_map(cfg, mod_name, template, map_mods=()):
    """Prépare et vérifie le changement de carte côté serveur.

    ``template`` doit être un dossier existant dans ``mpmissions``. Si
    ``mod_name`` est vide, il s'agit d'une carte officielle qui ne nécessite
    pas de mod dédié. Les mods présents dans ``map_mods`` sont retirés de la
    ligne LGSM avant d'ajouter la nouvelle carte, afin de ne pas charger deux
    cartes en même temps.

    La fonction ne redémarre pas le serveur : l'interface déclenche le
    redémarrage LGSM uniquement après cette écriture et sa vérification.
    """
    mod_name, template = _validate_map_names(mod_name, template)
    map_mods = tuple(dict.fromkeys(
        str(m).strip() for m in map_mods if m not in (None, "")
    ))
    for map_mod in map_mods:
        if not _MOD_NAME_RE.fullmatch(map_mod):
            raise ValueError("La liste des mods de cartes contient un nom invalide.")

    if not mission_exists(cfg, template):
        raise IOError(
            f"Mission « {template} » introuvable sous mpmissions.\n"
            f"La carte {mod_name or 'officielle'} ne fournit pas la mission serveur : "
            f"téléverse d'abord le dossier « {template} » dans "
            f"{mpmissions_path(cfg)} avant de définir la carte active."
        )

    common_path = common_cfg_path(cfg)
    old_server = read_serverdz(cfg)
    old_common = _read_common(cfg)
    old_mods = get_mods(cfg)

    new_server = set_value(old_server, "template", template, quoted=True)
    map_mods_set = set(map_mods)
    new_mods = [m for m in old_mods if m not in map_mods_set and m != mod_name]
    if mod_name:
        new_mods.append(mod_name)
    new_common = _set_mods_content(old_common, new_mods)

    try:
        write_serverdz(cfg, new_server)
        connection.write_file(common_path, new_common)

        # Vérification de lecture après écriture : LGSM doit relire exactement
        # le fichier que nous venons de modifier.
        written_server = read_serverdz(cfg)
        if get_value(written_server, "template") != template:
            raise IOError("Le template de mission n'a pas pu être vérifié.")
        if mod_name and mod_name not in get_mods(cfg):
            raise IOError(f"Le mod {mod_name} n'est pas présent dans common.cfg.")
    except Exception:
        # Tant que le serveur n'a pas redémarré, on peut revenir à l'état
        # initial si l'une des deux écritures ou la vérification échoue.
        try:
            write_serverdz(cfg, old_server)
        except Exception:
            pass
        try:
            connection.write_file(common_path, old_common)
        except Exception:
            pass
        raise

    return {
        "mod_name": mod_name,
        "template": template,
        "removed_mods": [m for m in old_mods if m not in new_mods],
    }
