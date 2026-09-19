"""Read-only readiness checks, with actionable results and no credentials."""

from shlex import quote
from managers import cfg_editor
from ssh.connection import connection


def local_checks(cfg):
    return [
        ("Connexion", "OK" if cfg.get("host") and cfg.get("user") else "À configurer",
         "Renseigner l'hôte et l'utilisateur dans Réglages."),
        ("Chemin LGSM", "OK" if str(cfg.get("lgsm_path", "")).startswith("/") else "À corriger",
         "Chemin absolu du dossier contenant dayzserver, par exemple /home/florent."),
        ("RCON", "Prêt" if cfg.get("rcon_enabled") and cfg.get("rcon_password") else "Optionnel",
         "Activer la RCON dans Automatisation pour les joueurs et préavis."),
        ("E-mail", "À vérifier" if cfg.get("notification_email_enabled") else "Désactivé",
         "Utiliser le test de notification dans Réglages après saisie du mot de passe SMTP."),
    ]


def inspect_server(cfg):
    rows = local_checks(cfg)
    root = str(cfg.get("lgsm_path") or "").rstrip("/")
    if not root.startswith("/") or not cfg.get("host") or not cfg.get("user"):
        return rows
    checks = [
        ("LinuxGSM", f"test -x {quote(root + '/dayzserver')}", "Vérifier le chemin LGSM et le droit d'exécution de dayzserver."),
        ("Fichiers DayZ", f"test -d {quote(root + '/serverfiles')}", "Installer le serveur DayZ via LinuxGSM."),
        ("Configuration DayZ", f"test -r {quote(cfg_editor.serverdz_path(cfg))}", "Vérifier le fichier cfg/dayzserver.server.cfg utilisé par LGSM."),
        ("Configuration LGSM", f"test -r {quote(cfg_editor.common_cfg_path(cfg))}", "Configurer common.cfg dans Réglages / identifiant Steam."),
        ("Droits d'import", f"test -w {quote(root + '/serverfiles/mpmissions')}", "Donner au compte SSH l'accès en écriture à mpmissions."),
        ("Python distant", "command -v python3 >/dev/null 2>&1", "Installer Python 3 côté serveur pour les fonctions RCON."),
        ("Planification", "command -v crontab >/dev/null 2>&1", "Installer cron pour les redémarrages et rotations."),
        ("Archives", "command -v tar >/dev/null 2>&1", "Installer tar pour sauvegarder et restaurer."),
    ]
    script = "\n".join(f"if {command}; then echo CHECK_{i}=OK; else echo CHECK_{i}=FAIL; fi" for i, (_, command, _) in enumerate(checks))
    code, out, err = connection.execute(script, timeout=30)
    if code:
        raise RuntimeError(err or "Diagnostic distant interrompu.")
    results = dict(line.split("=", 1) for line in out.splitlines() if line.startswith("CHECK_") and "=" in line)
    for i, (label, _, advice) in enumerate(checks):
        ok = results.get(f"CHECK_{i}") == "OK"
        rows.append((label, "OK" if ok else "À corriger", "Vérifié sur le serveur." if ok else advice))
    return rows
