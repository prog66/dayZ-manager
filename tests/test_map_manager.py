import tempfile
import unittest
from pathlib import Path

from managers import map_manager


class MapManagerTests(unittest.TestCase):
    def test_custom_mission_is_discovered(self):
        entries = map_manager.discover_maps(
            ["@OtherMod"],
            ["dayzOffline.chernarusplus", "dayzOffline.customworld"],
        )
        self.assertIn(
            map_manager.MapOption(
                "Mission personnalisée : dayzOffline.customworld",
                None,
                "dayzOffline.customworld",
                True,
            ),
            entries,
        )

    def test_template_guess_is_stable(self):
        self.assertEqual(
            "dayzOffline.mycustommap",
            map_manager.guess_template("@MyCustomMap"),
        )

    def test_unknown_mod_is_linked_to_matching_mission(self):
        entries = map_manager.discover_maps(
            ["@MyCustomMap"], ["dayzOffline.mycustommap"]
        )
        self.assertEqual(
            "dayzOffline.mycustommap",
            next(entry for entry in entries if entry.mod_name == "@MyCustomMap").template,
        )

    def test_alteria_download_root_resolves_to_dayz_template(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "DayZ-Alteria-Missions-main"
            mission = root / "empty.alteria"
            mission.mkdir(parents=True)
            (mission / "init.c").write_text("void main() {}", encoding="utf-8")

            source, template = map_manager.prepare_mission_source(root)

        self.assertEqual(str(mission.resolve()), source)
        self.assertEqual("dayzOffline.alteria", template)


if __name__ == "__main__":
    unittest.main()
