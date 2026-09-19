"""Construction centralisée des commandes shell distantes.

Toutes les valeurs venant de la configuration ou de l'utilisateur passent
par ``shlex.quote`` pour éviter les injections. Plus aucun identifiant
n'est codé en dur : tout vient du ``cfg`` (config.json).
"""

import re
from shlex import quote


def lgsm(cfg):
    """Préfixe ``cd <lgsm_path> &&`` utilisé par toutes les commandes LGSM."""
    return f"cd {quote(cfg['lgsm_path'])} &&"


# --------------------------------------------------------------------- #
# Contrôle serveur
# --------------------------------------------------------------------- #
def server_action(cfg, action):
    """action ∈ start|stop|restart|update|validate|details|monitor"""
    if action not in {"start", "stop", "restart", "update", "validate", "details", "monitor", "console"}:
        raise ValueError("Action serveur inconnue.")
    return f"{lgsm(cfg)} ./dayzserver {action}"


def wait_for_server_state(cfg, online, attempts=12, delay=5):
    """Attend que le processus DayZ atteigne l'état demandé."""
    attempts = max(1, min(60, int(attempts)))
    delay = max(1, min(30, int(delay)))
    expected = "online" if online else "offline"
    return f"""{lgsm(cfg)}
for i in $(seq 1 {attempts}); do
    if pgrep -f '[D]ayZServer' >/dev/null; then state=online; else state=offline; fi
    if [ "$state" = "{expected}" ]; then
        echo "SERVER_STATE=$state"
        exit 0
    fi
    sleep {delay}
done
echo "SERVER_STATE=$state"
exit 1
"""


# --------------------------------------------------------------------- #
# Monitoring : un seul appel SSH renvoie toutes les métriques, une par
# ligne, dans un ordre fixe.
# --------------------------------------------------------------------- #
def server_stats(cfg):
    return f"""{lgsm(cfg)} {{
        if pgrep -f '[D]ayZServer' >/dev/null; then echo "online"; else echo "offline"; fi
        pgrep -fc '[D]ayZServer' || true
        free -m | awk '/Mem:/ {{printf "%d / %d Mo\\n", $3, $2}}'
        top -bn1 | awk -F'id,' '/%Cpu/ {{split($1, a, ","); printf "%.0f%%\\n", 100 - a[length(a)]}}'
        uptime -p 2>/dev/null || echo "-"
        (./dayzserver version 2>/dev/null | grep -i -m1 version || echo "Version inconnue")
        (lsb_release -ds 2>/dev/null || echo "-")
    }}"""


# --------------------------------------------------------------------- #
# Mods
# --------------------------------------------------------------------- #
def list_mods(cfg):
    serverfiles = quote(f"{cfg['lgsm_path']}/serverfiles")
    return f"if [ -d {serverfiles} ]; then ls -1 {serverfiles} | grep '^@' || true; fi"


def remove_mod(cfg, mod_name):
    if not re.fullmatch(r"@[A-Za-z0-9][A-Za-z0-9_.-]*", str(mod_name or "")):
        raise ValueError("Nom de mod invalide.")
    serverfiles = quote(f"{cfg['lgsm_path']}/serverfiles")
    common = quote(f"{cfg['lgsm_path']}/lgsm/config-lgsm/dayzserver/common.cfg")
    target = quote(f"{cfg['lgsm_path']}/serverfiles/{mod_name}")
    return f"""
SF={serverfiles}
COMMON={common}
TARGET={target}
if [ -f "$COMMON" ] && grep -Fq -- {quote(str(mod_name))} "$COMMON"; then
    echo "MOD_ACTIVE: {mod_name}" >&2
    exit 2
fi
case "$TARGET" in
    "$SF"/@*) ;;
    *) echo "Chemin de mod invalide" >&2; exit 2 ;;
esac
[ -d "$TARGET" ] || {{ echo "Mod introuvable" >&2; exit 1; }}
rm -rf -- "$TARGET" && echo REMOVED
"""


def workshop_content_dir(cfg):
    """Dossier de cache SteamCMD des items Workshop téléchargés."""
    app_id = cfg.get("app_id") or "221100"
    return f"{cfg['lgsm_path']}/.local/share/Steam/steamapps/workshop/content/{app_id}"


