"""Redémarrages programmés du serveur DayZ via crontab côté serveur.

Principe :
  • On dépose deux scripts sur le serveur :
      - ``dayz_manager_rcon.py`` : mini-client RCON BattlEye (alertes joueurs).
      - ``dayz_manager_restart.sh`` : envoie les préavis puis redémarre.
  • On installe des lignes ``crontab`` taggées ``# DAYZ-MANAGER`` (idempotent).

Le cron se déclenche ``warn_before`` minutes avant l'heure de redémarrage
voulue ; le script enchaîne les alertes (sleep) puis lance ``./dayzserver
restart``. Tout persiste même quand l'application est fermée.
"""

import json
import re
from shlex import quote

from ssh.connection import connection

TAG = "# DAYZ-MANAGER"
# Tag distinct (et NON préfixé par TAG) pour l'auto-restart : ainsi les deux
# blocs cron cohabitent sans que la (ré)installation de l'un n'efface l'autre.
MONITOR_TAG = "# DAYZMGR-MONITOR"
RESTART_NAME = "dayz_manager_restart.sh"
RCON_NAME = "dayz_manager_rcon.py"
MONITOR_NAME = "dayz_manager_monitor.sh"
MAP_ROTATION_TAG = "# DAYZ-MANAGER-MAP"
MAP_ROTATION_NAME = "dayz_manager_map_rotation.py"

# Client RCON BattlEye minimal (UDP), exécuté côté serveur (python3).
RCON_SCRIPT = r'''#!/usr/bin/env python3
"""Mini-client RCON BattlEye : envoie une commande puis quitte.
Usage: dayz_manager_rcon.py <commande...>   (ex: say -1 "message")
Paramètres via variables d'environnement RCON_IP / RCON_PORT / RCON_PASSWORD.
"""
import os, socket, sys, zlib

def packet(payload):
    crc = zlib.crc32(payload) & 0xffffffff
    return b"BE" + crc.to_bytes(4, "little") + payload

def main():
    ip = os.environ.get("RCON_IP", "127.0.0.1")
    port = int(os.environ.get("RCON_PORT", "2310"))
    pwd = os.environ.get("RCON_PASSWORD", "")
    cmd = " ".join(sys.argv[1:])
    if not cmd:
        return 0
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(5)
    try:
        s.connect((ip, port))
        s.send(packet(b"\xff\x00" + pwd.encode()))
        resp = s.recv(1024)
        if len(resp) < 9 or resp[8] != 0x01:
            print("RCON: login refuse", file=sys.stderr)
            return 1
        s.send(packet(b"\xff\x01\x00" + cmd.encode()))
        try:
            s.recv(2048)
        except socket.timeout:
            pass
    except Exception as exc:
        print(f"RCON: {exc}", file=sys.stderr)
        return 1
    finally:
        s.close()
    return 0

if __name__ == "__main__":
    sys.exit(main())
'''


def _paths(cfg):
    base = cfg["lgsm_path"].rstrip("/")
    return f"{base}/{RESTART_NAME}", f"{base}/{RCON_NAME}"


def parse_times(times_str):
    """'04:00, 16:30' -> [(4,0),(16,30)] (valeurs valides uniquement)."""
    times = []
    for token in re.split(r"[,;]", times_str or ""):
        token = token.strip()
        m = re.match(r"^(\d{1,2}):(\d{2})$", token)
        if not m:
            continue
        hh, mm = int(m.group(1)), int(m.group(2))
        if 0 <= hh < 24 and 0 <= mm < 60:
            times.append((hh, mm))
    return times


def _cron_minute_hour(hh, mm, warn_before):
    total = (hh * 60 + mm - int(warn_before)) % (24 * 60)
    return total % 60, total // 60


