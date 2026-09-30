"""Safe clipboard manipulation and text typing simulation."""

import sys
import time
from typing import Optional

from voiceflow_core.safe_logging import log


def safe_clipboard_get() -> str:
    """Retrieve clipboard text reliably across Windows, macOS, and Linux."""
    try:
        import pyperclip
        return pyperclip.paste()
    except Exception:
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            result = root.clipboard_get()
            root.destroy()
            return result
        except Exception:
            return ""


def safe_clipboard_set(text: str) -> bool:
    """Set clipboard text reliably with fallback to Tkinter."""
    if not isinstance(text, str):
        return False
    try:
        import pyperclip
        pyperclip.copy(text)
        return True
    except Exception:
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            root.clipboard_clear()
            root.clipboard_append(text)
            root.update()
            root.destroy()
            return True
        except Exception:
            return False


def force_release_modifiers() -> None:
    """Force release modifier keys (Ctrl, Shift, Alt, Cmd) so they do not jam."""
    try:
        from pynput.keyboard import Controller, Key
        kb = Controller()
        for modifier in (Key.ctrl, Key.shift, Key.alt, Key.cmd):
            try:
                kb.release(modifier)
            except Exception:
                pass
    except Exception:
        pass


def type_or_paste(text: str, mode: str = "type") -> bool:
    """Type or copy the final transcript into the focused application."""
    try:
        import pyautogui

        if not safe_clipboard_set(text + " "):
            raise RuntimeError("Clipboard is unavailable")

        if mode == "type":
            paste_modifier = "command" if sys.platform == "darwin" else "ctrl"
            pyautogui.hotkey(paste_modifier, "v")
        return True
    except Exception as e:
        log(f"Type error: {e}")
        return False