def list_workshop_items(cfg):
    """Liste les items du cache SteamCMD : ``id<TAB>mtime_epoch<TAB>@Nom``.

    Le ``mtime`` du dossier de l'item reflète la dernière écriture par
    SteamCMD, donc la version actuellement installée. On le compare ensuite
    au ``time_updated`` de l'API Steam pour repérer les mises à jour.
    """
    root = quote(workshop_content_dir(cfg))
    return (
        f'if [ -d {root} ]; then '
        f'for d in {root}/*/; do '
        f'[ -d "$d" ] || continue; '
        f'id=$(basename "$d"); '
        f"""name=$(grep -m1 -iE '^[[:space:]]*name[[:space:]]*=' "$d/meta.cpp" """
        f"""2>/dev/null | cut -d'"' -f2); """
        f'[ -z "$name" ] && name="$id"; '
        f'mtime=$(stat -c %Y "$d" 2>/dev/null || echo 0); '
        f'printf "%s\\t%s\\t@%s\\n" "$id" "$mtime" "$name"; '
        f'done; fi'
    )


# Marqueur de progression émis par le script et lu par ``InstallWorker``.
# Format : ``@@DZM@@<TYPE>|<champs...>`` — voir ssh/install_worker.py.
INSTALL_MARK = "@@DZM@@"


def install_mods(cfg, mod_ids):
    """Script résilient et *streamable* d'installation/màj de mods.

    Conçu pour être lancé via ``InstallWorker`` (canal SSH dédié) afin
    d'avoir un retour temps réel. Points clés de fiabilité :

    - **Pas de ``set -e``** : SteamCMD renvoie souvent un code ≠ 0 même en
      cas de succès. On juge chaque mod sur la *présence du dossier
      téléchargé*, pas sur le code de sortie — un mod en échec n'interrompt
      plus les suivants.
    - **``HOME`` explicite** : garantit que SteamCMD télécharge bien dans le
      cache attendu (``lgsm_path/.local/...``), sinon la vérification échoue.
    - **Nom robuste** : ``meta.cpp`` s'écrit ``name = "X";`` (avec espaces),
      d'où le même motif que ``list_workshop_items``.

    L'ajout à la ligne ``mods=`` reste géré côté Python (cfg_editor).
    """
    lgsm_path = cfg["lgsm_path"]
    steam_user = cfg.get("steam_user") or "anonymous"
    steam_pass = cfg.get("steam_pass") or ""
    app_id = cfg.get("app_id") or "221100"

    login = quote(steam_user)
    if steam_user != "anonymous" and steam_pass:
        login += f" {quote(steam_pass)}"

    qapp = quote(str(app_id))
    serverfiles = f"{lgsm_path}/serverfiles"
    keys_dir = f"{serverfiles}/keys"

    id_list = " ".join(quote(str(m)) for m in mod_ids)
    tries = max(1, int(cfg.get("install_retries", 3) or 3))

    # Vraie boucle ``for`` : ``continue`` y est valide (un script « déroulé »
    # ne pourrait pas sauter proprement un mod en échec). Chaque mod est
    # tenté jusqu'à ``tries`` fois ; entre deux essais on purge le cache de
    # téléchargement SteamCMD, remède connu à l'erreur « caller chunk
    # indicies out of date / Unexpected result 11 » (cache obsolète).
    script = [
        f"export HOME={quote(lgsm_path)}",
        f"SF={quote(serverfiles)}",
        f"KEYS={quote(keys_dir)}",
        f"APPID={qapp}",
        'STEAM_ROOT="$HOME/.local/share/Steam"',
        'WS="$STEAM_ROOT/steamapps/workshop"',
        'WS_ROOT="$WS/content/$APPID"',
        f"TOTAL={len(mod_ids)}",
        f"TRIES={tries}",
        'mkdir -p "$SF" "$KEYS"',
        "OKN=0; FAILN=0; IDX=0",
        f"for MID in {id_list}; do",
        "  IDX=$((IDX+1))",
        f'  printf "{INSTALL_MARK}STEP|%s|%s|%s\\n" "$IDX" "$TOTAL" "$MID"',
        '  echo "──────── [$IDX/$TOTAL] Mod $MID : téléchargement SteamCMD…"',
        '  MOD_PATH="$WS_ROOT/$MID"',
        "  OK_DL=0; TRY=0",
        '  while [ "$TRY" -lt "$TRIES" ]; do',
        "    TRY=$((TRY+1))",
        '    [ "$TRY" -gt 1 ] && echo "  ↻ Nouvelle tentative ($TRY/$TRIES) après purge du cache SteamCMD…"',
        # `2>&1` + `|| true` : on capture tout et on ne s'arrête jamais ici ;
        # le succès se juge sur la présence du dossier, pas sur le code retour.
        f"    steamcmd +login {login} "
        f'+workshop_download_item "$APPID" "$MID" validate +quit 2>&1 || true',
        '    if [ -d "$MOD_PATH" ] && [ -n "$(ls -A "$MOD_PATH" 2>/dev/null)" ]; then',
        "      OK_DL=1; break",
        "    fi",
        # Purge ciblée du cache obsolète avant de réessayer (le contenu déjà
        # téléchargé sous content/ est préservé).
        '    rm -rf "$WS/downloads" "$WS/temp" "$WS/appworkshop_$APPID.acf" 2>/dev/null || true',
        "    sleep 3",
        "  done",
        '  if [ "$OK_DL" != "1" ]; then',
        f'    printf "{INSTALL_MARK}FAIL|%s|%s\\n" "$MID" "telechargement SteamCMD echoue apres $TRIES tentative(s)"',
        "    FAILN=$((FAILN+1)); continue",
        "  fi",
        "  MOD_NAME=$(grep -m1 -iE '^[[:space:]]*name[[:space:]]*=' "
        '"$MOD_PATH/meta.cpp" 2>/dev/null | cut -d\'"\' -f2)',
        # Nettoyage du nom : les espaces / parenthèses dans le dossier @Nom
        # cassent le paramètre -mod= au lancement (LGSM le passe à un shell
        # qui découpe sur les espaces → serveur qui refuse de démarrer). On
        # normalise vers [A-Za-z0-9._+-], tout le reste devient « _ ».
        "  MOD_NAME=$(printf '%s' \"$MOD_NAME\" | "
        "sed -E 's/[^A-Za-z0-9._+-]+/_/g; s/_+/_/g; s/^_+//; s/_+$//')",
        '  [ -z "$MOD_NAME" ] && MOD_NAME="$MID"',
        '  TARGET="$SF/@$MOD_NAME"',
        '  echo "  → installation : @$MOD_NAME"',
        '  rm -rf "$TARGET"',
        '  if cp -r "$MOD_PATH" "$TARGET"; then',
        '    find "$TARGET" -iname "*.bikey" -exec cp -f {} "$KEYS/" \\; '
        "2>/dev/null || true",
        f'    printf "{INSTALL_MARK}OK|%s|@%s\\n" "$MID" "$MOD_NAME"',
        "    OKN=$((OKN+1))",
        "  else",
        f'    printf "{INSTALL_MARK}FAIL|%s|%s\\n" "$MID" "copie vers serverfiles echouee"',
        "    FAILN=$((FAILN+1))",
        "  fi",
        "done",
        f'printf "{INSTALL_MARK}DONE|%s|%s\\n" "$OKN" "$FAILN"',
    ]
    return "\n".join(script)


