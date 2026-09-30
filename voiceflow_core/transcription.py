"""Speech-to-text transcription service supporting local Faster-Whisper and Groq Whisper."""

import os
import tempfile
import wave
from typing import Callable, Optional

from voiceflow_core.safe_logging import log


class TranscriptionService:
    """Provides speech-to-text transcription via local Faster-Whisper or Groq cloud."""

    def __init__(self, on_status: Optional[Callable[[str], None]] = None):
        self.on_status = on_status
        self.whisper_model = None
        self._has_speechrec = True

    def get_whisper_model(self):
        if not self._has_speechrec:
            return None
        if self.whisper_model is None:
            if self.on_status:
                self.on_status("Loading AI... (first time only)")
            log("Loading Faster-Whisper model (base)...")
            try:
                from faster_whisper import WhisperModel
                self.whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
                log("Whisper model loaded!")
                if self.on_status:
                    self.on_status("idle")
            except Exception as e:
                log(f"Failed to load Whisper model: {e}")
                self._has_speechrec = False
                if self.on_status:
                    self.on_status("idle")
        return self.whisper_model

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
            if not api_key:
                log("API key missing. Cannot use Groq for transcription.")
                return None
            try:
                from groq import Groq

                fd, temp_path = tempfile.mkstemp(suffix=".wav")
                os.close(fd)
                try:
                    with wave.open(temp_path, "wb") as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(sample_rate)
                        wf.writeframes(raw_bytes)

                    log("Transcribing with Groq Whisper...")
                    client = Groq(api_key=api_key)
                    lang = None if language == "auto" else language

                    base_prompt = "Here is a transcription with correct capitalization, commas, and periods."
                    vocab = (custom_vocabulary or "").strip()
                    if vocab:
                        base_prompt += f" Vocabulary: {vocab}"

                    kwargs = {
                        "file": (os.path.basename(temp_path), open(temp_path, "rb").read()),
                        "model": "whisper-large-v3-turbo",
                        "prompt": base_prompt,
                        "response_format": "text",
                    }
                    if lang:
                        kwargs["language"] = lang

                    transcription = client.audio.transcriptions.create(**kwargs)
                    log("Transcription received from Groq")
                    return transcription.strip()
                finally:
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass
            except Exception as e:
                log(f"Groq Transcription error: {e}")
                return None

        # Local Faster-Whisper
        model = self.get_whisper_model()
        if not model:
            log("Cannot transcribe locally: faster_whisper not available or model failed to load")
            return None

        try:
            import numpy as np
            audio_data = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0

            log("Transcribing with Faster-Whisper...")
            lang = None if language == "auto" else language
            base_prompt = "Here is a transcription with correct capitalization, commas, and periods."
            vocab = (custom_vocabulary or "").strip()
            if vocab:
                base_prompt += f" Vocabulary: {vocab}"

            segments, _info = model.transcribe(
                audio_data,
                language=lang,
                beam_size=1,
                vad_filter=False,
                initial_prompt=base_prompt,
            )
            text = " ".join([segment.text for segment in segments])
            log("Transcription received")
            return text.strip()
        except Exception as e:
            log(f"Transcription error: {e}")
            return None

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
            if not api_key:
                log("API key missing. Cannot use Groq for file transcription.")
                return None
            try:
                from groq import Groq
                log(f"Transcribing file with Groq: {filepath}")
                client = Groq(api_key=api_key)
                lang = None if language == "auto" else language

                base_prompt = "Here is a transcription with correct capitalization, commas, and periods."
                vocab = (custom_vocabulary or "").strip()
                if vocab:
                    base_prompt += f" Vocabulary: {vocab}"

                kwargs = {
                    "file": (os.path.basename(filepath), open(filepath, "rb").read()),
                    "model": "whisper-large-v3-turbo",
                    "prompt": base_prompt,
                    "response_format": "text",
                }
                if lang:
                    kwargs["language"] = lang

                transcription = client.audio.transcriptions.create(**kwargs)
                log("File transcription complete (Groq)")
                return transcription.strip()
            except Exception as e:
                log(f"Groq File transcription error: {e}")
                return None

        # Local
        model = self.get_whisper_model()
        if not model:
            log("Cannot transcribe: faster_whisper not available")
            return None

        try:
            log(f"Transcribing file locally: {filepath}")
            lang = None if language == "auto" else language
            base_prompt = "Here is a transcription with correct capitalization, commas, and periods."
            vocab = (custom_vocabulary or "").strip()
            if vocab:
                base_prompt += f" Vocabulary: {vocab}"

            segments, _info = model.transcribe(
                filepath,
                language=lang,
                beam_size=1,
                vad_filter=True,
                initial_prompt=base_prompt,
            )
            text = " ".join([segment.text for segment in segments])
            log("File transcription complete")
            return text.strip()
        except Exception as e:
            log(f"File transcription error: {e}")
            return None
