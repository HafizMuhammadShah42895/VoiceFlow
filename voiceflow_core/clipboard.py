"""Safe clipboard manipulation and text typing simulation."""

import sys
import threading
import time
from typing import Any, Callable, Optional

from voiceflow_core import linux_input
from voiceflow_core.safe_logging import log

# How long to wait after Ctrl+V before restoring the user's clipboard. Apps read
# the clipboard when they process the queued keystroke, so restoring too early
# can paste the old contents instead of the transcript.
CLIPBOARD_RESTORE_DELAY = 0.6

# Runs a function against a long-lived Tk root (the overlay) in its own thread.
# Used when no clipboard tool is available: on X11 the clipboard belongs to the
# window that set it, so a temporary Tk window would lose it as soon as it closed.
_clipboard_host: Optional[Callable[[Callable[[Any], Any]], Any]] = None


def set_clipboard_host(host: Optional[Callable[[Callable[[Any], Any]], Any]]) -> None:
    global _clipboard_host
    _clipboard_host = host


def safe_clipboard_get() -> str:
    """Retrieve clipboard text reliably across Windows, macOS, and Linux."""
    try:
        import pyperclip
        return pyperclip.paste()
    except Exception:
        if _clipboard_host is not None:
            try:
                return _clipboard_host(lambda root: root.clipboard_get()) or ""
            except Exception:
                return ""
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
        if _clipboard_host is not None:
            try:
                def _set(root):
                    root.clipboard_clear()
                    root.clipboard_append(text)
                    root.update_idletasks()

                _clipboard_host(_set)
                return True
            except Exception:
                return False
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


def clipboard_sequence_number() -> Optional[int]:
    """Return the Windows clipboard change counter, or None where unsupported."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        user32 = ctypes.windll.user32
        user32.GetClipboardSequenceNumber.restype = ctypes.c_uint
        return int(user32.GetClipboardSequenceNumber())
    except Exception:
        return None


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


def send_shortcut(key: str, shift: bool = False) -> None:
    """Send Ctrl(+Shift)+<key> (Cmd on macOS) to the focused application.

    On Wayland X11 fake key presses never reach native apps, so the kernel
    virtual keyboard is used when VoiceFlow has permission for it.
    """
    if linux_input.should_use_virtual_keyboard():
        linux_input.send_shortcut(key, shift=shift)
        return

    import pyautogui

    modifier = "command" if sys.platform == "darwin" else "ctrl"
    pyautogui.hotkey(*([modifier] + (["shift"] if shift else []) + [key]))


def capture_selection(timeout: float = 0.5) -> str:
    """Copy the focused app's selected text without disturbing an unchanged clipboard.

    On Windows the clipboard sequence number tells us whether the copy produced
    anything, so when nothing is selected the user's clipboard (including images
    or files) is never touched.
    """
    try:
        force_release_modifiers()
        time.sleep(0.05)

        old_text = safe_clipboard_get()
        before = clipboard_sequence_number()
        if before is None:
            # No change-detection API: clear first so a successful copy is visible.
            safe_clipboard_set("")

        send_shortcut("c")

        selected = ""
        changed = before is None
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(0.03)
            if not changed:
                if clipboard_sequence_number() == before:
                    continue
                changed = True
            selected = safe_clipboard_get().strip()
            if selected:
                break

        if changed:
            safe_clipboard_set(old_text)
        return selected
    except Exception as e:
        log(f"Selection capture failed: {e}")
        return ""


def _restore_clipboard(previous_text: str, pasted_text: str, pasted_sequence: Optional[int]) -> None:
    """Put the user's clipboard back unless something else has replaced ours."""
    if pasted_sequence is not None:
        if clipboard_sequence_number() != pasted_sequence:
            return
    elif safe_clipboard_get() != pasted_text:
        return
    safe_clipboard_set(previous_text)


def paste_text(text: str, restore_clipboard: bool = True, wait: bool = False, terminal: bool = False) -> bool:
    """Paste text into the focused app through the clipboard.

    When ``restore_clipboard`` is set, the previous clipboard text is put back
    after a short delay. ``wait`` blocks until that restore has happened.
    ``terminal`` pastes with Ctrl+Shift+V on Linux, where terminals ignore Ctrl+V.
    """
    previous_text = safe_clipboard_get() if restore_clipboard else ""
    if not safe_clipboard_set(text):
        return False
    pasted_sequence = clipboard_sequence_number()

    try:
        force_release_modifiers()
        send_shortcut("v", shift=terminal and sys.platform.startswith("linux"))
    except Exception as e:
        log(f"Paste error: {e}")
        return False

    if restore_clipboard and previous_text:
        if wait:
            time.sleep(CLIPBOARD_RESTORE_DELAY)
            _restore_clipboard(previous_text, text, pasted_sequence)
        else:
            timer = threading.Timer(
                CLIPBOARD_RESTORE_DELAY,
                _restore_clipboard,
                args=(previous_text, text, pasted_sequence),
            )
            timer.daemon = True
            timer.start()
    return True


def type_or_paste(text: str, mode: str = "type", terminal: bool = False) -> bool:
    """Type or copy the final transcript into the focused application."""
    try:
        if mode == "type":
            # The trailing space keeps back-to-back dictations separated.
            return paste_text(text + " ", terminal=terminal)
        if not safe_clipboard_set(text):
            raise RuntimeError("Clipboard is unavailable")
        return True
    except Exception as e:
        log(f"Type error: {e}")
        return False
