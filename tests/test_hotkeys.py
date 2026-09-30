import unittest
from voiceflow_core.hotkeys import hotkey_signature, normalize_key, preset_for_keys, repair_preset_conflicts


class DummyKey:
    def __init__(self, name=None, char=None):
        self.name = name
        self.char = char


class HotkeyTests(unittest.TestCase):
    def test_normalize_key(self):
        self.assertEqual(normalize_key(DummyKey(name="alt_l")), "alt")
        self.assertEqual(normalize_key(DummyKey(name="shift_r")), "shift")
        self.assertEqual(normalize_key(DummyKey(char="k")), "k")

    def test_hotkey_signature(self):
        sig = hotkey_signature(["Alt_L", "Shift_R"])
        self.assertEqual(sig, frozenset({"alt", "shift"}))

    def test_repair_preset_conflicts(self):
        hotkey = {"alt", "shift"}
        context_hotkey = {"ctrl", "shift"}
        presets = [
            {"id": "p1", "name": "Conflicting", "hotkeys": ["alt", "shift"]},
            {"id": "p2", "name": "Valid", "hotkeys": ["ctrl", "space"]},
        ]
        repair_preset_conflicts(presets, hotkey, context_hotkey)
        # Conflicting preset should be reassigned to a fallback
        p1_sig = frozenset(presets[0]["hotkeys"])
        self.assertNotEqual(p1_sig, frozenset(hotkey))
        self.assertNotEqual(p1_sig, frozenset(context_hotkey))
        self.assertIn(p1_sig, {frozenset(["ctrl", "space"]), frozenset(["alt", "space"]), frozenset(["shift", "space"]), frozenset(["ctrl", "alt"])})

    def test_preset_for_keys_prefers_most_specific_match(self):
        presets = [
            {"name": "Two", "hotkeys": ["ctrl", "space"]},
            {"name": "Broken", "hotkeys": ["ctrl"]},
            "not-a-preset",
        ]
        self.assertEqual(preset_for_keys(presets, {"ctrl", "space"})["name"], "Two")
        self.assertEqual(preset_for_keys(presets, {"ctrl_l", "space"}), None)
        self.assertIsNone(preset_for_keys(presets, {"ctrl"}))


if __name__ == "__main__":
    unittest.main()
