"""Normalisation des sorties texte provenant de SSH et des PTY Linux.

LinuxGSM utilise des séquences ANSI et des retours chariot pour animer sa
sortie. Les flux SSH peuvent aussi contenir des octets issus d'une locale
différente de UTF-8. Ce module fournit un seul point de décodage afin que
l'interface affiche toujours du texte lisible et stable.
"""

import re


# CSI (couleurs, effacement de ligne, gras, etc.), OSC (titre de terminal) et
# les séquences ANSI simples. Le motif est volontairement limité aux
# séquences de contrôle, pas aux caractères Unicode normaux.
_ANSI_ESCAPE_RE = re.compile(
    r"(?:\x1b\][^\x07]*(?:\x07|\x1b\\)|"
    r"\x1b\[[0-?]*[ -/]*[@-~]|"
    r"\x1b[@-_])"
)


def clean_terminal_text(text: str) -> str:
    """Supprime ANSI/contrôles et convertit les retours chariot en lignes."""
    text = _ANSI_ESCAPE_RE.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "".join(
        char for char in text
        if char in "\n\t" or (ord(char) >= 0x20 and char != "\x7f")
    )


def decode_bytes(data: bytes | bytearray | str) -> str:
    """Décode des octets distants sans perdre silencieusement de caractères."""
    if isinstance(data, str):
        text = data
    else:
        raw = bytes(data)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = raw.decode("cp1252")
            except UnicodeDecodeError:
                text = raw.decode("latin-1")
    return clean_terminal_text(text)
