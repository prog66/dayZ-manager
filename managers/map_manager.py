"""Catalogue et découverte des cartes DayZ.

Ce module ne parle ni à Qt ni au serveur. Il transforme simplement les
mods/missions découverts en options testables et réutilisables par l'UI.
"""

from dataclasses import dataclass
from pathlib import Path


MAP_TEMPLATES = {
    "@DeerIsle": "dayzOffline.deerisle",
    "@NamalskIsland": "dayzOffline.namalsk",
    "@Banov": "dayzOffline.banov",
    "@Rostow": "dayzOffline.rostow",
    "@Alteria": "dayzOffline.alteria",
    "@Chiemsee": "dayzOffline.chiemsee",
    "@TakistanPlus": "dayzOffline.takistan",
    "@Esseker": "dayzOffline.esseker",
    "@Pripyat": "dayzOffline.pripyat",
}

OFFICIAL_MAPS = {
    "Chernarus Plus": "dayzOffline.chernarusplus",
    "Livonia": "dayzOffline.enoch",
    "Sakhal": "dayzOffline.sakhal",
}


@dataclass(frozen=True)
class MapOption:
    label: str
    mod_name: str | None
    template: str
    available: bool = True


def guess_template(mod_name):
    """Propose un template raisonnable pour un mod non catalogué."""
    if not mod_name:
        return "dayzOffline."
    return "dayzOffline." + str(mod_name).lstrip("@").lower()


def prepare_mission_source(local_dir):
    """Résout un dossier téléchargé vers sa vraie mission et son template.

    Certains dépôts contiennent un dossier racine supplémentaire, comme
    ``DayZ-Alteria-Missions-main/empty.alteria``. L'importeur peut recevoir le
    dossier racine et sélectionner automatiquement le seul sous-dossier qui
    ressemble à une mission DayZ.
    """
    path = Path(local_dir).expanduser().resolve()
    if not path.is_dir():
        raise ValueError("Sélectionne un dossier extrait, pas une archive ZIP.")

    def looks_like_mission(candidate):
        return (candidate / "init.c").is_file()

    if not looks_like_mission(path):
        candidates = [
            child for child in path.iterdir()
            if child.is_dir() and looks_like_mission(child)
        ]
        if len(candidates) == 1:
            path = candidates[0]
        elif not candidates:
            raise ValueError(
                "Le dossier sélectionné ne contient pas de mission DayZ "
                "reconnaissable (init.c manquant)."
            )
        else:
            raise ValueError(
                "Plusieurs missions sont présentes : sélectionne directement "
                "le dossier de mission voulu."
            )

    folder_name = path.name
    normalized_name = folder_name.casefold()
    if normalized_name == "empty.alteria" or "alteria" in path.parent.name.casefold():
        template = "dayzOffline.alteria"
    else:
        template = folder_name
    return str(path), template


def discover_maps(installed_mods, missions):
    """Construit le catalogue visible depuis les mods et dossiers distants.

    Les dossiers de mission non catalogués sont ajoutés comme missions
    personnalisées. Cela permet de détecter une carte custom même lorsque le
    nom du mod Workshop n'est pas connu par l'application.
    """
    installed = sorted({str(x).strip() for x in installed_mods if str(x).strip()})
    mission_set = {str(x).strip() for x in missions if str(x).strip()}
    entries = []
    represented_templates = set()

    for label, template in OFFICIAL_MAPS.items():
        if template in mission_set:
            entries.append(MapOption(label, None, template, True))
            represented_templates.add(template)

    for mod_name in installed:
        template = MAP_TEMPLATES.get(mod_name)
        if template:
            entries.append(MapOption(mod_name, mod_name, template, template in mission_set))
            represented_templates.add(template)
        else:
            # Le mod est bien détecté ; son association avec le template
            # est souvent déductible du nom de mission.
            guessed = guess_template(mod_name)
            matched = next(
                (mission for mission in mission_set
                 if mission.lower() == guessed.lower()),
                "",
            )
            entries.append(MapOption(mod_name, mod_name, matched, True))
            if matched:
                represented_templates.add(matched)

    for template in sorted(mission_set, key=str.lower):
        if template not in represented_templates:
            entries.append(MapOption(
                f"Mission personnalisée : {template}", None, template, True
            ))
    return entries


def map_mod_names():
    """Retourne les noms catalogués comme mods de carte."""
    return tuple(MAP_TEMPLATES)
