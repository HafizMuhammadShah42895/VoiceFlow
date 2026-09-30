import unittest

from voiceflow_core.version import is_newer_version, parse_version


class VersionTests(unittest.TestCase):
    def test_parse_version(self):
        self.assertEqual(parse_version("v3.1.0"), (3, 1, 0))
        self.assertEqual(parse_version("3.2.0-beta.1"), (3, 2, 0))
        self.assertEqual(parse_version("nightly"), ())

    def test_is_newer_version(self):
        self.assertTrue(is_newer_version("3.1.1", "3.1.0"))
        self.assertTrue(is_newer_version("v3.2", "3.1.9"))
        self.assertFalse(is_newer_version("3.1", "3.1.0"))
        self.assertFalse(is_newer_version("1.0.57", "3.1.0"))
        self.assertFalse(is_newer_version("", "3.1.0"))


if __name__ == "__main__":
    unittest.main()