def _restart_script(cfg, warn_before, marks, message):
    restart_path, rcon_path = _paths(cfg)
    lgsm_path = cfg["lgsm_path"].rstrip("/")
    rcon_enabled = "1" if cfg.get("rcon_enabled") else "0"
    rcon_port = int(cfg.get("rcon_port", 2310) or 2310)
    rcon_pass = str(cfg.get("rcon_password", ""))

    # Paliers d'alerte valides (minutes restantes), ordre décroissant.
    marks = sorted({int(x) for x in marks if 0 < int(x) <= int(warn_before)}, reverse=True)

    # cron tourne avec un environnement minimal : on fixe HOME (chemins Steam
    # de LGSM) et un PATH complet (tmux/curl/python3…), sinon
    # « ./dayzserver restart » peut échouer silencieusement.
    lines = [
        "#!/bin/bash",
        f"export HOME={quote(lgsm_path)}",
        'export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:'
        '/sbin:/bin:$HOME/.local/bin:$PATH"',
        f"cd {quote(lgsm_path)} || exit 1",
        f"LOG={quote(lgsm_path)}/dayz_manager_restart.log",
        'echo "[$(date "+%F %T")] preavis + restart LGSM (demarrage)" >> "$LOG"',
        "export RCON_IP=127.0.0.1",
        f"export RCON_PORT={rcon_port}",
        f"export RCON_PASSWORD={quote(rcon_pass)}",
        f"RCON_ENABLED={rcon_enabled}",
        f"RCON_SCRIPT={quote(rcon_path)}",
        'warn() { [ "$RCON_ENABLED" = "1" ] && python3 "$RCON_SCRIPT" say -1 "$1" '
        ">/dev/null 2>&1; return 0; }",
        "",
    ]

    prev = int(warn_before)
    for m in marks:
        delay = (prev - m) * 60
        if delay > 0:
            lines.append(f"sleep {delay}")
        if "{m}" in message:
            msg = message.replace("{m}", str(m))
        else:
            msg = f"{message} ({m} min)"
        lines.append(f"warn {quote(msg)}")
        prev = m

    if prev > 0:
        lines.append(f"sleep {prev * 60}")
    lines.append('warn "Redemarrage du serveur en cours..."')
    lines.append('./dayzserver restart >> "$LOG" 2>&1')
    lines.append('echo "[$(date "+%F %T")] restart LGSM termine" >> "$LOG"')
    lines.append("")
    return "\n".join(lines)


def _valid_timezone(value):
    value = str(value or "").strip()
    if value and not re.fullmatch(r"[A-Za-z0-9._+-]+(?:/[A-Za-z0-9._+-]+)+", value):
        raise ValueError("Fuseau horaire invalide.")
    return value


def apply(cfg, times_str, warn_before, marks, message, timezone=""):
    """Déploie les scripts et (ré)installe le crontab. Renvoie un résumé."""
    times = parse_times(times_str)
    if not times:
        raise ValueError("Aucune heure de redémarrage valide (format HH:MM).")

    restart_path, rcon_path = _paths(cfg)
    warn_before = int(warn_before)
    timezone = _valid_timezone(timezone)

    # 1) Dépose les scripts.
    connection.write_file(restart_path, _restart_script(cfg, warn_before, marks, message))
    connection.write_file(rcon_path, RCON_SCRIPT)

    # 2) Construit les lignes cron.
    cron_lines = []
    for hh, mm in times:
        cmin, chour = _cron_minute_hour(hh, mm, warn_before)
        cron_lines.append(
            f"{cmin} {chour} * * * /bin/bash {quote(restart_path)} "
            f">/dev/null 2>&1 {TAG}"
        )

    # 3) Fusionne avec le crontab existant (en retirant notre ancien bloc).
    _, existing, _ = connection.execute("crontab -l 2>/dev/null")
    kept = [
        ln for ln in existing.splitlines()
        if TAG not in ln and not ln.startswith("CRON_TZ=") and ln.strip()
    ]
    tz_line = [f"CRON_TZ={timezone}"] if timezone else []
    new_crontab = "\n".join(kept + tz_line + cron_lines).strip() + "\n"

    tmp = f"{cfg['lgsm_path'].rstrip('/')}/.dayz_manager_cron"
    connection.write_file(tmp, new_crontab)
    code, out, err = connection.execute(
        f"chmod 700 {quote(restart_path)} {quote(rcon_path)} && "
        f"crontab {quote(tmp)} && rm -f {quote(tmp)} && echo SCHEDULED"
    )
    if code != 0:
        raise RuntimeError(err or out or "Échec de l'installation du crontab.")

    heures = ", ".join(f"{h:02d}:{m:02d}" for h, m in times)
    suffix = f" · fuseau {timezone}" if timezone else ""
    return f"Planification active : {heures} (préavis {warn_before} min){suffix}."


def disable_command():
    """Commande shell retirant notre bloc du crontab."""
    return (
        f"( crontab -l 2>/dev/null | grep -v {quote(TAG)} | "
        "grep -v '^CRON_TZ=' ) | crontab - "
        f"2>/dev/null; echo CLEARED"
    )


