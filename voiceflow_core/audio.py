"""Audio capture and watchdog management."""

import collections
import threading
import time
from typing import Callable, Optional

import pyaudio

from voiceflow_core.safe_logging import log


class AudioCapture:
    """Manages PyAudio stream, watchdog, dynamic volume metering, and audio buffer."""

    def __init__(
        self,
        sample_rate: int = 16000,
        chunk_size: int = 1024,
        on_volume: Optional[Callable[[float], None]] = None,
    ):
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.on_volume = on_volume
        self.is_recording = False
        self._running = False
        self._pa: Optional[pyaudio.PyAudio] = None
        self._stream: Optional[pyaudio.Stream] = None
        self._audio_chunks: list[bytes] = []
        self._rolling_buffer = collections.deque(maxlen=8)
        self._last_callback_time = time.time()
        self.current_volume: float = 0.0

    def start(self) -> None:
        self._running = True
        try:
            self._pa = pyaudio.PyAudio()
            self._reopen_stream()
            threading.Thread(target=self._watchdog, daemon=True).start()
        except Exception as e:
            log(f"Audio system initialization error: {e}")

    def _reopen_stream(self) -> None:
        if not self._pa:
            return
        try:
            if self._stream:
                self._stream.stop_stream()
                self._stream.close()
        except Exception:
            pass

        try:
            self._stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=self.chunk_size,
                stream_callback=self._audio_callback,
            )
            self._stream.start_stream()
            self._last_callback_time = time.time()
            log("Audio stream connected.")
        except Exception as e:
            log(f"Failed to open audio stream: {e}")

    def _audio_callback(self, in_data, frame_count, time_info, status):
        self._last_callback_time = time.time()
        self._rolling_buffer.append(in_data)

        try:
            import numpy as np
            audio_data = np.frombuffer(in_data, dtype=np.int16).astype(np.float32)
            volume = float(np.sqrt(np.mean(np.square(audio_data))) / 32768.0)
            self.current_volume = volume
            if self.on_volume:
                self.on_volume(volume)
        except Exception:
            pass

        if self.is_recording:
            self._audio_chunks.append(in_data)
        return (None, pyaudio.paContinue)

    def _watchdog(self) -> None:
        while self._running:
            time.sleep(1.0)
            if time.time() - self._last_callback_time > 2.0:
                if not self.is_recording:
                    log("Hardware audio interrupt detected. Rebuilding audio stream...")
                    self._reopen_stream()
                else:
                    self._last_callback_time = time.time()

    def start_recording(self) -> None:
        self._audio_chunks = list(self._rolling_buffer)
        self.is_recording = True

    def stop_recording(self) -> bytes:
        self.is_recording = False
        chunks = self._audio_chunks
        self._audio_chunks = []
        return b"".join(chunks)

    def stop(self) -> None:
        self._running = False
        self.is_recording = False
        if self._stream:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
        if self._pa:
            try:
                self._pa.terminate()
            except Exception:
                pass
        log("Audio capture stopped.")
