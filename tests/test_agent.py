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

    def test_profile_overrides_main_settings_for_its_app(self):
        from voiceflow_core.app_context import AppContext

        self.agent.update_config({
            "main_dictation_ai": False,
            "writing_style": "natural",
            "writing_profiles": [
                {"name": "Work chat", "apps": ["slack.exe"], "writing_style": "concise",
                 "ai_polish": "on", "instructions": "Keep it short."},
                {"name": "Just type", "apps": ["chrome.exe"], "ai_polish": "off"},
            ],
        })
        slack = AppContext(process_name="slack.exe", category="chat", instruction="built-in chat rule")
        profile = dictation_agent.profile_for_app(self.agent.writing_profiles, slack.process_name)
        self.assertEqual(
            self.agent._writing_settings(profile, slack),
            {"ai_polish": True, "writing_style": "concise", "instruction": "Keep it short."},
        )

        self.agent.main_dictation_ai = True
        chrome = AppContext(process_name="chrome.exe", category="browser", instruction="built-in browser rule")
        profile = dictation_agent.profile_for_app(self.agent.writing_profiles, chrome.process_name)
        self.assertFalse(self.agent._writing_settings(profile, chrome)["ai_polish"])

        # No profile: main settings and the built-in app rule apply.
        notepad = AppContext(process_name="notepad.exe", instruction="")
        self.assertEqual(
            self.agent._writing_settings(None, notepad),
            {"ai_polish": True, "writing_style": "natural", "instruction": ""},
        )
        saved = json.loads(Path(os.environ["VOICEFLOW_CONFIG_FILE"]).read_text(encoding="utf-8"))
        self.assertEqual([p["name"] for p in saved["writing_profiles"]], ["Work chat", "Just type"])

    def test_recording_start_remembers_the_apps_profile(self):
        from voiceflow_core.app_context import AppContext

        self.agent.writing_profiles = [{"name": "Work chat", "apps": ["slack.exe"], "writing_style": "default",
                                        "ai_polish": "default", "instructions": "", "id": "p1"}]
        with mock.patch.object(dictation_agent, "get_foreground_app_context",
                               return_value=AppContext(process_name="slack.exe")), \
                mock.patch.object(self.agent.audio, "start_recording"), \
                mock.patch.object(dictation_agent, "_play_sound"):
            self.agent._start_recording(context=False)
        self.assertEqual(self.agent._active_profile["name"], "Work chat")
        job = self.agent.history.get(self.agent._active_history_id)
        self.assertEqual(job["metadata"]["profile"], "Work chat")

    def test_correction_suggests_and_adds_replacements(self):
        job_id = self.agent.history.create(status="transcribing")
        self.agent.history.complete(job_id, "Deploy with docker compose")
        result = self.agent.correct_history_item(job_id, "Deploy with docker-compose")
        self.assertEqual(result["item"]["final_text"], "Deploy with docker-compose")
        self.assertEqual(result["suggestions"], [{"spoken": "docker compose", "replacement": "docker-compose"}])

        self.assertTrue(self.agent.add_replacement("docker compose", "docker-compose"))
        self.assertFalse(self.agent.add_replacement("Docker Compose", "something else"))
        self.assertEqual(self.agent.text_replacements, "docker compose => docker-compose")
        with self.assertRaises(ValueError):
            self.agent.add_replacement("a => b", "c")
        with self.assertRaises(ValueError):
            self.agent.correct_history_item(job_id, "   ")
        self.assertIsNone(self.agent.correct_history_item("missing", "text"))


if __name__ == "__main__":
    unittest.main()
