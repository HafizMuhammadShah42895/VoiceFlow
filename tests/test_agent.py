import json
import os
from contextlib import closing
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

_TEMP_DIR = tempfile.TemporaryDirectory()
os.environ["VOICEFLOW_CONFIG_FILE"] = str(Path(_TEMP_DIR.name) / "config.json")
os.environ["VOICEFLOW_ANALYTICS_FILE"] = str(Path(_TEMP_DIR.name) / "analytics.json")
os.environ["VOICEFLOW_DATA_DIR"] = _TEMP_DIR.name

import dictation_agent  # noqa: E402  (must import after the environment is set)
from voiceflow_core.secrets import CredentialStore  # noqa: E402


class _MemoryKeyring:
    def __init__(self):
        self.values = {}

    def get_password(self, service, account):
        return self.values.get((service, account))

    def set_password(self, service, account, value):
        self.values[(service, account)] = value

    def delete_password(self, service, account):
        self.values.pop((service, account), None)


class _Key:
    def __init__(self, name):
        self.name = name
        self.char = None


def tearDownModule():
    _TEMP_DIR.cleanup()


class DictationAgentTests(unittest.TestCase):
    def setUp(self):
        for name in ("VOICEFLOW_CONFIG_FILE", "VOICEFLOW_ANALYTICS_FILE"):
            Path(os.environ[name]).unlink(missing_ok=True)
        self.keyring = _MemoryKeyring()
        patcher = mock.patch.object(dictation_agent, "CredentialStore", lambda: CredentialStore(self.keyring))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.agent = dictation_agent.DictationAgent()

    def press(self, *names):
        for name in names:
            self.agent._on_press(_Key(name))

    def release(self, *names):
        for name in names:
            self.agent._on_release(_Key(name))

    def test_preset_hotkey_triggers_ai_edit(self):
        self.agent.ai_presets = [{"id": "p", "name": "Formal", "hotkeys": ["ctrl", "space"], "prompt": "Be formal"}]
        with mock.patch.object(self.agent, "_start_ai_edit") as start_ai_edit, \
                mock.patch.object(self.agent, "_start_recording") as start_recording:
            self.press("ctrl_l", "space")
            self.press("space")  # auto-repeat must not fire it twice
        start_ai_edit.assert_called_once_with("Be formal")
        start_recording.assert_not_called()

    def test_main_hotkey_starts_dictation_without_touching_clipboard(self):
        with mock.patch.object(self.agent, "_start_recording") as start_recording, \
                mock.patch.object(dictation_agent, "capture_selection") as capture:
            self.press("alt_l", "shift")
        start_recording.assert_called_once_with(context=False)
        capture.assert_not_called()

    def test_autorepeat_does_not_stop_toggle_recording(self):
        self.agent.dictation_trigger_mode = "toggle"
        self.agent.is_recording = True
        with mock.patch.object(self.agent, "_stop_recording") as stop_recording:
            self.agent.keys_pressed = {"alt", "shift"}
            self.press("shift")  # held key repeating
            stop_recording.assert_not_called()
            self.release("alt", "shift")
            self.press("alt", "shift")  # a fresh press stops it
            stop_recording.assert_called_once()

    def test_invalid_settings_are_rejected_without_partial_changes(self):
        with self.assertRaises(ValueError):
            self.agent.update_config({"writing_style": "casual", "silence_timeout_seconds": "soon"})
        self.assertEqual(self.agent.writing_style, "natural")
        with self.assertRaises(ValueError):
            self.agent.update_config({})
        with self.assertRaises(ValueError):
            self.agent.update_config({"key1": "alt", "key2": "shift", "context_key1": "shift", "context_key2": "alt"})

    def test_settings_are_saved_atomically_without_api_key(self):
        self.agent.update_config({"writing_style": "concise", "api_key": "gsk_secret", "silence_timeout_seconds": 1})
        saved = json.loads(Path(os.environ["VOICEFLOW_CONFIG_FILE"]).read_text(encoding="utf-8"))
        self.assertEqual(saved["writing_style"], "concise")
        self.assertEqual(saved["silence_timeout_seconds"], 3.0)
        self.assertNotIn("api_key", saved)
        self.assertNotIn("context_aware_dictation", saved)
        self.assertEqual(self.keyring.get_password("VoiceFlow", "groq-api-key"), "gsk_secret")

    def test_legacy_plaintext_key_moves_to_keyring(self):
        config_path = Path(os.environ["VOICEFLOW_CONFIG_FILE"])
        config_path.write_text(json.dumps({"api_key": "gsk_legacy", "writing_style": "bogus"}), encoding="utf-8")
        agent = dictation_agent.DictationAgent()
        self.assertEqual(agent.api_key, "gsk_legacy")
        self.assertEqual(agent.writing_style, "natural")
        self.assertNotIn("api_key", json.loads(config_path.read_text(encoding="utf-8")))

    def test_analytics_count_each_dictation_once(self):
        self.agent._update_analytics("one two three")
        self.agent._update_analytics("four")
        self.assertEqual(self.agent.get_analytics(), {"total_words": 4, "sessions": 2})

    def test_retention_purge_removes_old_history(self):
        job_id = self.agent.history.create(status="listening")
        old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat(timespec="milliseconds")
        with closing(sqlite3.connect(self.agent.history.database_path)) as connection, connection:
            connection.execute("UPDATE dictations SET created_at = ? WHERE id = ?", (old, job_id))
        self.agent.history_retention_days = 30
        self.agent._purge_history(force=True)
        self.assertIsNone(self.agent.history.get(job_id))


if __name__ == "__main__":
    unittest.main()