def _rotation_script(cfg, profiles):
    """Génère le script autonome appelé par cron pour une rotation."""
    script = r'''#!/usr/bin/env python3
import json
import pathlib
import re
import subprocess
import sys

LGSM_PATH = __LGSM_PATH__
PROFILES = __PROFILES__


def replace_line(text, key, value, semicolon):
    line = f'{key} = "{value}"' + (";" if semicolon else "")
    pattern = re.compile(r"^\s*" + re.escape(key) + r"\s*=.*$", re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(line, text, count=1)
    return text.rstrip("\n") + "\n" + line + "\n"


def main():
    try:
        profile = PROFILES[int(sys.argv[1])]
    except (IndexError, ValueError, TypeError):
        return 2
    root = pathlib.Path(LGSM_PATH)
    server = root / "serverfiles/cfg/dayzserver.server.cfg"
    common = root / "lgsm/config-lgsm/dayzserver/common.cfg"
    if not server.is_file() or not common.is_file():
        return 3
    server_text = replace_line(server.read_text(encoding="utf-8"),
                               "template", profile["template"], True)
    mods = "\\;".join(profile.get("mods", []))
    common_text = replace_line(common.read_text(encoding="utf-8"),
                               "mods", mods, False)
    common_text = replace_line(common_text, "startparameters",
                               profile.get("startparameters", ""), False)
    server.write_text(server_text, encoding="utf-8")
    common.write_text(common_text, encoding="utf-8")
    return subprocess.run(["./dayzserver", "restart"], cwd=root).returncode


if __name__ == "__main__":
    raise SystemExit(main())
'''
    return script.replace(
        "__LGSM_PATH__", json.dumps(cfg["lgsm_path"])
    ).replace("__PROFILES__", json.dumps(profiles, ensure_ascii=False))


def apply_map_rotation(cfg, profiles, times_str, timezone=""):
    """Déploie une rotation carte persistante côté serveur via cron."""
    times = parse_times(times_str)
    if not times:
        raise ValueError("Aucune heure de rotation valide (format HH:MM).")
    timezone = _valid_timezone(timezone)
    if len(times) != len(profiles):
        raise ValueError("Il faut exactement un profil par heure de rotation.")
    clean_profiles = []
    for profile in profiles:
        if not isinstance(profile, dict) or not profile.get("template"):
            raise ValueError("Profil de rotation incomplet.")
        template = str(profile["template"]).strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", template):
            raise ValueError("Template invalide dans la rotation.")
        mods = [str(mod).strip() for mod in profile.get("mods", [])]
        if any(not re.fullmatch(r"@[A-Za-z0-9][A-Za-z0-9_.-]*", mod) for mod in mods):
            raise ValueError("Mod invalide dans la rotation.")
        mission_path = (
            f"{cfg['lgsm_path'].rstrip('/')}/serverfiles/mpmissions/{template}"
        )
        if not connection.is_dir(mission_path):
            raise IOError(f"Mission absente du serveur : {template}")
        clean_profiles.append({
            "template": template,
            "mods": list(dict.fromkeys(mods)),
            "startparameters": str(profile.get("startparameters") or ""),
        })

    base = cfg["lgsm_path"].rstrip("/")
    script_path = f"{base}/{MAP_ROTATION_NAME}"
    connection.write_file(script_path, _rotation_script(cfg, clean_profiles))
    cron_lines = []
    for index, (hour, minute) in enumerate(times):
        cron_lines.append(
            f"{minute} {hour} * * * /usr/bin/python3 {quote(script_path)} "
            f"{index} >> {quote(base + '/dayz_manager_map_rotation.log')} 2>&1 "
            f"{MAP_ROTATION_TAG}"
        )
    _, existing, _ = connection.execute("crontab -l 2>/dev/null")
    kept = [
        line for line in existing.splitlines()
        if MAP_ROTATION_TAG not in line and not line.startswith("CRON_TZ=")
        and line.strip()
    ]
    tz_line = [f"CRON_TZ={timezone}"] if timezone else []
    new_crontab = "\n".join(kept + tz_line + cron_lines).strip() + "\n"
    tmp = f"{base}/.dayz_manager_map_cron"
    connection.write_file(tmp, new_crontab)
    code, out, err = connection.execute(
        f"chmod 700 {quote(script_path)} && crontab {quote(tmp)} && "
        f"rm -f {quote(tmp)} && echo MAP_ROTATION_ON"
    )
    if code != 0:
        raise RuntimeError(err or out or "Échec de la rotation des cartes.")
    hours = ", ".join(f"{h:02d}:{m:02d}" for h, m in times)
    suffix = f" · fuseau {timezone}" if timezone else ""
    return f"Rotation active : {hours}{suffix}."


