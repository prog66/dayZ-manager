"""Catalogue et découverte des cartes DayZ.

Ce module ne parle ni à Qt ni au serveur. Il transforme simplement les
mods/missions découverts en options testables et réutilisables par l'UI.
"""

from dataclasses import dataclass


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
