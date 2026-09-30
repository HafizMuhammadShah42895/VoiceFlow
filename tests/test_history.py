import tempfile
import unittest
from pathlib import Path

from voiceflow_core.history import DictationHistory, DictationStatus


class DictationHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.history = DictationHistory(Path(self.temp_dir.name) / "history.db")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_records_complete_dictation_and_analytics(self):
        job_id = self.history.create(status=DictationStatus.LISTENING, mode="dictation")
        self.history.transition(job_id, DictationStatus.TRANSCRIBING, duration_ms=1250)
        self.history.transition(job_id, DictationStatus.POLISHING, raw_text="hello um world")
        result = self.history.complete(job_id, "Hello world.")

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["raw_text"], "hello um world")
        self.assertEqual(result["final_text"], "Hello world.")
        self.assertEqual(self.history.analytics(), {"total_words": 2, "sessions": 1})

    def test_search_latest_and_delete(self):
        first = self.history.create(mode="file", status=DictationStatus.TRANSCRIBING)
        self.history.complete(first, "Alpha transcript")
        second = self.history.create(mode="dictation", status=DictationStatus.LISTENING)
        self.history.fail(second, "No speech", code="no_speech")

        self.assertEqual(self.history.latest()["id"], first)
        self.assertEqual(len(self.history.list(query="Alpha")), 1)
        self.assertTrue(self.history.delete(first))
        self.assertIsNone(self.history.get(first))

    def test_rejects_invalid_transition(self):
        job_id = self.history.create(status=DictationStatus.LISTENING)
        with self.assertRaises(ValueError):
            self.history.transition(job_id, DictationStatus.COMPLETED)

    def test_recovers_interrupted_job_and_preserves_audio_for_retry(self):
        job_id = self.history.create(status=DictationStatus.LISTENING)
        audio_path = self.history.save_recovery_audio(job_id, b"\x00\x00" * 160, 16000)
        self.history.transition(job_id, DictationStatus.TRANSCRIBING, audio_path=audio_path)

        reopened = DictationHistory(self.history.database_path)
        recovered = reopened.get(job_id)
        self.assertEqual(recovered["status"], "failed")
        self.assertEqual(recovered["error_code"], "interrupted")
        self.assertTrue(Path(recovered["audio_path"]).exists())

    def test_clear_removes_rows_and_recovery_audio(self):
        job_id = self.history.create(status=DictationStatus.LISTENING)
        audio_path = self.history.save_recovery_audio(job_id, b"\x00\x00" * 160, 16000)
        self.history.transition(job_id, DictationStatus.TRANSCRIBING, audio_path=audio_path)

        self.assertEqual(self.history.clear(), 1)
        self.assertEqual(self.history.list(), [])
        self.assertFalse(Path(audio_path).exists())

    def test_update_final_text_keeps_status_and_marks_correction(self):
        job_id = self.history.create(mode="dictation", status=DictationStatus.TRANSCRIBING)
        self.history.complete(job_id, "Run docker compose")
        updated = self.history.update_final_text(job_id, "Run docker-compose")
        self.assertEqual(updated["final_text"], "Run docker-compose")
        self.assertEqual(updated["status"], "completed")
        self.assertIn("corrected_at", updated["metadata"])
        self.assertIsNone(self.history.update_final_text("missing", "x"))


if __name__ == "__main__":
    unittest.main()
