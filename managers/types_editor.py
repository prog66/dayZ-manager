"""Lecture / écriture de ``types.xml`` (économie / loot DayZ).

On parse le XML avec ElementTree, on n'expose que les champs numériques
courants dans une table éditable, et on réécrit l'arbre complet : les
``flags``, ``category``, ``usage``, ``value`` non édités sont préservés.
"""

import xml.etree.ElementTree as ET

# Champs numériques exposés dans l'éditeur (ordre = colonnes).
FIELDS = ["nominal", "min", "lifetime", "restock", "quantmin", "quantmax", "cost"]


def parse(text):
    """Renvoie l'élément racine <types>. Lève ET.ParseError si invalide."""
    return ET.fromstring(text)


def iter_types(root):
    return root.findall("type")


def get_field(element, field):
    child = element.find(field)
    if child is not None and child.text is not None:
        return child.text.strip()
    return ""


def set_field(element, field, value):
    """Met à jour (ou crée) un champ. Une valeur vide laisse le champ tel quel."""
    value = (value or "").strip()
    if value == "":
        return
    child = element.find(field)
    if child is None:
        child = ET.SubElement(element, field)
    child.text = value


def serialize(root):
    """Sérialise l'arbre en XML indenté avec déclaration."""
    ET.indent(root, space="    ")
    body = ET.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + body + "\n"