# --------------------------------------------------------------------- #
# Sauvegardes
# --------------------------------------------------------------------- #
def backup_dir(cfg):
    return f"{cfg['lgsm_path']}/backups-manager"


def create_backup(cfg, label=""):
    lgsm_path = cfg["lgsm_path"]
    bdir = quote(backup_dir(cfg))
    root = quote(lgsm_path)
    label = _safe_backup_label(label)
    prefix = f"dayz-backup-{label}-" if label else "dayz-backup-"
    # On archive depuis la racine LGSM afin d'inclure le vrai fichier actif
    # ``serverfiles/cfg/dayzserver.server.cfg`` et ``common.cfg``.
    # ``-v`` : liste chaque fichier au fil de l'archivage (sortie live via PTY).
    return f"""
mkdir -p {bdir}
STAMP=$(date +%Y%m%d-%H%M%S)
ARCHIVE={bdir}/{prefix}$STAMP.tar.gz
cd {root} || {{ echo "racine LGSM introuvable"; exit 1; }}
FILES=""
[ -d serverfiles/mpmissions ] && FILES="$FILES serverfiles/mpmissions"
[ -f serverfiles/cfg/dayzserver.server.cfg ] && \\
    FILES="$FILES serverfiles/cfg/dayzserver.server.cfg"
[ -f lgsm/config-lgsm/dayzserver/common.cfg ] && \\
    FILES="$FILES lgsm/config-lgsm/dayzserver/common.cfg"
[ -n "$FILES" ] || {{ echo "Aucun fichier DayZ à sauvegarder"; exit 1; }}
echo "Archivage de :$FILES"
tar -czvf "$ARCHIVE" $FILES || exit $?
echo "BACKUP:$ARCHIVE"
"""


def list_backups(cfg):
    bdir = quote(backup_dir(cfg))
    return f"if [ -d {bdir} ]; then ls -1t {bdir} | grep '.tar.gz' || true; fi"