def disable_map_rotation_command():
    return (
        f"( crontab -l 2>/dev/null | grep -v {quote(MAP_ROTATION_TAG)} | "
        "grep -v '^CRON_TZ=' ) | crontab - 2>/dev/null; echo MAP_ROTATION_OFF"
    )


def view_map_rotation_command():
    return (
        f"crontab -l 2>/dev/null | grep -E "
        f"{quote('DAYZ-MANAGER-MAP|^CRON_TZ=')} || "
        "echo '(rotation de cartes inactive)'"
    )


# --------------------------------------------------------------------- #
# Auto-restart en cas de crash (LGSM ``monitor`` via cron)
# --------------------------------------------------------------------- #
def _monitor_script(cfg):
    """Script lancé par cron : relance le serveur s'il est tombé.

    Même durcissement que le script de redémarrage (HOME/PATH) car cron
    tourne dans un environnement minimal et LGSM en dépend.
    """
    lgsm_path = cfg["lgsm_path"].rstrip("/")
    return "\n".join([
        "#!/bin/bash",
        f"export HOME={quote(lgsm_path)}",
        'export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:'
        '/sbin:/bin:$HOME/.local/bin:$PATH"',
        f"cd {quote(lgsm_path)} || exit 1",
        # Évite deux relances simultanées si cron se chevauche.
        'LOCK="$HOME/.dayz_manager_monitor.lock"',
        'if [ -f "$LOCK" ] && kill -0 "$(cat "$LOCK")" 2>/dev/null; then exit 0; fi',
        'echo $$ > "$LOCK"; trap \'rm -f "$LOCK"\' EXIT',
        'echo "[$(date "+%F %T")] contrôle santé LGSM" >> "$PWD/dayz_manager_monitor.log"',
        # ``monitor`` ne fait rien si le serveur tourne ; sinon il le relance.
        './dayzserver monitor >> "$PWD/dayz_manager_monitor.log" 2>&1',
        "",
    ])


def apply_monitor(cfg, every_minutes=5):
    """Installe le cron d'auto-restart (``./dayzserver monitor``)."""
    every = max(1, min(60, int(every_minutes)))
    base = cfg["lgsm_path"].rstrip("/")
    monitor_path = f"{base}/{MONITOR_NAME}"

    connection.write_file(monitor_path, _monitor_script(cfg))

    line = (
        f"*/{every} * * * * /bin/bash {quote(monitor_path)} "
        f">/dev/null 2>&1 {MONITOR_TAG}"
    )
    _, existing, _ = connection.execute("crontab -l 2>/dev/null")
    kept = [ln for ln in existing.splitlines()
            if MONITOR_TAG not in ln and ln.strip()]
    new_crontab = "\n".join(kept + [line]).strip() + "\n"

    tmp = f"{base}/.dayz_manager_cron_mon"
    connection.write_file(tmp, new_crontab)
    code, out, err = connection.execute(
        f"chmod 700 {quote(monitor_path)} && crontab {quote(tmp)} && "
        f"rm -f {quote(tmp)} && echo MONITOR_ON"
    )
    if code != 0:
        raise RuntimeError(err or out or "Échec de l'installation de l'auto-restart.")
    return f"Auto-restart actif : vérification toutes les {every} min."


def disable_monitor_command():
    """Commande shell retirant le bloc auto-restart du crontab."""
    return (
        f"( crontab -l 2>/dev/null | grep -v {quote(MONITOR_TAG)} ) | crontab - "
        f"2>/dev/null; echo MONITOR_OFF"
    )


def monitor_view_command():
    """Affiche la ligne cron d'auto-restart si présente."""
    return (
        f"crontab -l 2>/dev/null | grep {quote(MONITOR_TAG)} || "
        f"echo '(auto-restart inactif)'"
    )


def view_command():
    """Commande shell affichant nos lignes cron (redémarrages + auto-restart)."""
    return (
        f"crontab -l 2>/dev/null | grep -E {quote('^CRON_TZ=|DAYZ-MANAGER|DAYZMGR-MONITOR')} || "
        f"echo '(aucune planification active)'"
    )
