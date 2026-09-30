import importlib.util
import io
import sys
import types
import unittest
from pathlib import Path


class _FakeHistory:
    def analytics(self):
        return {"total_words": 2, "sessions": 1}

    def purge_older_than(self, _days):
        return 0


class _FakeAgent:
    def __init__(self):
        self.history = _FakeHistory()
        self.hotkey = {"alt", "shift"}
        self.context_hotkey = {"ctrl", "shift"}
        self.ai_presets = []
        self.items = [{
            "id": "item-1",
            "status": "completed",
            "raw_text": "hello",
            "final_text": "Hello.",
        }]

    def get_config(self):
        return {"status": "idle", "hotkey": ["alt", "shift"]}

    def save_config(self):
        return None

    def get_history(self, limit=100, offset=0, query=""):
        return self.items[offset:offset + limit]

    def get_history_item(self, job_id):
        return next((item for item in self.items if item["id"] == job_id), None)

    def delete_history_item(self, job_id):
        before = len(self.items)
        self.items = [item for item in self.items if item["id"] != job_id]
        return len(self.items) != before

    def clear_history(self):
        deleted = len(self.items)
        self.items = []
        return deleted

    def copy_history_item(self, job_id=None):
        return bool(self.items and (job_id is None or self.get_history_item(job_id)))

    def paste_history_item(self, job_id=None):
        return self.copy_history_item(job_id)

    def retry_history_item(self, _job_id):
        return None

    def transcribe_file(self, filepath):
        self.last_file_path = filepath
        return "Safe transcript"


def _load_app_module():
    fake_agent_module = types.ModuleType("dictation_agent")
    fake_agent_module.DictationAgent = _FakeAgent
    fake_agent_module.safe_clipboard_set = lambda text: isinstance(text, str)
    fake_webview_module = types.ModuleType("webview")
    sys.modules["dictation_agent"] = fake_agent_module
    sys.modules["webview"] = fake_webview_module

    app_path = Path(__file__).resolve().parents[1] / "app.py"
    spec = importlib.util.spec_from_file_location("voiceflow_api_test_app", app_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_app_module()

    def setUp(self):
        self.module.agent.items = [{
            "id": "item-1",
            "status": "completed",
            "raw_text": "hello",
            "final_text": "Hello.",
        }]
        self.client = self.module.app.test_client()

    def test_history_contract(self):
        response = self.client.get("/api/history")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["items"][0]["id"], "item-1")

        copy_response = self.client.post("/api/history/item-1/copy")
        self.assertEqual(copy_response.status_code, 200)
        self.assertTrue(copy_response.get_json()["ok"])

        delete_response = self.client.delete("/api/history/item-1")
        self.assertEqual(delete_response.status_code, 200)
        self.assertEqual(self.client.get("/api/history").get_json()["items"], [])

    def test_latest_route_is_not_treated_as_an_item_id(self):
        response = self.client.post("/api/history/latest/copy")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])

    def test_clear_history(self):
        response = self.client.delete("/api/history")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["deleted"], 1)

    def test_upload_uses_generated_temp_filename(self):
        response = self.client.post(
            "/api/transcribe_file",
            data={"file": (io.BytesIO(b"not-real-audio"), "../../outside.wav")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["text"], "Safe transcript")
        self.assertTrue(Path(self.module.agent.last_file_path).name.startswith("voiceflow-upload-"))
        self.assertFalse(Path(self.module.agent.last_file_path).exists())

    def test_check_update_endpoint(self):
        response = self.client.get("/api/check_update")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("update_available", data)
        self.assertIn("current_version", data)


if __name__ == "__main__":
    unittest.main()
