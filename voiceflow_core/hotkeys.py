"""Hotkey normalization, conflict detection, and listener coordination."""

import sys
from typing import Iterable, Optional

from voiceflow_core.safe_logging import log

MODIFIER_MAP = {
    "alt_l": "alt",
    "alt_r": "alt",
    "alt": "alt",
    "shift_l": "shift",
    "shift_r": "shift",
    "shift": "shift",
    "ctrl_l": "ctrl",
    "ctrl_r": "ctrl",
    "ctrl": "ctrl",
    "cmd_l": "cmd",
    "cmd_r": "cmd",
    "cmd": "cmd",
}


def normalize_key(key) -> Optional[str]:
    """Convert a pynput key event to a canonical string name."""
    name = None
    if hasattr(key, "char") and key.char:
        name = key.char.lower()
    elif hasattr(key, "name"):
        name = key.name.lower()
    return MODIFIER_MAP.get(name, name) if name else None


def hotkey_signature(keys) -> frozenset[str]:
    """Return a normalized set of keys for comparison."""
    return frozenset(
        MODIFIER_MAP.get(str(k).lower(), str(k).lower())
        for k in (keys or [])
        if k
    )


def repair_preset_conflicts(
    ai_presets: list[dict],
    hotkey: set[str],
    context_hotkey: set[str],
) -> None:
    """Repair saved preset shortcuts that conflict with main dictation shortcuts."""
    reserved = {frozenset(hotkey), frozenset(context_hotkey)}
    used = set()
    fallbacks = [
        ("ctrl", "space"),
        ("alt", "space"),
        ("shift", "space"),
        ("ctrl", "alt"),
    ]

    for preset in ai_presets:
        signature = hotkey_signature(preset.get("hotkeys", []))
        windows_key_is_unreliable = sys.platform == "win32" and "cmd" in signature
        if len(signature) < 2 or signature in reserved or signature in used or windows_key_is_unreliable:
            replacement = next(
                (
                    candidate
                    for candidate in fallbacks
                    if frozenset(candidate) not in reserved and frozenset(candidate) not in used
                ),
                None,
            )
            if replacement:
                preset["hotkeys"] = list(replacement)
                signature = frozenset(replacement)
                log(f"Changed conflicting preset hotkey for '{preset.get('name', 'Preset')}'.")
        used.add(signature)


def preset_for_keys(ai_presets: list[dict], keys_pressed: Iterable[str]) -> Optional[dict]:
    """Return the preset whose shortcut is held, preferring the most specific one."""
    pressed = set(keys_pressed)
    best = None
    best_size = 0
    for preset in ai_presets or []:
        if not isinstance(preset, dict):
            continue
        signature = hotkey_signature(preset.get("hotkeys", []))
        if len(signature) >= 2 and signature.issubset(pressed) and len(signature) > best_size:
            best = preset
            best_size = len(signature)
    return best
