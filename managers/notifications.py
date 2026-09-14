"""Notifications Discord et e-mail sans dépendance externe."""

import json
import smtplib
import ssl
import urllib.request
from email.message import EmailMessage


def send_discord(webhook, message, timeout=10):
    webhook = str(webhook or "").strip()
    if not webhook:
        return "Discord non configuré"
    request = urllib.request.Request(
        webhook,
        data=json.dumps({"content": str(message)[:1900]}).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "DayZManager"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status not in (200, 204):
            raise RuntimeError(f"Discord a répondu HTTP {response.status}")
    return "Discord OK"


def send_email(cfg, subject, message, timeout=15):
    host = str(cfg.get("notification_email_host") or "").strip()
    recipient = str(cfg.get("notification_email_to") or "").strip()
    if not host or not recipient:
        return "E-mail non configuré"
    port = int(cfg.get("notification_email_port", 587) or 587)
    sender = str(cfg.get("notification_email_from") or recipient).strip()
    username = str(cfg.get("notification_email_user") or "").strip()
    password = str(cfg.get("notification_email_password") or "")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content(message)
    with smtplib.SMTP(host, port, timeout=timeout) as server:
        server.starttls(context=ssl.create_default_context())
        if username:
            server.login(username, password)
        server.send_message(msg)
    return "E-mail OK"


def send(cfg, subject, message):
    """Envoie vers les canaux activés et renvoie un résumé lisible."""
    results = []
    if cfg.get("discord_webhook"):
        results.append(send_discord(cfg["discord_webhook"], message))
    if cfg.get("notification_email_enabled"):
        results.append(send_email(cfg, subject, message))
    return ", ".join(results) if results else "Aucune notification configurée"
