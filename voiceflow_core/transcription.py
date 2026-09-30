"""Speech-to-text transcription service supporting local Faster-Whisper and Groq Whisper."""

import os
import tempfile
import threading
import time
import wave
from typing import Callable, Optional

from voiceflow_core.safe_logging import log

GROQ_WHISPER_MODEL = "whisper-large-v3-turbo"
LOCAL_WHISPER_MODEL = "base"
# After a failed model load (e.g. an interrupted first download), wait this long
# before trying again instead of disabling local transcription until restart.
MODEL_RETRY_SECONDS = 60.0


def _build_prompt(custom_vocabulary: str) -> str:
    prompt = "Here is a transcription with correct capitalization, commas, and periods."
    vocab = (custom_vocabulary or "").strip()
    if vocab:
        prompt += f" Vocabulary: {vocab}"
    return prompt


class TranscriptionService:
    """Provides speech-to-text transcription via local Faster-Whisper or Groq cloud."""

    def __init__(self, on_status: Optional[Callable[[str], None]] = None):
        self.on_status = on_status
        self.whisper_model = None
        self._model_lock = threading.Lock()
        self._last_load_failure = 0.0

    def get_whisper_model(self):
        with self._model_lock:
            if self.whisper_model is not None:
                return self.whisper_model
            if self._last_load_failure and time.time() - self._last_load_failure < MODEL_RETRY_SECONDS:
                return None

            if self.on_status:
                self.on_status("Loading speech model (first time only)")
            log(f"Loading Faster-Whisper model ({LOCAL_WHISPER_MODEL})...")
            try:
                from faster_whisper import WhisperModel

                self.whisper_model = WhisperModel(LOCAL_WHISPER_MODEL, device="cpu", compute_type="int8")
                self._last_load_failure = 0.0
                log("Whisper model loaded!")
            except Exception as e:
                log(f"Failed to load Whisper model: {e}")
                self._last_load_failure = time.time()
            return self.whisper_model

    def _transcribe_groq(self, filepath: str, api_key: str, language: str, custom_vocabulary: str) -> Optional[str]:
        if not api_key:
            log("API key missing. Cannot use Groq for transcription.")
            return None
        try:
            from groq import Groq

            with open(filepath, "rb") as audio_file:
                audio_bytes = audio_file.read()
            kwargs = {
                "file": (os.path.basename(filepath), audio_bytes),
                "model": GROQ_WHISPER_MODEL,
                "prompt": _build_prompt(custom_vocabulary),
                "response_format": "text",
            }
            if language != "auto":
                kwargs["language"] = language

            log("Transcribing with Groq Whisper...")
            transcription = Groq(api_key=api_key).audio.transcriptions.create(**kwargs)
            log("Transcription received from Groq")
            return transcription.strip()
        except Exception as e:
            log(f"Groq transcription error: {e}")
            return None

    def _transcribe_local(self, audio, language: str, custom_vocabulary: str, vad_filter: bool) -> Optional[str]:
        model = self.get_whisper_model()
        if not model:
            log("Cannot transcribe locally: faster_whisper not available or model failed to load")
            return None
        try:
            log("Transcribing with Faster-Whisper...")
            segments, _info = model.transcribe(
                audio,
                language=None if language == "auto" else language,
                beam_size=1,
                vad_filter=vad_filter,
                initial_prompt=_build_prompt(custom_vocabulary),
            )
            text = " ".join(segment.text for segment in segments)
            log("Transcription received")
            return text.strip()
        except Exception as e:
            log(f"Transcription error: {e}")
            return None

    def transcribe_raw(
        self,
        raw_bytes: bytes,
        sample_rate: int = 16000,
        engine: str = "local",
        api_key: str = "",
        language: str = "auto",
        custom_vocabulary: str = "",
    ) -> Optional[str]:
        if not raw_bytes:
            return None

        if engine == "groq":
            fd, temp_path = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            try:
                with wave.open(temp_path, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(sample_rate)
                    wf.writeframes(raw_bytes)
                return self._transcribe_groq(temp_path, api_key, language, custom_vocabulary)
            finally:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

        import numpy as np

        audio_data = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        return self._transcribe_local(audio_data, language, custom_vocabulary, vad_filter=False)

    def transcribe_file(
        self,
        filepath: str,
        engine: str = "local",
        api_key: str = "",
        language: str = "auto",
        custom_vocabulary: str = "",
    ) -> Optional[str]:
        if not filepath or not os.path.exists(filepath):
            return None

        if engine == "groq":
            return self._transcribe_groq(filepath, api_key, language, custom_vocabulary)
        log("Transcribing file locally")
        return self._transcribe_local(filepath, language, custom_vocabulary, vad_filter=True)