def last_backup(cfg):
    """Renvoie le nom de la dernière sauvegarde, ou une valeur neutre."""
    bdir = quote(backup_dir(cfg))
    return f"ls -1t {bdir}/*.tar.gz 2>/dev/null | head -n 1 | xargs -r basename || true"


def restore_backup(cfg, archive_name):
    archive_name = _safe_archive_name(archive_name)
    bdir = backup_dir(cfg)
    archive = quote(f"{bdir}/{archive_name}")
    root = quote(cfg["lgsm_path"])
    # ``-v`` : liste chaque fichier restauré au fil de l'extraction.
    # Les anciennes archives étaient créées depuis serverfiles ; on garde
    # leur compatibilité en détectant leur préfixe avant extraction.
    return f"""
ROOT={root}
ARCHIVE={archive}
test -f "$ARCHIVE" || exit 1
case "$(tar -tzf "$ARCHIVE" 2>/dev/null | head -n 1)" in
    serverfiles/*|lgsm/*) DEST="$ROOT" ;;
    *) DEST="$ROOT/serverfiles" ;;
esac
python3 - "$ARCHIVE" "$DEST" <<'PY'
import os, pathlib, sys, tarfile
destination = os.path.realpath(sys.argv[2])
with tarfile.open(sys.argv[1], 'r:gz') as archive:
    for entry in archive:
        name = pathlib.PurePosixPath(entry.name)
        if name.is_absolute() or '..' in name.parts or not (entry.isfile() or entry.isdir()):
            raise SystemExit('Archive refusee : chemin ou lien non autorise')
        target = os.path.realpath(os.path.join(destination, *name.parts))
        if os.path.commonpath([destination, target]) != destination:
            raise SystemExit('Archive refusee : destination hors du dossier serveur')
PY
[ $? -eq 0 ] || exit 1
echo "Restauration en cours…"
tar -xzvf "$ARCHIVE" -C "$DEST" && echo RESTORED
"""


def delete_backup(cfg, archive_name):
    archive_name = _safe_archive_name(archive_name)
    archive = quote(f"{backup_dir(cfg)}/{archive_name}")
    return f"rm -f {archive} && echo DELETED"


def _safe_archive_name(archive_name):
    """Autorise uniquement un nom de fichier de sauvegarde, jamais un chemin."""
    name = str(archive_name or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.tar\.gz", name):
        raise ValueError("Nom de sauvegarde invalide.")
    return name


def _safe_backup_label(label):
    label = str(label or "").strip()
    if not label:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,31}", label):
        raise ValueError(
            "Libellé invalide : utilise 1 à 32 caractères alphanumériques, "
            "points, tirets ou underscores."
        )
    return label


def verify_map_loaded(cfg, template):
    """Vérifie le processus DayZ et la présence du template dans les logs récents."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", str(template or "")):
        raise ValueError("Template de mission invalide.")
    root = quote(cfg["lgsm_path"])
    needle = quote(str(template))
    return f"""
ROOT={root}
TEMPLATE={needle}
if pgrep -f '[D]ayZServer' >/dev/null; then
    echo PROCESS=online
else
    echo PROCESS=offline
fi
FOUND=0
for LOG in $(find "$ROOT/serverfiles" -maxdepth 5 -type f \\
    \\( -iname '*.rpt' -o -iname '*.adm' -o -iname '*.log' \\) \\
    -printf '%T@ %p\\n' 2>/dev/null | sort -rn | head -n 8 | cut -d' ' -f2-); do
    if grep -Fqi -- "$TEMPLATE" "$LOG" 2>/dev/null; then
        FOUND=1
        break
    fi
done
if [ "$FOUND" -eq 1 ]; then
    echo MAP_READY
else
    echo MAP_NOT_CONFIRMED
fi
"""


def list_mod_dependencies(cfg):
    """Extrait les ``requiredAddons`` déclarés par les mods installés."""
    root = quote(f"{cfg['lgsm_path']}/serverfiles")
    return f"""
ROOT={root}
for MOD in "$ROOT"/@*/; do
    [ -d "$MOD" ] || continue
    NAME=$(basename "$MOD")
    grep -RhoE 'requiredAddons[[:space:]]*=[[:space:]]*\\{{[^}}]*\\}}' \\
        "$MOD" 2>/dev/null | grep -oE '"[^"]+"' | tr -d '"' | sort -u | \\
        paste -sd, - | sed "s#^#$NAME\\t#"
