import sys
import unittest

from voiceflow_core.profiles import normalize_app_name, parse_profiles, profile_for_app


class WritingProfileTests(unittest.TestCase):
    def test_normalizes_app_names(self):
        expected = "slack.exe" if sys.platform == "win32" else "slack"
        self.assertEqual(normalize_app_name("  Slack "), expected)
        self.assertEqual(normalize_app_name(r"C:\Program Files\Slack\slack.exe"), "slack.exe")

    def test_parses_and_finds_profile_for_app(self):
        profiles = parse_profiles([
            {"name": "Work chat", "apps": ["slack.exe", "Teams.exe"], "writing_style": "concise", "ai_polish": "on"},
            {"name": "Just type", "apps": ["chrome.exe"], "ai_polish": "off", "instructions": "  keep it literal "},
        ])
        self.assertEqual(profiles[0]["apps"], ["slack.exe", "teams.exe"])
        self.assertTrue(profiles[0]["id"])
        self.assertEqual(profiles[1]["writing_style"], "default")
        self.assertEqual(profiles[1]["instructions"], "keep it literal")
        self.assertEqual(profile_for_app(profiles, "TEAMS.EXE")["name"], "Work chat")
        self.assertIsNone(profile_for_app(profiles, "notepad.exe"))
        self.assertIsNone(profile_for_app(profiles, ""))

    def test_rejects_invalid_profiles(self):
        with self.assertRaises(ValueError):
            parse_profiles([{"name": "A", "apps": ["slack.exe"]}, {"name": "B", "apps": ["slack.exe"]}])
        with self.assertRaises(ValueError):
            parse_profiles([{"name": "A", "writing_style": "shouty"}])
        with self.assertRaises(ValueError):
            parse_profiles([{"name": "A", "ai_polish": "maybe"}])
        with self.assertRaises(ValueError):
            parse_profiles({"name": "not a list"})


if __name__ == "__main__":
    unittest.main()
