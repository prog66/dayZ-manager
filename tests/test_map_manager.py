import unittest

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


if __name__ == "__main__":
    unittest.main()
