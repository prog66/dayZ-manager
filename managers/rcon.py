"""Client RCON BattlEye complet, exécuté côté serveur via SSH.

La RCON BattlEye est presque toujours bindée sur ``127.0.0.1`` côté
serveur (cf. le planificateur, qui parle déjà à ``127.0.0.1``). Plutôt
que d'ouvrir un socket UDP depuis le poste de l'admin — ce qui exigerait
d'exposer le port RCON sur Internet — on dépose un petit script Python
sur le serveur et on l'invoque par SSH, comme le fait ``scheduler``.

Le script déployé gère le protocole BattlEye : login, envoi d'UNE
commande, réassemblage des réponses multi-paquets, puis affichage de la
réponse textuelle sur stdout. Le parsing (joueurs, bans) se fait ici,
côté application.

API publique :
  • run_command(cfg, cmd)            -> texte brut renvoyé par le serveur
  • list_players(cfg)                -> [ {num, name, guid, ping, ip, lobby} ]
  • say_all / say_player             -> diffusion / message privé
  • kick / ban_player                -> modération
  • list_bans / remove_ban / reload_bans
"""

import hashlib
import re
import struct
from shlex import quote

from ssh.connection import connection

RCONCTL_NAME = "dayz_manager_rconctl.py"

# Client RCON BattlEye (UDP) exécuté côté serveur. Login + 1 commande +
# lecture de la réponse (multi-paquets) -> stdout.
RCONCTL_SCRIPT = r'''#!/usr/bin/env python3
"""Client RCON BattlEye : login, envoi d'une commande, lecture de la
reponse (multi-paquets) puis affichage sur stdout. Deploye par DayZ Manager.
Usage: dayz_manager_rconctl.py <commande...>
Env: RCON_IP / RCON_PORT / RCON_PASSWORD
"""
import os, socket, sys, time, zlib


def _packet(payload):
    crc = zlib.crc32(payload) & 0xffffffff
    return b"BE" + crc.to_bytes(4, "little") + payload


def _parse(data):
    """Renvoie (type, payload) ou (None, None) si trame invalide."""
    if len(data) < 8 or data[:2] != b"BE":
        return None, None
    body = data[6:]            # saute 'BE' + CRC(4)
    if not body or body[0] != 0xFF:
        return None, None
    return body[1], body[2:]


def main():
    ip = os.environ.get("RCON_IP", "127.0.0.1")
    port = int(os.environ.get("RCON_PORT", "2310"))
    pwd = os.environ.get("RCON_PASSWORD", "")
    cmd = " ".join(sys.argv[1:]).strip()

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(5)
    try:
        s.connect((ip, port))
        # --- login ---
        s.send(_packet(b"\xff\x00" + pwd.encode()))
        ptype, payload = _parse(s.recv(4096))
        if ptype != 0x00 or not payload or payload[0] != 0x01:
            print("login refuse (mot de passe RCON ?)", file=sys.stderr)
            return 2
        if not cmd:
            return 0
        # --- commande (sequence 0) ---
        s.send(_packet(b"\xff\x01\x00" + cmd.encode()))
        # --- reponse, eventuellement multi-paquets ---
        parts = {}
        total = 1
        deadline = time.time() + 6
        while time.time() < deadline:
            try:
                ptype, payload = _parse(s.recv(4096))
            except socket.timeout:
                break
            if ptype != 0x01 or payload is None:
                continue
            rest = payload[1:]            # saute l'octet de sequence
            if len(rest) >= 3 and rest[0] == 0x00:
                total = rest[1]
                parts[rest[2]] = rest[3:]
            else:
                parts[0] = rest
                total = 1
            if len(parts) >= total:
                break
        out = b"".join(parts[i] for i in sorted(parts))
        sys.stdout.write(out.decode(errors="ignore"))
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        s.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

# Hôtes sur lesquels le script a déjà été déposé pendant cette session.
_deployed = set()


def _script_path(cfg):
    return f"{cfg['lgsm_path'].rstrip('/')}/{RCONCTL_NAME}"


def _ensure_deployed(cfg):
    """Dépose le script RCON côté serveur (une fois par session)."""
    path = _script_path(cfg)
    key = (cfg.get("host"), path)
    if key in _deployed:
        return path
    connection.write_file(path, RCONCTL_SCRIPT)
    connection.execute(f"chmod 700 {quote(path)}")
    _deployed.add(key)
    return path


def enable_on_server(cfg):
    """Écrit la config BattlEye RCON (``beserver_x64.cfg``) côté serveur.

    - Auto-détecte le dossier BattlEye (réutilise celui d'un ``beserver*``
      existant, sinon un dossier ``battleye`` sous serverfiles, sinon le
      crée).
    - Pose ``RConPassword`` / ``RConPort`` / ``RestrictRCon 0``.
    - Supprime les fichiers ``beserver_x64_active_*.cfg`` aléatoires qui,
      sinon, font ignorer notre config.

    Renvoie le chemin du fichier écrit. Un redémarrage du serveur est requis
    pour que BattlEye relise la config.
    """
    password = str(cfg.get("rcon_password", "")).strip()
    if not password:
        raise RuntimeError("Renseigne d'abord un mot de passe RCON.")
    port = int(cfg.get("rcon_port", 2310) or 2310)
    sf = f"{cfg['lgsm_path'].rstrip('/')}/serverfiles"

    script = (
        f"SF={quote(sf)}\n"
        # 1) dossier BattlEye : priorité à un beserver existant, puis un
        #    dossier 'battleye', sinon défaut sous serverfiles.
        "BE=$(find \"$SF\" -maxdepth 3 -iname 'beserver_x64*.cfg' 2>/dev/null "
        "| head -n1 | xargs -r dirname)\n"
        "[ -z \"$BE\" ] && BE=$(find \"$SF\" -maxdepth 3 -type d -iname 'battleye' "
        "2>/dev/null | head -n1)\n"
        "[ -z \"$BE\" ] && BE=\"$SF/battleye\"\n"
        "mkdir -p \"$BE\" || exit 1\n"
        "CFG=\"$BE/beserver_x64.cfg\"\n"
        f"printf 'RConPassword %s\\nRConPort %s\\nRestrictRCon 0\\n' "
        f"{quote(password)} {port} > \"$CFG\" || exit 1\n"
        "chmod 600 \"$CFG\" 2>/dev/null || true\n"
        # 2) neutralise les fichiers 'active' aléatoires.
        "find \"$BE\" -iname 'beserver_x64_active_*.cfg' -delete 2>/dev/null || true\n"
        "echo \"RCONCFG:$CFG\"\n"
    )
    code, out, err = connection.execute(script, timeout=30)
    if code != 0:
        raise RuntimeError(err.strip() or out.strip() or "Échec de l'écriture de la config RCON.")
    path = ""
    for line in out.splitlines():
        if line.startswith("RCONCFG:"):
            path = line.split(":", 1)[1].strip()
    return path or "beserver_x64.cfg"


def run_command(cfg, rcon_command):
    """Exécute une commande RCON brute et renvoie la réponse texte.

    ``rcon_command`` est inséré tel quel dans la ligne shell : les
    fonctions de haut niveau de ce module se chargent du ``quote`` des
    arguments libres (messages, raisons…).
    """
    if not cfg.get("rcon_enabled"):
        raise RuntimeError("RCON désactivée — active-la dans Planification.")
    if not cfg.get("rcon_password"):
        raise RuntimeError("Mot de passe RCON manquant (Planification).")

    path = _ensure_deployed(cfg)
    port = int(cfg.get("rcon_port", 2310) or 2310)
    env = (
        f"RCON_IP=127.0.0.1 RCON_PORT={port} "
        f"RCON_PASSWORD={quote(str(cfg.get('rcon_password', '')))}"
    )
    full = f"{env} python3 {quote(path)} {rcon_command}"
    code, out, err = connection.execute(full, timeout=20)
    if code != 0:
        raise RuntimeError(err.strip() or out.strip() or "Échec de la commande RCON.")
    return out


# --------------------------------------------------------------------- #
# Joueurs
# --------------------------------------------------------------------- #
# 0   123.45.67.89:2304    50    abc...(OK)  PlayerName
_PLAYER_RE = re.compile(
    r"^\s*(\d+)\s+([0-9.]+):\d+\s+(\d+)\s+([0-9a-fA-F]+|-)\(([^)]*)\)\s+(.*?)\s*$"
)


def parse_players(text):
    players = []
    for line in text.splitlines():
        m = _PLAYER_RE.match(line)
        if not m:
            continue
        num, ip, ping, guid, _status, name = m.groups()
        lobby = name.endswith("(Lobby)")
        if lobby:
            name = name[: -len("(Lobby)")].strip()
        players.append({
            "num": num,
            "ip": ip,
            "ping": ping,
            "guid": guid,
            "name": name,
            "lobby": lobby,
        })
    return players


def list_players(cfg):
    return parse_players(run_command(cfg, "players"))


def say_all(cfg, message):
    return run_command(cfg, f"say -1 {quote(message)}")


def say_player(cfg, num, message):
    return run_command(cfg, f"say {int(num)} {quote(message)}")


def kick(cfg, num, reason=""):
    reason = (reason or "").strip()
    arg = f" {quote(reason)}" if reason else ""
    return run_command(cfg, f"kick {int(num)}{arg}")


def ban_player(cfg, num, minutes=0, reason=""):
    """Bannit le joueur ``num`` pour ``minutes`` (0 = permanent)."""
    reason = (reason or "").strip() or "Banni"
    return run_command(cfg, f"ban {int(num)} {int(minutes)} {quote(reason)}")


# --------------------------------------------------------------------- #
# Bans
# --------------------------------------------------------------------- #
# 0  1234abcd...  perm  Raison        (GUID)
# 1  123.45.67.89  -1   Raison        (IP)
_BAN_RE = re.compile(
    r"^\s*(\d+)\s+([0-9a-fA-F]{6,}|[0-9.]+)\s+(perm|-?\d+)\s*(.*?)\s*$"
)


def parse_bans(text):
    bans = []
    for line in text.splitlines():
        m = _BAN_RE.match(line)
        if not m:
            continue
        ban_id, target, remaining, reason = m.groups()
        kind = "IP" if "." in target and target.replace(".", "").isdigit() else "GUID"
        bans.append({
            "id": ban_id,
            "target": target,
            "remaining": "permanent" if remaining in ("perm", "-1") else remaining,
            "reason": reason,
            "kind": kind,
        })
    return bans


def list_bans(cfg):
    return parse_bans(run_command(cfg, "bans"))


def remove_ban(cfg, ban_id):
    return run_command(cfg, f"removeBan {int(ban_id)}")


def reload_bans(cfg):
    return run_command(cfg, "loadBans")


# --------------------------------------------------------------------- #
# Bans hors-ligne (par GUID/SteamID/IP) + import / export
# --------------------------------------------------------------------- #
_STEAMID64_RE = re.compile(r"^7656\d{13}$")
_GUID_RE = re.compile(r"^[0-9a-f]{32}$", re.IGNORECASE)


def steamid_to_guid(steamid):
    """SteamID64 -> GUID BattlEye (md5 de 'BE' + steamid64 little-endian)."""
    sid = int(str(steamid).strip())
    return hashlib.md5(b"BE" + struct.pack("<Q", sid)).hexdigest()


def normalize_ban_target(target):
    """Accepte GUID / SteamID64 / IP et renvoie la cible utilisable par BE.

    Un SteamID64 (``7656…``) est converti en GUID BattlEye.
    """
    target = str(target).strip()
    if _STEAMID64_RE.match(target):
        return steamid_to_guid(target)
    return target


def add_ban(cfg, target, minutes=0, reason="Banni"):
    """Ban hors-ligne : ``addBan <GUID|IP> <minutes> <raison>`` (0 = perm)."""
    target = normalize_ban_target(target)
    if not (_GUID_RE.match(target) or "." in target):
        raise RuntimeError(f"Cible de ban invalide : {target}")
    reason = (reason or "").strip() or "Banni"
    return run_command(cfg, f"addBan {quote(target)} {int(minutes)} {quote(reason)}")


def export_bans(cfg):
    """Renvoie la liste brute des bans du serveur (texte), pour sauvegarde."""
    return run_command(cfg, "bans")


def import_bans(cfg, targets, minutes=0, reason="Import"):
    """Banni en lot une liste de cibles (GUID/SteamID/IP), puis recharge.

    Tout est fait en UNE commande SSH (boucle côté serveur) pour éviter une
    rafale d'allers-retours. Renvoie le nombre de cibles traitées.
    """
    if not cfg.get("rcon_password"):
        raise RuntimeError("Mot de passe RCON manquant (Planification).")
    cleaned = []
    for t in targets:
        t = str(t).strip()
        if not t or t.startswith("#"):
            continue
        # On ne garde que le premier jeton (un export peut contenir des colonnes).
        cleaned.append(normalize_ban_target(t.split()[0]))
    if not cleaned:
        return 0

    path = _ensure_deployed(cfg)
    port = int(cfg.get("rcon_port", 2310) or 2310)
    env = (
        f"RCON_IP=127.0.0.1 RCON_PORT={port} "
        f"RCON_PASSWORD={quote(str(cfg.get('rcon_password', '')))}"
    )
    targets_sh = " ".join(quote(t) for t in cleaned)
    reason = (reason or "Import").strip() or "Import"
    script = (
        f"for T in {targets_sh}; do "
        f'{env} python3 {quote(path)} addBan "$T" {int(minutes)} {quote(reason)} '
        ">/dev/null 2>&1; done; "
        f"{env} python3 {quote(path)} loadBans >/dev/null 2>&1; "
        f'echo "IMPORTED:{len(cleaned)}"'
    )
    code, out, err = connection.execute(script, timeout=max(30, len(cleaned) * 2))
    if code != 0:
        raise RuntimeError(err.strip() or out.strip() or "Échec de l'import des bans.")
    return len(cleaned)
