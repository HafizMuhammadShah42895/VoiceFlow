import unittest

from voiceflow_core.secrets import CredentialStore


class _MemoryKeyring:
    def __init__(self):
        self.values = {}

    def get_password(self, service, account):
        return self.values.get((service, account))

    def set_password(self, service, account, value):
        self.values[(service, account)] = value

    def delete_password(self, service, account):
        del self.values[(service, account)]


class CredentialStoreTests(unittest.TestCase):
    def test_round_trip_and_delete(self):
        store = CredentialStore(_MemoryKeyring())
        self.assertTrue(store.set_api_key("gsk_test"))
        self.assertEqual(store.get_api_key(), "gsk_test")
        self.assertTrue(store.delete_api_key())
        self.assertEqual(store.get_api_key(), "")


if __name__ == "__main__":
    unittest.main()