done
"""


def search_logs(cfg, query="", category="Tous"):
    """Recherche dans les logs avec un filtre thématique optionnel."""
    categories = {
        "Tous": ".",
        "Erreurs": "error|fatal|exception|crash|failed|cannot",
        "Crash": "crash|segmentation|sigsegv|fatal|abort",
        "Mods": "mod|addon|workshop|requiredaddons",
        "Joueurs": "player|kick|ban|connect|disconnect",
    }
    query = str(query or "").strip()
    pattern = query or categories.get(category, categories["Tous"])
    roots = " ".join(quote(path) for path in (
        f"{cfg['lgsm_path']}/log",
        f"{cfg['lgsm_path']}/serverfiles/profiles",
        f"{cfg['lgsm_path']}/serverfiles",
    ))
    return (
        f"find {roots} -maxdepth 5 -type f "
        r"\( -iname '*.rpt' -o -iname '*.adm' -o -iname '*.log' \) "
        f"-exec grep -HinE -- {quote(pattern)} {{}} + 2>/dev/null | tail -n 300"
    )


def server_health(cfg):
    """Diagnostic court : processus, mémoire, disque et indices de crash."""
    root = quote(cfg["lgsm_path"])
    return f"""
ROOT={root}
pgrep -f '[D]ayZServer' >/dev/null && echo SERVER=online || echo SERVER=offline
free -m | awk '/Mem:/ {{printf "MEMORY=%s/%s Mo\\n", $3, $2}}'
df -P "$ROOT" | awk 'NR==2 {{printf "DISK=%s%%\\n", $5}}'
CRASHES=$(find "$ROOT/serverfiles" -maxdepth 5 -type f \\
    \\( -iname '*.rpt' -o -iname '*.log' \\) -exec grep -HiE \\
    'crash|segmentation|sigsegv|fatal exception' {{}} + 2>/dev/null | tail -n 50 | wc -l)
echo CRASH_SIGNS=$CRASHES
"""


# --------------------------------------------------------------------- #
# Logs serveur (.RPT / .ADM / .log)
# --------------------------------------------------------------------- #
def list_logs(cfg):
    """Liste les fichiers de log récents : ``mtime<TAB>taille<TAB>chemin``."""
    lgsm = cfg["lgsm_path"]
    roots = " ".join(quote(p) for p in (
        f"{lgsm}/log",
        f"{lgsm}/serverfiles/profiles",
        f"{lgsm}/serverfiles/config",
        f"{lgsm}/serverfiles",
    ))
    return (
        f"find {roots} -maxdepth 4 -type f "
        r"\( -iname '*.rpt' -o -iname '*.adm' -o -iname '*.log' \) "
        r"-printf '%T@\t%s\t%p\n' 2>/dev/null | sort -rn | head -80"
    )


def tail_log(cfg, path, lines=200):
    return f"tail -n {int(lines)} {quote(path)}"


def follow_log(cfg, path, lines=80):
    """Commande de suivi live, à passer à ConsoleWorker."""
    return f"tail -n {int(lines)} -f {quote(path)}"


# --------------------------------------------------------------------- #
# Économie : localisation des types.xml
# --------------------------------------------------------------------- #
def list_types_files(cfg):
    mpmissions = quote(f"{cfg['lgsm_path']}/serverfiles/mpmissions")
    return f"find {mpmissions} -maxdepth 4 -iname 'types.xml' 2>/dev/null | sort"


# Fichiers d'économie / config DayZ éditables (hors types.xml, déjà géré).
ECONOMY_FILENAMES = (
    "globals.xml",
    "events.xml",
    "cfgspawnabletypes.xml",
    "cfgeconomycore.xml",
    "cfgeventspawns.xml",
    "cfgenvironment.xml",
    "cfggameplay.json",
    "cfgweather.xml",
)


def list_economy_files(cfg):
    """Liste les fichiers d'économie/config DayZ trouvés sous mpmissions."""
    mpmissions = quote(f"{cfg['lgsm_path']}/serverfiles/mpmissions")
    names = " -o ".join(f"-iname {quote(n)}" for n in ECONOMY_FILENAMES)
    return f"find {mpmissions} -maxdepth 5 \\( {names} \\) 2>/dev/null | sort"


# --------------------------------------------------------------------- #
# Mission active (mpmissions)
# --------------------------------------------------------------------- #
def list_missions(cfg):
    """Liste les dossiers de mission disponibles sous mpmissions."""
    mpmissions = quote(f"{cfg['lgsm_path']}/serverfiles/mpmissions")
    return (
        f"if [ -d {mpmissions} ]; then "
        f"find {mpmissions} -maxdepth 1 -mindepth 1 -type d "
        f"-printf '%f\\n' 2>/dev/null | sort; fi"
    )
