"""Orchestrates dictation capture, speech recognition, AI polish, and desktop insertion."""

import json
import math
import os
import sys
import tempfile
import threading
import time
from typing import Any, Optional
from pynput import keyboard

from voiceflow_core import (
    AudioCapture,
    CredentialStore,
    DEFAULT_CONTEXT_PROMPT,
    DEFAULT_PRESET_HOTKEY,
    DEFAULT_PROMPT,
    DictationHistory,
    DictationStatus,
    FloatingOverlay,
    LLMService,
    MODIFIER_MAP,
    TranscriptionService,
    WRITING_STYLE_PROMPTS,
    apply_replacements,
    capture_selection,
    expand_snippet,
    focus_window,
    force_release_modifiers,
    get_foreground_app_context,
    log,
    normalize_key,
    paste_text,
    preset_for_keys,
    repair_preset_conflicts,
    safe_clipboard_get,
    safe_clipboard_set,
    send_shortcut,
    type_or_paste,
)

CONFIG_FILE = os.environ.get("VOICEFLOW_CONFIG_FILE", os.path.expanduser("~/.voiceflow_config.json"))
# Lifetime usage counters. Kept separate from history so that deleting or
# purging transcripts does not shrink the "words dictated" total.
ANALYTICS_FILE = os.environ.get("VOICEFLOW_ANALYTICS_FILE", os.path.expanduser("~/.voiceflow_analytics.json"))
HISTORY_PURGE_INTERVAL_SECONDS = 3600

BOOL_SETTINGS = ("main_dictation_ai", "use_local_llm", "app_aware_formatting", "silence_auto_stop", "onboarding_complete")
TEXT_SETTINGS = ("context_prompt", "custom_vocabulary", "text_replacements", "voice_snippets")
CHOICE_SETTINGS = {
    "output_mode": {"type", "copy"},
    "dictation_trigger_mode": {"hold", "toggle"},
    "transcription_engine": {"local", "groq"},
    "writing_style": set(WRITING_STYLE_PROMPTS),
}


