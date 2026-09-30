import importlib.util
import io
import sys
import types
import unittest
from pathlib import Path


class _FakeAgent:
    def __init__(self):
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

    def update_config(self, data):
        if not isinstance(data, dict) or not data:
            raise ValueError("Expected a JSON object with the settings to change")
        self.last_config = data

    def get_analytics(self):
        return {"total_words": 2, "sessions": 1}

    def list_open_apps(self):
        return [{"process_name": "slack.exe", "window_title": "Slack"}]

    def correct_history_item(self, job_id, text):
        if not isinstance(text, str) or not text.strip():
            raise ValueError("The corrected text cannot be empty")
        item = self.get_history_item(job_id)
        if not item:
            return None
        item["final_text"] = text
        return {"item": item, "suggestions": [{"spoken": "hello", "replacement": "Hello!"}]}

    def add_replacement(self, spoken, replacement):
        self.text_replacements = f"{spoken} => {replacement}"
        return True

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
        self.base_url = "http://127.0.0.1:5000"
        self.headers = {"X-VoiceFlow-Token": self.module.API_TOKEN}

    def request(self, method, path, **kwargs):
        headers = {**self.headers, **kwargs.pop("headers", {})}
        base_url = kwargs.pop("base_url", self.base_url)
        return self.client.open(path, method=method, headers=headers, base_url=base_url, **kwargs)

    def get(self, path, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path, **kwargs):
        return self.request("POST", path, **kwargs)

    def delete(self, path, **kwargs):
        return self.request("DELETE", path, **kwargs)

    def test_api_rejects_requests_without_token(self):
        response = self.client.post("/api/history/latest/paste", base_url=self.base_url)
        self.assertEqual(response.status_code, 403)
        wrong = self.post("/api/history/latest/paste", headers={"X-VoiceFlow-Token": "guess"})
        self.assertEqual(wrong.status_code, 403)

    def test_rejects_dns_rebinding_host(self):
        response = self.get("/api/history", base_url="http://attacker.example:5000")
        self.assertEqual(response.status_code, 403)
        page = self.client.get("/", base_url="http://attacker.example:5000")
        self.assertEqual(page.status_code, 403)

    def test_dashboard_embeds_token(self):
        page = self.client.get("/", base_url=self.base_url)
        self.assertEqual(page.status_code, 200)
        self.assertIn(self.module.API_TOKEN, page.get_data(as_text=True))

    def test_config_rejects_empty_body(self):
        response = self.post("/api/config", data="", content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["ok"])

    def test_open_apps_endpoint(self):
        data = self.get("/api/apps").get_json()
        self.assertEqual(data["apps"][0]["process_name"], "slack.exe")

    def test_correct_history_and_add_replacement(self):
        response = self.post("/api/history/item-1/correct", json={"text": "Hello!"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["item"]["final_text"], "Hello!")
        self.assertEqual(response.get_json()["suggestions"][0]["spoken"], "hello")
        self.assertEqual(self.post("/api/history/item-1/correct", json={"text": " "}).status_code, 400)
        self.assertEqual(self.post("/api/history/missing/correct", json={"text": "x"}).status_code, 404)

        added = self.post("/api/replacements", json={"spoken": "hello", "replacement": "Hello!"}).get_json()
        self.assertTrue(added["added"])
        self.assertEqual(added["text_replacements"], "hello => Hello!")

    def test_show_window_endpoint(self):
        shown = []
        self.module.app.config["SHOW_WINDOW"] = lambda: shown.append(True)
        try:
            self.assertEqual(self.post("/api/show").status_code, 200)
            self.assertEqual(shown, [True])
            self.assertEqual(self.client.post("/api/show", base_url=self.base_url).status_code, 403)
        finally:
            self.module.app.config.pop("SHOW_WINDOW", None)

    def test_analytics_endpoint(self):
        self.assertEqual(self.get("/api/analytics").get_json(), {"total_words": 2, "sessions": 1})

    def test_history_contract(self):
        response = self.get("/api/history")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["items"][0]["id"], "item-1")

        copy_response = self.post("/api/history/item-1/copy")
        self.assertEqual(copy_response.status_code, 200)
        self.assertTrue(copy_response.get_json()["ok"])

        delete_response = self.delete("/api/history/item-1")
        self.assertEqual(delete_response.status_code, 200)
        self.assertEqual(self.get("/api/history").get_json()["items"], [])

    def test_latest_route_is_not_treated_as_an_item_id(self):
        response = self.post("/api/history/latest/copy")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])

    def test_clear_history(self):
        response = self.delete("/api/history")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["deleted"], 1)

    def test_upload_uses_generated_temp_filename(self):
        response = self.post(
            "/api/transcribe_file",
            data={"file": (io.BytesIO(b"not-real-audio"), "../../outside.wav")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["text"], "Safe transcript")
        self.assertTrue(Path(self.module.agent.last_file_path).name.startswith("voiceflow-upload-"))
        self.assertFalse(Path(self.module.agent.last_file_path).exists())

    def test_check_update_endpoint(self):
        response = self.get("/api/check_update")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("update_available", data)
        self.assertIn("current_version", data)


if __name__ == "__main__":
    unittest.main()
