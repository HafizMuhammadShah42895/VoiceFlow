"""Core services shared by the VoiceFlow desktop app and its UI."""

from .audio import AudioCapture
from .app_context import APP_RULES, AppContext, get_foreground_app_context
from .clipboard import force_release_modifiers, safe_clipboard_get, safe_clipboard_set, type_or_paste
from .history import DictationHistory, DictationStatus
from .hotkeys import MODIFIER_MAP, hotkey_signature, normalize_key, repair_preset_conflicts
from .llm import (
    DEFAULT_CONTEXT_PROMPT,
    DEFAULT_DICTATION_PROMPT,
    DEFAULT_PRESET_HOTKEY,
    DEFAULT_PROMPT,
    WRITING_STYLE_PROMPTS,
    LLMService,
)
from .overlay import AnimatedGIF, FloatingOverlay
from .safe_logging import log
from .secrets import CredentialStore
from .single_instance import SingleInstance
from .text_rules import apply_replacements, expand_snippet, parse_rules
from .transcription import TranscriptionService
from .tray import SystemTray
from .version import APP_VERSION

__all__ = [
    "AudioCapture",
    "AnimatedGIF",
    "APP_VERSION",
    "APP_RULES",
    "apply_replacements",
    "AppContext",
    "CredentialStore",
    "DEFAULT_CONTEXT_PROMPT",
    "DEFAULT_DICTATION_PROMPT",
    "DEFAULT_PRESET_HOTKEY",
    "DEFAULT_PROMPT",
    "DictationHistory",
    "DictationStatus",
    "expand_snippet",
    "FloatingOverlay",
    "force_release_modifiers",
    "get_foreground_app_context",
    "hotkey_signature",
    "LLMService",
    "log",
    "MODIFIER_MAP",
    "normalize_key",
    "parse_rules",
    "repair_preset_conflicts",
    "safe_clipboard_get",
    "safe_clipboard_set",
    "SingleInstance",
    "SystemTray",
    "TranscriptionService",
    "type_or_paste",
    "WRITING_STYLE_PROMPTS",
]