def _play_sound(name: str) -> None:
    try:
        import winsound

        base_dir = sys._MEIPASS if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
        sound_path = os.path.join(base_dir, "static", "sounds", f"{name}.wav")
        if os.path.exists(sound_path):
            winsound.PlaySound(sound_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
    except Exception:
        pass


def _write_json_atomic(path: str, data: Any) -> None:
    """Write JSON via a temp file + rename so a crash never leaves a half-written file."""
    directory = os.path.dirname(os.path.abspath(path))
    descriptor, temp_path = tempfile.mkstemp(prefix=".voiceflow-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        os.replace(temp_path, path)
    except BaseException:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise


def _as_bool(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in {"true", "false", "1", "0"}:
        return value.strip().lower() in {"true", "1"}
    raise ValueError(f"{name} must be true or false")


def _as_text(value: Any, name: str, max_length: int = 20000) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be text")
    if len(value) > max_length:
        raise ValueError(f"{name} is too long")
    return value


def _as_choice(value: Any, name: str, choices: set) -> str:
    if value not in choices:
        raise ValueError(f"{name} must be one of: {', '.join(sorted(choices))}")
    return value


def _as_number(value: Any, name: str, minimum: float) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number") from None
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a number")
    return max(minimum, number)


def _hotkey_pair(key1: Any, key2: Any, name: str) -> frozenset:
    keys = []
    for key in (key1, key2):
        key = _as_text(key, name, 32).strip().lower()
        if not key:
            raise ValueError(f"{name} needs two keys")
        keys.append(MODIFIER_MAP.get(key, key))
    if keys[0] == keys[1]:
        raise ValueError(f"{name} keys must be different")
    return frozenset(keys)


def _parse_presets(value: Any) -> list[dict]:
    if not isinstance(value, list):
        raise ValueError("AI presets must be a list")
    presets = []
    for index, preset in enumerate(value, start=1):
        if not isinstance(preset, dict):
            raise ValueError(f"AI preset {index} is invalid")
        hotkeys = preset.get("hotkeys")
        if (
            not isinstance(hotkeys, list)
            or len(hotkeys) != 2
            or not all(isinstance(key, str) and key.strip() for key in hotkeys)
        ):
            raise ValueError(f"AI preset {index} needs two shortcut keys")
        presets.append({
            "id": str(preset.get("id") or f"preset_{index}"),
            "name": _as_text(preset.get("name") or f"Preset {index}", "Preset name", 200),
            "hotkeys": [key.strip().lower() for key in hotkeys],
            "prompt": _as_text(preset.get("prompt") or DEFAULT_PROMPT, "Preset prompt"),
        })
    return presets


class DictationAgent:
    """Orchestrates hotkey events, audio capture, transcription, and paste pipeline."""

    def __init__(self):
        self.hotkey = {"alt", "shift"}
        self.context_hotkey = {"ctrl", "shift"}
        self.keys_pressed = set()
        self.is_recording = False
        self._is_context_recording = False
        self._preset_hotkey_latched = False
        self._last_voice_edit: Optional[dict[str, Any]] = None
        self.is_paused = False
        self.status = "idle"

        self.context_prompt = DEFAULT_CONTEXT_PROMPT
        self.main_dictation_ai = False
        self.run_at_startup = False
        self.use_local_llm = False
        self.dictation_language = "auto"
        self.transcription_engine = "local"
        self.custom_vocabulary = ""
        self.writing_style = "natural"
        self.text_replacements = ""
        self.voice_snippets = ""
        self.history_retention_days = 30
        self.onboarding_complete = False
        self.app_aware_formatting = True
        self.output_mode = "type"
        self.dictation_trigger_mode = "hold"
        self.silence_auto_stop = True
        self.silence_timeout_seconds = 3.0
        self.silence_threshold = 0.01
        self._recording_lock = threading.RLock()
        self._config_lock = threading.RLock()
        self._analytics_lock = threading.Lock()
        self._stop_requested = False
        self._cancel_requested = False
        self._silence_monitor_thread = None
        self._active_app_context = None
        self._last_history_purge = 0.0

        self.ai_presets = [
            {
                "id": "preset_1",
                "name": "Default Grammar Polish",
                "hotkeys": DEFAULT_PRESET_HOTKEY.copy(),
                "prompt": DEFAULT_PROMPT,
            }
        ]

        self.api_key = ""
        self.credential_store = CredentialStore()
        self.history = DictationHistory()
        self._active_history_id = None

        # Core service sub-modules
        self.overlay = FloatingOverlay()
        self.audio = AudioCapture(sample_rate=16000, chunk_size=1024)
        self.transcriber = TranscriptionService(on_status=self.overlay.show_notification)
        self._listener = None
        self._running = False

        self._load_config()

    # ------------------------------------------------------------------ settings

    def _parse_settings(self, data: dict, strict: bool) -> dict:
        """Validate a settings payload. Strict mode raises; lenient mode skips bad fields."""
        parsed: dict[str, Any] = {}

        def attempt(name: str, parse) -> None:
            try:
                parsed[name] = parse()
            except (TypeError, ValueError) as e:
                if strict:
                    raise ValueError(str(e)) from None
                log(f"Ignoring invalid saved setting '{name}': {e}")

        if "key1" in data and "key2" in data:
            attempt("hotkey", lambda: _hotkey_pair(data["key1"], data["key2"], "Dictation shortcut"))
        if "context_key1" in data and "context_key2" in data:
            attempt("context_hotkey", lambda: _hotkey_pair(data["context_key1"], data["context_key2"], "Context shortcut"))
        if "ai_presets" in data:
            attempt("ai_presets", lambda: _parse_presets(data["ai_presets"]))
        for name in BOOL_SETTINGS + ("run_at_startup", "clear_api_key"):
            if name in data:
                attempt(name, lambda name=name: _as_bool(data[name], name))
        for name in TEXT_SETTINGS:
            if name in data:
                attempt(name, lambda name=name: _as_text(data[name], name))
        for name, choices in CHOICE_SETTINGS.items():
            if name in data:
                attempt(name, lambda name=name, choices=choices: _as_choice(data[name], name, choices))
        if "dictation_language" in data:
            attempt("dictation_language", lambda: _as_text(data["dictation_language"], "Language", 16).strip() or "auto")
        if "silence_timeout_seconds" in data:
            attempt("silence_timeout_seconds", lambda: _as_number(data["silence_timeout_seconds"], "Silence timeout", 3.0))
        if "silence_threshold" in data:
            attempt("silence_threshold", lambda: _as_number(data["silence_threshold"], "Silence threshold", 0.001))
        if "history_retention_days" in data:
            attempt("history_retention_days", lambda: int(_as_number(data["history_retention_days"], "History retention", 0)))
        if "api_key" in data:
            attempt("api_key", lambda: _as_text(data["api_key"], "API key", 512).strip())

        hotkey = parsed.get("hotkey", frozenset(self.hotkey))
        context_hotkey = parsed.get("context_hotkey", frozenset(self.context_hotkey))
        if hotkey == context_hotkey:
            if strict:
                raise ValueError("Dictation and context shortcuts must be different")
            parsed.pop("context_hotkey", None)
        return parsed

    def _apply_settings(self, parsed: dict) -> None:
        for name, value in parsed.items():
            if name in {"hotkey", "context_hotkey"}:
                setattr(self, name, set(value))
                self.keys_pressed.clear()
            else:
                setattr(self, name, value)

    def _load_config(self) -> None:
        if self.credential_store.available:
            self.api_key = self.credential_store.get_api_key()

        cfg: Any = {}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            except (OSError, ValueError) as e:
                log(f"Failed to load config: {e}")
        if not isinstance(cfg, dict):
            cfg = {}

        parsed = self._parse_settings(cfg, strict=False)
        legacy_key = parsed.pop("api_key", "")
        parsed.pop("clear_api_key", None)
        self._apply_settings(parsed)
        repair_preset_conflicts(self.ai_presets, self.hotkey, self.context_hotkey)

        if legacy_key and self.credential_store.available:
            # Move a plaintext key from older versions into the OS credential store,
            # then rewrite the config file without it.
            if self.api_key or self.set_api_key(legacy_key):
                self.save_config()
        elif legacy_key and not self.api_key:
            self.api_key = legacy_key

    def update_config(self, data: Any) -> None:
        """Validate and apply a settings change. Nothing is applied if any field is invalid."""
        if not isinstance(data, dict) or not data:
            raise ValueError("Expected a JSON object with the settings to change")
        parsed = self._parse_settings(data, strict=True)

        with self._config_lock:
            api_key = parsed.pop("api_key", "")
            clear_api_key = parsed.pop("clear_api_key", False)
            run_at_startup = parsed.pop("run_at_startup", None)

            self._apply_settings(parsed)
            if api_key:
                self.set_api_key(api_key)
            if clear_api_key:
                self.clear_api_key()
            if run_at_startup is not None:
                self.set_startup(run_at_startup)
            if "history_retention_days" in parsed:
                self._purge_history(force=True)
            self.save_config()

    def save_config(self) -> None:
        with self._config_lock:
            keys = list(self.hotkey)
            while len(keys) < 2:
                keys.append(keys[0] if keys else "ctrl")
            c_keys = list(self.context_hotkey)
            while len(c_keys) < 2:
                c_keys.append(c_keys[0] if c_keys else "shift")

            repair_preset_conflicts(self.ai_presets, self.hotkey, self.context_hotkey)
            cfg = {
                "key1": keys[0],
                "key2": keys[1],
                "context_key1": c_keys[0],
                "context_key2": c_keys[1],
                "ai_presets": self.ai_presets,
                "context_prompt": self.context_prompt,
                "main_dictation_ai": self.main_dictation_ai,
                "run_at_startup": self.run_at_startup,
                "use_local_llm": self.use_local_llm,
                "transcription_engine": self.transcription_engine,
                "custom_vocabulary": self.custom_vocabulary,
                "writing_style": self.writing_style,
                "text_replacements": self.text_replacements,
                "voice_snippets": self.voice_snippets,
                "history_retention_days": self.history_retention_days,
                "onboarding_complete": self.onboarding_complete,
                "app_aware_formatting": self.app_aware_formatting,
                "output_mode": self.output_mode,
                "dictation_language": self.dictation_language,
                "dictation_trigger_mode": self.dictation_trigger_mode,
                "silence_auto_stop": self.silence_auto_stop,
                "silence_timeout_seconds": self.silence_timeout_seconds,
                "silence_threshold": self.silence_threshold,
            }
            if self.api_key and not self.credential_store.available:
                # Without an OS credential store the key would otherwise be lost on restart.
                cfg["api_key"] = self.api_key
            try:
                _write_json_atomic(CONFIG_FILE, cfg)
            except Exception as e:
                log(f"Failed to save config: {e}")

    def set_api_key(self, value: str) -> bool:
        self.api_key = (value or "").strip()
        if self.credential_store.available and self.api_key:
            return self.credential_store.set_api_key(self.api_key)
        return False

    def clear_api_key(self) -> bool:
        self.api_key = ""
        if self.credential_store.available:
            return self.credential_store.delete_api_key()
        return False

    # ----------------------------------------------------------------- lifecycle

    def start(self) -> None:
        self._running = True
        threading.Thread(target=self.overlay.start, daemon=True).start()
        self.audio.start()
        self._purge_history(force=True)

        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.start()
        log("Agent started and listening for hotkeys.")

    def stop(self) -> None:
        self._running = False
        if self._listener:
            try:
                self._listener.stop()
            except Exception:
                pass
        self.audio.stop()
        log("Agent stopped.")

    def toggle_pause(self) -> bool:
        self.is_paused = not self.is_paused
        status_msg = "Dictation Paused" if self.is_paused else "Dictation Resumed"
        self.overlay.show_notification(status_msg)
        log(status_msg)
        return self.is_paused

    # ------------------------------------------------------------------- hotkeys

    def _on_press(self, key) -> None:
        if self.is_paused:
            return

        try:
            n = normalize_key(key)
        except Exception:
            return
        if not n:
            return
        # A held key auto-repeats key-down events; only a fresh press can complete a chord.
        is_repeat = n in self.keys_pressed
        self.keys_pressed.add(n)
        if is_repeat:
            return

        if n == "esc" and self.is_recording:
            self._cancel_recording()
            return

        if self.is_recording:
            active_hotkey = self.context_hotkey if self._is_context_recording else self.hotkey
            if self.dictation_trigger_mode == "toggle" and active_hotkey.issubset(self.keys_pressed):
                self._stop_recording()
            return

        if self.status != "idle":
            return

        if not self._preset_hotkey_latched:
            preset = preset_for_keys(self.ai_presets, self.keys_pressed)
            if preset:
                self._preset_hotkey_latched = True
                self._start_ai_edit(preset.get("prompt") or DEFAULT_PROMPT)
                return

        if self.context_hotkey.issubset(self.keys_pressed):
            self._start_recording(context=True)
        elif self.hotkey.issubset(self.keys_pressed):
            self._start_recording(context=False)

    def _on_release(self, key) -> None:
        try:
            n = normalize_key(key)
            if n and n in self.keys_pressed:
                self.keys_pressed.remove(n)
        except Exception:
            pass

        if not self.keys_pressed:
            self._preset_hotkey_latched = False

        if self.is_recording and self.dictation_trigger_mode == "hold":
            trigger_hotkey = self.context_hotkey if self._is_context_recording else self.hotkey
            if not trigger_hotkey.issubset(self.keys_pressed):
                self._stop_recording()

    def _wait_for_hotkey_release(self, timeout: float = 2.0) -> None:
        deadline = time.time() + timeout
        while self.keys_pressed and time.time() < deadline:
            time.sleep(0.05)
        self.keys_pressed.clear()

    # ----------------------------------------------------------------- recording

    def _start_recording(self, context: bool) -> None:
        with self._recording_lock:
            if self.is_recording or self.status != "idle":
                return
            self._is_context_recording = context
            self.is_recording = True
            self._stop_requested = False
            self._cancel_requested = False
            self.status = "listening"
            self.overlay.set_state("listening")
            _play_sound("start")

            # Always identify the target app: it decides whether probing for a
            # selection is safe. It only shapes the AI prompt when app-aware
            # formatting is enabled.
            self._active_app_context = get_foreground_app_context()
            metadata = {}
            if self.app_aware_formatting:
                metadata = {
                    "process_name": self._active_app_context.process_name,
                    "window_title": self._active_app_context.window_title,
                    "app_category": self._active_app_context.category,
                }
            try:
                self._active_history_id = self.history.create(
                    mode="context_reply" if context else "dictation",
                    status=DictationStatus.LISTENING,
                    language=self.dictation_language,
                    transcription_engine=self.transcription_engine,
                    metadata=metadata,
                )
            except Exception as e:
                log(f"Failed to create history record: {e}")
                self._active_history_id = None

            self.audio.start_recording()
            if self.dictation_trigger_mode == "toggle" and self.silence_auto_stop:
                self._silence_monitor_thread = threading.Thread(target=self._monitor_silence, daemon=True)
                self._silence_monitor_thread.start()

    def _stop_recording(self) -> None:
        with self._recording_lock:
            if not self.is_recording or self._stop_requested:
                return
            self._stop_requested = True
            _play_sound("stop")
            self.is_recording = False
            self.keys_pressed.clear()
            self.status = "processing"
            self.overlay.set_state("processing")

            raw_audio = self.audio.stop_recording()
            history_id = self._active_history_id
            self._active_history_id = None
            is_context_recording = self._is_context_recording
            app_context = self._active_app_context

        self._process_recording(raw_audio, history_id, is_context_recording, app_context)

    def _cancel_recording(self) -> None:
        with self._recording_lock:
            if not self.is_recording:
                return
            self._cancel_requested = True
            self.is_recording = False
            self.keys_pressed.clear()
            self.audio.stop_recording()
            history_id = self._active_history_id
            self._active_history_id = None
            self._active_app_context = None
            self.status = "idle"

        if history_id:
            try:
                self.history.transition(
                    history_id,
                    DictationStatus.CANCELLED,
                    error_code="cancelled",
                    error_message="Recording cancelled by user.",
                )
            except Exception as e:
                log(f"Could not mark dictation as cancelled: {e}")
        self.overlay.show_notification("Dictation cancelled")
        self.overlay.set_state("idle")
        _play_sound("stop")
        log("Dictation cancelled.")

    def _monitor_silence(self) -> None:
        started_at = time.time()
        last_voice_at = None
        speech_started = False
        while self._running:
            time.sleep(0.1)
            if not self.is_recording or self._cancel_requested or self._stop_requested:
                return
            if self.dictation_trigger_mode != "toggle" or not self.silence_auto_stop:
                return
            volume = getattr(self.audio, "current_volume", 0.0)
            now = time.time()
            if volume >= self.silence_threshold:
                speech_started = True
                last_voice_at = now
            startup_grace_period = 4.0
            minimum_recording_seconds = 1.5
            if not speech_started and now - started_at < startup_grace_period:
                continue
            if not speech_started:
                last_voice_at = now
                speech_started = True
            if (
                last_voice_at
                and now - started_at >= minimum_recording_seconds
                and now - last_voice_at >= self.silence_timeout_seconds
            ):
                log("Silence detected. Stopping toggle-mode dictation.")
                self._stop_recording()
                return

    def _process_recording(
        self,
        raw_audio: bytes,
        history_id: Optional[str],
        is_context_recording: bool,
        app_context: Any = None,
    ) -> None:
        def process():
            recovery_audio_path = None
            selection = {"text": ""}
            selection_thread = None
            try:
                if not raw_audio:
                    log("No audio captured.")
                    if history_id:
                        self.history.fail(history_id, "No audio was captured.", code="no_audio")
                    return

                # Look for selected text (voice edit) while transcription runs. This
                # happens after the hotkey is released so the synthetic Ctrl+C never
                # blocks the keyboard hook or collides with the held shortcut.
                if not is_context_recording and app_context is not None and app_context.allows_selection_capture:
                    selection_thread = threading.Thread(
                        target=lambda: selection.update(text=capture_selection()),
                        daemon=True,
                    )
                    selection_thread.start()

                secs = len(raw_audio) / (self.audio.sample_rate * 2)
                log(f"Captured {len(raw_audio)} bytes ({secs:.1f}s)")
                if history_id:
                    try:
                        recovery_audio_path = self.history.save_recovery_audio(
                            history_id, raw_audio, self.audio.sample_rate
                        )
                    except Exception as e:
                        log(f"Could not save recovery audio: {e}")
                    self.history.transition(
                        history_id,
                        DictationStatus.TRANSCRIBING,
                        duration_ms=round(secs * 1000),
                        audio_path=recovery_audio_path,
                    )

                raw_text = self.transcriber.transcribe_raw(
                    raw_audio,
                    sample_rate=self.audio.sample_rate,
                    engine=self.transcription_engine,
                    api_key=self.api_key,
                    language=self.dictation_language,
                    custom_vocabulary=self.custom_vocabulary,
                )
                if selection_thread:
                    selection_thread.join(timeout=2.0)
                voice_edit_selection = selection["text"]

                if not raw_text or not raw_text.strip():
                    log("No speech detected.")
                    if history_id:
                        self.history.fail(history_id, "No speech was detected.", code="no_speech")
                    return

                text = raw_text.strip()
                app_instruction = app_context.instruction if app_context and self.app_aware_formatting else ""

                if voice_edit_selection:
                    log("Selected text detected. Applying voice edit.")
                    if history_id:
                        self.history.transition(
                            history_id, DictationStatus.POLISHING, raw_text=text, mode="voice_edit"
                        )
                    self.overlay.set_state("ai_edit")
                    edited_text = self._rewrite_selected_text(voice_edit_selection, text)
                    if not edited_text:
                        if history_id:
                            self.history.fail(
                                history_id,
                                "Voice edit could not produce rewritten text.",
                                code="voice_edit_failed",
                                raw_text=text,
                            )
                        return

                    if paste_text(edited_text):
                        self._remember_edit(voice_edit_selection, edited_text, app_context)
                        if history_id:
                            self.history.discard_recovery_audio(recovery_audio_path)
                            self.history.complete(history_id, edited_text, raw_text=text, audio_path="")
                        self._update_analytics(edited_text)
                    elif history_id:
                        self.history.discard_recovery_audio(recovery_audio_path)
                        self.history.fail(
                            history_id,
                            "VoiceFlow could not paste the edited text.",
                            code="voice_edit_paste_failed",
                            raw_text=text,
                            final_text=edited_text,
                            audio_path="",
                        )
                    return

                use_ai = is_context_recording or self.main_dictation_ai

                if use_ai:
                    if history_id:
                        self.history.transition(history_id, DictationStatus.POLISHING, raw_text=text)
                    self.overlay.set_state("ai_edit")

                    clipboard_context = safe_clipboard_get() if is_context_recording else ""
                    text = LLMService.apply_post_processing(
                        text=text,
                        api_key=self.api_key,
                        is_context_recording=is_context_recording,
                        main_dictation_ai=self.main_dictation_ai,
                        writing_style=self.writing_style,
                        context_prompt=self.context_prompt,
                        clipboard_context=clipboard_context,
                        app_instruction=app_instruction,
                        use_local_llm=self.use_local_llm,
                        on_error=self.overlay.show_error,
                    )
                elif history_id:
                    self.history.transition(history_id, DictationStatus.PASTING, raw_text=text)

                if text and text.strip():
                    text = expand_snippet(text, self.voice_snippets)
                    text = apply_replacements(text, self.text_replacements)
                    if history_id and use_ai:
                        self.history.transition(history_id, DictationStatus.PASTING)

                    log(f"Pasting text: {len(text)} characters")
                    if type_or_paste(text, mode=self.output_mode):
                        if history_id:
                            self.history.discard_recovery_audio(recovery_audio_path)
                            self.history.complete(history_id, text, audio_path="")
                        self._update_analytics(text)
                    elif history_id:
                        self.history.discard_recovery_audio(recovery_audio_path)
                        self.history.fail(
                            history_id,
                            "The transcript was saved, but VoiceFlow could not copy or paste it.",
                            code="paste_failed",
                            final_text=text,
                            audio_path="",
                        )
                else:
                    if history_id:
                        self.history.discard_recovery_audio(recovery_audio_path)
                        self.history.fail(history_id, "AI polish returned empty text.", code="empty_ai_result")
            except Exception as e:
                log(f"Dictation processing error: {e}")
                if history_id:
                    try:
                        self.history.fail(history_id, str(e))
                    except Exception:
                        pass
            finally:
                self.status = "idle"
                self._stop_requested = False
                self._cancel_requested = False
                self._is_context_recording = False
                self._active_app_context = None
                self.overlay.set_state("idle")
                self._purge_history()

        threading.Thread(target=process, daemon=True).start()

    # ------------------------------------------------------------------ AI edits

    def _rewrite_selected_text(self, selected_text: str, spoken_instruction: str) -> Optional[str]:
        prompt = (
            "You are a voice-controlled editor. Rewrite the selected text using the user's spoken instruction. "
            "Return ONLY the rewritten text. Do not explain, quote, label, or add a preamble. "
            "Preserve the user's meaning unless the instruction clearly asks for a change."
        )
        request_text = (
            f"Selected text:\n{selected_text}\n\n"
            f"Spoken instruction:\n{spoken_instruction}\n\n"
            "Rewrite the selected text now."
        )
        return LLMService.enhance_with_llm(
            request_text,
            prompt,
            api_key=self.api_key,
            use_local_llm=self.use_local_llm,
            on_error=self.overlay.show_error,
        )

    def _remember_edit(self, original_text: str, edited_text: str, app_context: Any) -> None:
        self._last_voice_edit = {
            "original_text": original_text,
            "edited_text": edited_text,
            "window_handle": getattr(app_context, "window_handle", 0),
            "created_at": time.time(),
        }

    def undo_last_voice_edit(self) -> bool:
        """Undo the most recent voice edit or AI preset edit in the app it was pasted into."""
        if not self._last_voice_edit:
            self.overlay.show_notification("No AI edit to undo")
            return False
        with self._recording_lock:
            if self.is_recording or self.status != "idle":
                return False
            self.status = "ai_edit"
        try:
            # The tray menu takes focus, so return it to the edited window first.
            focus_window(self._last_voice_edit.get("window_handle", 0))
            time.sleep(0.15)
            force_release_modifiers()
            send_shortcut("z")
            self._last_voice_edit = None
            self.overlay.show_notification("Last AI edit undone")
            log("Undo last voice edit triggered.")
            return True
        except Exception as e:
            log(f"Undo voice edit error: {e}")
            self.overlay.show_error("Undo failed")
            return False
        finally:
            self.status = "idle"

    def _start_ai_edit(self, prompt: str) -> None:
        with self._recording_lock:
            if self.is_recording or self.status != "idle":
                return
            self.status = "ai_edit"
        threading.Thread(target=self._trigger_ai_edit, args=(prompt,), daemon=True).start()

    def _trigger_ai_edit(self, prompt: str) -> None:
        _play_sound("start")
        self.overlay.set_state("ai_edit")
        log("AI Edit triggered on selected text...")

        try:
            self._wait_for_hotkey_release()
            app_context = get_foreground_app_context()
            if app_context.category == "terminal":
                # Ctrl+C would interrupt the running command instead of copying.
                self.overlay.show_notification("AI presets are not available in terminals")
                return

            selected_text = capture_selection(timeout=1.5)
            if not selected_text:
                log("No text selected or copy failed.")
                self.overlay.show_notification("Select text first")
                return

            new_text = LLMService.enhance_with_llm(
                selected_text,
                prompt,
                api_key=self.api_key,
                use_local_llm=self.use_local_llm,
                on_error=self.overlay.show_error,
            )
            if not new_text:
                log("AI Edit aborted: no rewritten text.")
                return

            if paste_text(new_text, wait=True):
                self._remember_edit(selected_text, new_text, app_context)
                _play_sound("stop")
                log("AI Edit complete.")
            else:
                self.overlay.show_error("Could not paste the edited text")
        except Exception as e:
            log(f"AI Edit error: {e}")
        finally:
            self.status = "idle"
            self.overlay.set_state("idle")

    # ------------------------------------------------------------ files, history

    def transcribe_file(self, filepath: str) -> Optional[str]:
        history_id = None
        try:
            history_id = self.history.create(
                mode="file",
                status=DictationStatus.TRANSCRIBING,
                language=self.dictation_language,
                transcription_engine=self.transcription_engine,
                metadata={"source_name": os.path.basename(filepath)},
            )
            text = self.transcriber.transcribe_file(
                filepath,
                engine=self.transcription_engine,
                api_key=self.api_key,
                language=self.dictation_language,
                custom_vocabulary=self.custom_vocabulary,
            )
            if text and text.strip():
                self.history.complete(history_id, text.strip(), raw_text=text.strip())
                self._update_analytics(text)
                return text.strip()
            if history_id:
                self.history.fail(history_id, "File transcription returned no text.")
            return None
        except Exception as e:
            log(f"File transcription failed: {e}")
            if history_id:
                try:
                    self.history.fail(history_id, str(e))
                except Exception:
                    pass
            return None

    def get_history(self, limit: int = 100, offset: int = 0, query: str = ""):
        return self.history.list(limit=limit, offset=offset, query=query)

    def get_history_item(self, job_id: str):
        return self.history.get(job_id)

    def delete_history_item(self, job_id: str) -> bool:
        item = self.get_history_item(job_id)
        if item and item.get("audio_path"):
            self.history.discard_recovery_audio(item["audio_path"])
        return self.history.delete(job_id)

    def clear_history(self) -> int:
        return self.history.clear()

    def _purge_history(self, force: bool = False) -> None:
        """Apply the retention setting, at most once per interval unless forced."""
        now = time.time()
        if not force and now - self._last_history_purge < HISTORY_PURGE_INTERVAL_SECONDS:
            return
        self._last_history_purge = now
        try:
            removed = self.history.purge_older_than(self.history_retention_days)
            if removed:
                log(f"Removed {removed} history item(s) past the retention period.")
        except Exception as e:
            log(f"History retention purge failed: {e}")

    def retry_history_item(self, job_id: str):
        item = self.history.get(job_id)
        if not item or not item.get("audio_path") or not os.path.exists(item["audio_path"]):
            return None

        self.history.transition(job_id, DictationStatus.TRANSCRIBING, error_code="", error_message="")
        try:
            with open(item["audio_path"], "rb") as f:
                raw_audio = f.read()

            raw_text = self.transcriber.transcribe_raw(
                raw_audio,
                sample_rate=self.audio.sample_rate,
                engine=item.get("transcription_engine") or self.transcription_engine,
                api_key=self.api_key,
                language=item.get("language") or self.dictation_language,
                custom_vocabulary=self.custom_vocabulary,
            )

            if raw_text and raw_text.strip():
                final_text = raw_text.strip()
                self.history.discard_recovery_audio(item["audio_path"])
                self._update_analytics(final_text)
                return self.history.complete(job_id, final_text, raw_text=final_text, audio_path="")
            self.history.fail(job_id, "Retry transcription returned empty text.", code="retry_empty")
            return self.history.get(job_id)
        except Exception as e:
            self.history.fail(job_id, f"Retry error: {e}", code="retry_failed")
            return self.history.get(job_id)

    def _history_text(self, job_id: Optional[str] = None) -> str:
        item = self.history.get(job_id) if job_id else self.history.latest()
        if not item:
            return ""
        return (item.get("final_text") or item.get("raw_text") or "").strip()

    def copy_history_item(self, job_id: Optional[str] = None) -> bool:
        text = self._history_text(job_id)
        return bool(text) and safe_clipboard_set(text)

    def paste_history_item(self, job_id: Optional[str] = None) -> bool:
        text = self._history_text(job_id)
        if not text:
            return False
        return paste_text(text, restore_clipboard=False)

    # ----------------------------------------------------------------- analytics

    def _read_analytics(self) -> dict[str, int]:
        try:
            with open(ANALYTICS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {
                "total_words": max(0, int(data.get("total_words", 0))),
                "sessions": max(0, int(data.get("sessions", 0))),
            }
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError, AttributeError) as e:
            log(f"Failed to read analytics: {e}")
        return {"total_words": 0, "sessions": 0}

    def get_analytics(self) -> dict[str, int]:
        with self._analytics_lock:
            return self._read_analytics()

    def _update_analytics(self, text: str) -> None:
        if not text:
            return
        with self._analytics_lock:
            data = self._read_analytics()
            data["total_words"] += len(text.split())
            data["sessions"] += 1
            try:
                _write_json_atomic(ANALYTICS_FILE, data)
            except Exception as e:
                log(f"Failed to update analytics: {e}")

    # ------------------------------------------------------------------- startup

    def set_startup(self, enabled: bool) -> None:
        self.run_at_startup = enabled
        if getattr(sys, "frozen", False):
            command = f'"{sys.executable}"'
        else:
            python_exe = sys.executable
            if sys.platform == "win32" and python_exe.lower().endswith("python.exe"):
                python_exe = python_exe[:-10] + "pythonw.exe"
            command = f'"{python_exe}" "{os.path.abspath(sys.argv[0])}"'

        if sys.platform == "win32":
            try:
                import winreg

                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Run",
                    0,
                    winreg.KEY_SET_VALUE,
                )
                if enabled:
                    winreg.SetValueEx(key, "VoiceFlow", 0, winreg.REG_SZ, command)
                    log("Added to Windows Startup.")
                else:
                    try:
                        winreg.DeleteValue(key, "VoiceFlow")
                        log("Removed from Windows Startup.")
                    except FileNotFoundError:
                        pass
                winreg.CloseKey(key)
            except Exception as e:
                log(f"Failed to update Windows startup registry: {e}")
        elif sys.platform.startswith("linux"):
            try:
                autostart_dir = os.path.expanduser("~/.config/autostart")
                os.makedirs(autostart_dir, exist_ok=True)
                desktop_file = os.path.join(autostart_dir, "VoiceFlow.desktop")
                if enabled:
                    content = f"""[Desktop Entry]
Type=Application
Exec={command}
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Name=VoiceFlow
Comment=AI Dictation Everywhere
"""
                    with open(desktop_file, "w") as f:
                        f.write(content)
                    log("Added to Linux Autostart.")
                else:
                    if os.path.exists(desktop_file):
                        os.remove(desktop_file)
                    log("Removed from Linux Autostart.")
            except Exception as e:
                log(f"Failed to update Linux autostart: {e}")

    def get_config(self) -> dict:
        keys = list(self.hotkey)
        while len(keys) < 2:
            keys.append(keys[0] if keys else "ctrl")
        c_keys = list(self.context_hotkey)
        while len(c_keys) < 2:
            c_keys.append(c_keys[0] if c_keys else "shift")

        return {
            "status": self.status,
            "is_paused": self.is_paused,
            "hotkey": keys[:2],
            "context_hotkey": c_keys[:2],
            "ai_presets": self.ai_presets,
            "api_key": "",
            "api_key_configured": bool(self.api_key),
            "default_prompt": DEFAULT_PROMPT,
            "default_context_prompt": DEFAULT_CONTEXT_PROMPT,
            "context_prompt": self.context_prompt,
            "main_dictation_ai": self.main_dictation_ai,
            "run_at_startup": self.run_at_startup,
            "use_local_llm": self.use_local_llm,
            "transcription_engine": self.transcription_engine,
            "custom_vocabulary": self.custom_vocabulary,
            "writing_style": self.writing_style,
            "text_replacements": self.text_replacements,
            "voice_snippets": self.voice_snippets,
            "history_retention_days": self.history_retention_days,
            "onboarding_complete": self.onboarding_complete,
            "app_aware_formatting": self.app_aware_formatting,
            "output_mode": self.output_mode,
            "dictation_language": self.dictation_language,
            "dictation_trigger_mode": self.dictation_trigger_mode,
            "silence_auto_stop": self.silence_auto_stop,
            "silence_timeout_seconds": self.silence_timeout_seconds,
            "silence_threshold": self.silence_threshold,
        }
