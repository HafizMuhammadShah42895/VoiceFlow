"""Orchestrates dictation capture, speech recognition, AI polish, and desktop insertion."""

import collections
import json
import os
import sys
import threading
import time
from typing import Any, Optional
from pynput import keyboard

from voiceflow_core import (
    AudioCapture,
    CredentialStore,
    DEFAULT_CONTEXT_PROMPT,
    DEFAULT_DICTATION_PROMPT,
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
    expand_snippet,
    force_release_modifiers,
    get_foreground_app_context,
    log,
    normalize_key,
    repair_preset_conflicts,
    safe_clipboard_get,
    safe_clipboard_set,
    type_or_paste,
)

CONFIG_FILE = os.environ.get("VOICEFLOW_CONFIG_FILE", os.path.expanduser("~/.voiceflow_config.json"))


def _play_sound(name: str) -> None:
    try:
        import winsound

        base_dir = sys._MEIPASS if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
        sound_path = os.path.join(base_dir, "static", "sounds", f"{name}.wav")
        if os.path.exists(sound_path):
            winsound.PlaySound(sound_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
    except Exception:
        pass


class DictationAgent:
    """Orchestrates hotkey events, audio capture, transcription, and paste pipeline."""

    def __init__(self):
        self.hotkey = {"alt", "shift"}
        self.context_hotkey = {"ctrl", "shift"}
        self.keys_pressed = set()
        self.is_recording = False
        self._is_context_recording = False
        self._voice_edit_selection = ""
        self._preset_hotkey_latched = False
        self._is_ai_editing = False
        self._last_voice_edit: Optional[dict[str, str]] = None
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
        self.context_aware_dictation = False
        self.app_aware_formatting = True
        self.output_mode = "type"
        self.dictation_trigger_mode = "hold"
        self.silence_auto_stop = True
        self.silence_timeout_seconds = 3.0
        self.silence_threshold = 0.01
        self._recording_lock = threading.RLock()
        self._stop_requested = False
        self._cancel_requested = False
        self._silence_monitor_thread = None
        self._active_app_context = None

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
        self.audio = AudioCapture(sample_rate=16000, chunk_size=1024, on_volume=self.overlay.update_volume)
        self.transcriber = TranscriptionService(on_status=self.overlay.show_notification)
        self._listener = None
        self._running = False

        self._load_config()

    def _load_config(self) -> None:
        if self.credential_store.available:
            self.api_key = self.credential_store.get_api_key()

        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    if "key1" in cfg and "key2" in cfg:
                        self.set_hotkey(cfg["key1"], cfg["key2"])
                    if "context_key1" in cfg and "context_key2" in cfg:
                        self.set_context_hotkey(cfg["context_key1"], cfg["context_key2"])
                    if "ai_presets" in cfg:
                        self.ai_presets = cfg["ai_presets"]
                    if not self.api_key and "api_key" in cfg and cfg["api_key"]:
                        self.set_api_key(cfg["api_key"])
                    self.context_prompt = cfg.get("context_prompt", DEFAULT_CONTEXT_PROMPT)
                    self.main_dictation_ai = cfg.get("main_dictation_ai", False)
                    self.run_at_startup = cfg.get("run_at_startup", False)
                    self.use_local_llm = cfg.get("use_local_llm", False)
                    self.transcription_engine = cfg.get("transcription_engine", "local")
                    self.custom_vocabulary = cfg.get("custom_vocabulary", "")
                    self.writing_style = cfg.get("writing_style", "natural")
                    self.text_replacements = cfg.get("text_replacements", "")
                    self.voice_snippets = cfg.get("voice_snippets", "")
                    self.history_retention_days = max(0, int(cfg.get("history_retention_days", 30)))
                    self.onboarding_complete = bool(cfg.get("onboarding_complete", False))
                    self.context_aware_dictation = cfg.get("context_aware_dictation", False)
                    self.app_aware_formatting = bool(cfg.get("app_aware_formatting", True))
                    self.output_mode = cfg.get("output_mode", "type")
                    self.dictation_language = cfg.get("dictation_language", "auto")
                    mode = cfg.get("dictation_trigger_mode", "hold")
                    self.dictation_trigger_mode = mode if mode in {"hold", "toggle"} else "hold"
                    self.silence_auto_stop = bool(cfg.get("silence_auto_stop", True))
                    self.silence_timeout_seconds = max(3.0, float(cfg.get("silence_timeout_seconds", 3.0)))
                    self.silence_threshold = max(0.001, float(cfg.get("silence_threshold", 0.01)))
            except Exception as e:
                log(f"Failed to load config: {e}")

        repair_preset_conflicts(self.ai_presets, self.hotkey, self.context_hotkey)

    def save_config(self) -> None:
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
            "context_aware_dictation": self.context_aware_dictation,
            "app_aware_formatting": self.app_aware_formatting,
            "output_mode": self.output_mode,
            "dictation_language": self.dictation_language,
            "dictation_trigger_mode": self.dictation_trigger_mode,
            "silence_auto_stop": self.silence_auto_stop,
            "silence_timeout_seconds": self.silence_timeout_seconds,
            "silence_threshold": self.silence_threshold,
        }
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=4)
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

    def start(self) -> None:
        self._running = True
        threading.Thread(target=self.overlay.start, daemon=True).start()
        self.audio.start()

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

    def set_hotkey(self, key1: str, key2: str) -> None:
        k1 = MODIFIER_MAP.get(key1.lower(), key1.lower())
        k2 = MODIFIER_MAP.get(key2.lower(), key2.lower())
        self.hotkey = {k1, k2}
        self.keys_pressed.clear()
        log(f"Hotkey set to: {self.hotkey}")

    def set_context_hotkey(self, key1: str, key2: str) -> None:
        k1 = MODIFIER_MAP.get(key1.lower(), key1.lower())
        k2 = MODIFIER_MAP.get(key2.lower(), key2.lower())
        self.context_hotkey = {k1, k2}
        self.keys_pressed.clear()
        log(f"Context hotkey set to: {self.context_hotkey}")

    def _on_press(self, key) -> None:
        if self.is_paused:
            return

        try:
            n = normalize_key(key)
            if n:
                self.keys_pressed.add(n)
        except Exception:
            return

        if n == "esc" and self.is_recording:
            self._cancel_recording()
            return

        if self.context_hotkey.issubset(self.keys_pressed) and self.is_recording and self._is_context_recording:
            if self.dictation_trigger_mode == "toggle":
                self._stop_recording()
            return

        if self.hotkey.issubset(self.keys_pressed) and self.is_recording and not self._is_context_recording:
            if self.dictation_trigger_mode == "toggle":
                self._stop_recording()
            return

        if self.context_hotkey.issubset(self.keys_pressed) and not self.is_recording and self.status == "idle":
            self._is_context_recording = True
            self._start_recording()
            return

        if self.hotkey.issubset(self.keys_pressed) and not self.is_recording and self.status == "idle":
            self._is_context_recording = False
            self._voice_edit_selection = self._capture_selected_text()
            self._start_recording()
            return

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

    def _start_recording(self) -> None:
        with self._recording_lock:
            if self.is_recording or self.status != "idle":
                return
            self.is_recording = True
            self._stop_requested = False
            self._cancel_requested = False
            self.status = "listening"
            self.overlay.set_state("listening")
            _play_sound("start")

            if self._is_context_recording:
                mode = "context_reply"
            elif self._voice_edit_selection:
                mode = "voice_edit"
            else:
                mode = "dictation"
            self._active_app_context = get_foreground_app_context() if self.app_aware_formatting else None
            metadata = {}
            if self._active_app_context:
                metadata = {
                    "process_name": self._active_app_context.process_name,
                    "window_title": self._active_app_context.window_title,
                    "app_category": self._active_app_context.category,
                }
            try:
                self._active_history_id = self.history.create(
                    mode=mode,
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
            voice_edit_selection = self._voice_edit_selection
            app_context = self._active_app_context

        self._process_recording(raw_audio, history_id, is_context_recording, voice_edit_selection, app_context)

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
            self._voice_edit_selection = ""
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
        voice_edit_selection: str = "",
        app_context: Any = None,
    ) -> None:
        def process():
            recovery_audio_path = None
            try:
                if not raw_audio:
                    log("No audio captured.")
                    if history_id:
                        self.history.fail(history_id, "No audio was captured.", code="no_audio")
                    return

                secs = len(raw_audio) / (self.audio.sample_rate * 2)
                log(f"Captured {len(raw_audio)} bytes ({secs:.1f}s)")
                recovery_audio_path = None
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

                if not raw_text or not raw_text.strip():
                    log("No speech detected.")
                    if history_id:
                        self.history.fail(history_id, "No speech was detected.", code="no_speech")
                    return

                text = raw_text.strip()
                if voice_edit_selection:
                    if history_id:
                        self.history.transition(history_id, DictationStatus.POLISHING, raw_text=text)
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

                    if self._paste_voice_edit(voice_edit_selection, edited_text):
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

                use_ai = is_context_recording or getattr(self, "main_dictation_ai", False)

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
                        app_instruction=app_context.instruction if app_context else "",
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
                self._voice_edit_selection = ""
                self._active_app_context = None
                self.overlay.set_state("idle")

        threading.Thread(target=process, daemon=True).start()

    def _capture_selected_text(self) -> str:
        try:
            import pyautogui

            old_clipboard = safe_clipboard_get()
            safe_clipboard_set("")
            force_release_modifiers()
            time.sleep(0.05)

            copy_modifier = "command" if sys.platform == "darwin" else "ctrl"
            pyautogui.hotkey(copy_modifier, "c")

            selected_text = ""
            deadline = time.time() + 0.6
            while time.time() < deadline and not selected_text:
                time.sleep(0.05)
                selected_text = safe_clipboard_get().strip()

            safe_clipboard_set(old_clipboard)
            if selected_text:
                log("Selected text detected. Starting voice edit mode.")
            return selected_text
        except Exception as e:
            log(f"Selection detection failed: {e}")
            return ""

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

    def _paste_voice_edit(self, original_text: str, edited_text: str) -> bool:
        try:
            import pyautogui

            old_clipboard = safe_clipboard_get()
            if not safe_clipboard_set(edited_text):
                return False
            force_release_modifiers()
            paste_modifier = "command" if sys.platform == "darwin" else "ctrl"
            pyautogui.hotkey(paste_modifier, "v")
            time.sleep(0.2)
            safe_clipboard_set(old_clipboard)
            self._last_voice_edit = {
                "original_text": original_text,
                "edited_text": edited_text,
                "created_at": str(time.time()),
            }
            log("Voice edit pasted.")
            return True
        except Exception as e:
            log(f"Voice edit paste error: {e}")
            return False

    def undo_last_voice_edit(self) -> bool:
        if not self._last_voice_edit:
            self.overlay.show_notification("No voice edit to undo")
            return False
        try:
            import pyautogui

            self.status = "ai_edit"
            self.overlay.set_state("ai_edit")
            force_release_modifiers()
            undo_modifier = "command" if sys.platform == "darwin" else "ctrl"
            pyautogui.hotkey(undo_modifier, "z")
            self.overlay.show_notification("Last voice edit undone")
            log("Undo last voice edit triggered.")
            return True
        except Exception as e:
            log(f"Undo voice edit error: {e}")
            self.overlay.show_error("Undo failed")
            return False
        finally:
            self.status = "idle"
            self.overlay.set_state("idle")

    def _trigger_ai_edit(self, prompt: str) -> None:
        self._is_ai_editing = True
        self.status = "ai_edit"
        _play_sound("start")
        self.overlay.set_state("ai_edit")
        log("AI Edit triggered on selected text...")

        try:
            import pyautogui

            wait_time = 0.0
            while self.keys_pressed and wait_time < 2.0:
                time.sleep(0.05)
                wait_time += 0.05
            self.keys_pressed.clear()

            force_release_modifiers()
            time.sleep(0.1)

            old_clipboard = safe_clipboard_get()
            safe_clipboard_set("")

            copy_modifier = "command" if sys.platform == "darwin" else "ctrl"
            pyautogui.hotkey(copy_modifier, "c")

            selected_text = ""
            deadline = time.time() + 1.5
            while time.time() < deadline and not selected_text:
                time.sleep(0.05)
                selected_text = safe_clipboard_get().strip()

            if not selected_text:
                log("No text selected or copy failed.")
                safe_clipboard_set(old_clipboard)
                return

            new_text = LLMService.enhance_with_llm(
                selected_text,
                prompt,
                api_key=self.api_key,
                use_local_llm=self.use_local_llm,
                on_error=self.overlay.show_error,
            )

            if new_text is None:
                log("AI Edit aborted due to error.")
                safe_clipboard_set(old_clipboard)
                return

            safe_clipboard_set(new_text)
            force_release_modifiers()

            paste_modifier = "command" if sys.platform == "darwin" else "ctrl"
            pyautogui.hotkey(paste_modifier, "v")

            time.sleep(0.3)
            safe_clipboard_set(old_clipboard)
            _play_sound("stop")
            log("AI Edit complete.")
        except Exception as e:
            log(f"AI Edit error: {e}")
        finally:
            self._is_ai_editing = False
            self.status = "idle"
            self.overlay.set_state("idle")

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
                return self.history.complete(job_id, final_text, raw_text=raw_text.strip(), audio_path="")
            self.history.fail(job_id, "Retry transcription returned empty text.", code="retry_empty")
            return self.history.get(job_id)
        except Exception as e:
            self.history.fail(job_id, f"Retry error: {e}", code="retry_failed")
            return self.history.get(job_id)

    def copy_history_item(self, job_id: Optional[str] = None) -> bool:
        item = self.history.get(job_id) if job_id else self.history.latest()
        if not item:
            return False
        text = (item.get("final_text") or item.get("raw_text") or "").strip()
        if not text:
            return False
        return safe_clipboard_set(text)

    def paste_history_item(self, job_id: Optional[str] = None) -> bool:
        if not self.copy_history_item(job_id):
            return False
        try:
            import pyautogui

            paste_modifier = "command" if sys.platform == "darwin" else "ctrl"
            pyautogui.hotkey(paste_modifier, "v")
            return True
        except Exception as e:
            log(f"History paste error: {e}")
            return False

    def _update_analytics(self, text: str) -> None:
        if not text:
            return
        words = len(text.split())
        analytics_file = os.path.expanduser("~/.voiceflow_analytics.json")
        try:
            if os.path.exists(analytics_file):
                with open(analytics_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = {"total_words": 0, "sessions": 0}
            data["total_words"] += words
            data["sessions"] += 1
            with open(analytics_file, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception as e:
            log(f"Failed to update analytics: {e}")

    def set_startup(self, enabled: bool) -> None:
        self.run_at_startup = enabled
        if getattr(sys, "frozen", False):
            path = f'"{sys.executable}"'
            exe_path = sys.executable
        else:
            python_exe = sys.executable
            if sys.platform == "win32" and python_exe.lower().endswith("python.exe"):
                python_exe = python_exe[:-10] + "pythonw.exe"
            path = f'"{python_exe}" "{os.path.abspath(sys.argv[0])}"'
            exe_path = f"{python_exe} {os.path.abspath(sys.argv[0])}"

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
                    winreg.SetValueEx(key, "VoiceFlow", 0, winreg.REG_SZ, path)
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
Exec={exe_path}
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
            "context_aware_dictation": self.context_aware_dictation,
            "app_aware_formatting": self.app_aware_formatting,
            "output_mode": self.output_mode,
            "dictation_language": self.dictation_language,
            "dictation_trigger_mode": self.dictation_trigger_mode,
            "silence_auto_stop": self.silence_auto_stop,
            "silence_timeout_seconds": self.silence_timeout_seconds,
            "silence_threshold": self.silence_threshold,
        }
