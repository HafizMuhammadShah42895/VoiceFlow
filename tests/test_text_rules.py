import unittest

from voiceflow_core.text_rules import apply_replacements, expand_snippet, parse_rules, suggest_replacements


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

    def test_suggests_replacements_from_a_correction(self):
        suggestions = suggest_replacements(
            "Run docker compose up with the api key.",
            "Run docker-compose up with the API key.",
        )
        self.assertEqual(suggestions, [
            {"spoken": "docker compose", "replacement": "docker-compose"},
            {"spoken": "api", "replacement": "API"},
        ])

    def test_ignores_trivial_known_and_rewritten_changes(self):
        self.assertEqual(suggest_replacements("hello world", "Hello world."), [])
        self.assertEqual(suggest_replacements("use open ai", "use OpenAI", "open ai => OpenAI"), [])
        self.assertEqual(
            suggest_replacements("the quick brown fox jumps over it", "a completely different sentence entirely"),
            [],
        )


if __name__ == "__main__":
    unittest.main()
