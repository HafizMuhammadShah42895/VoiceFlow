import unittest

from voiceflow_core.text_rules import apply_replacements, expand_snippet, parse_rules


class TextRulesTests(unittest.TestCase):
    def test_parses_valid_rules_and_ignores_comments(self):
        value = "# team rules\nvoice flow => VoiceFlow\ninvalid\napi => API"
        self.assertEqual(parse_rules(value), [("voice flow", "VoiceFlow"), ("api", "API")])

    def test_applies_case_insensitive_whole_phrase_replacements(self):
        result = apply_replacements("Voice flow uses an api, not a tapi.", "voice flow => VoiceFlow\napi => API")
        self.assertEqual(result, "VoiceFlow uses an API, not a tapi.")

    def test_expands_only_an_exact_snippet_trigger(self):
        rules = "my email => hello@example.com\nsign off => Best regards,\nWali"
        self.assertEqual(expand_snippet("My email.", rules), "hello@example.com")
        self.assertEqual(expand_snippet("Use my email here", rules), "Use my email here")


if __name__ == "__main__":
    unittest.main()
