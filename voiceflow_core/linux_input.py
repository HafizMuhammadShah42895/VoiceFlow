"""Keyboard access that works on Linux Wayland sessions.

Wayland does not let one app see keys typed into another app, and it ignores
X11 fake key presses (what pynput's and pyautogui's X11 backends use). The
kernel input layer works everywhere, so on Wayland VoiceFlow:

* reads keyboards from ``/dev/input/event*`` with ``evdev`` (global shortcuts), and
* sends Ctrl+C / Ctrl+V / Ctrl+Z through a ``/dev/uinput`` virtual keyboard.

Both need the user to be in the ``input`` group (and a udev rule for uinput);
:func:`detect_platform_issues` tells the dashboard what to show when they are not.
"""

from __future__ import annotations

import os
import select
import shutil
import string
import sys
import threading
import time
from typing import Callable, Optional

from voiceflow_core.safe_logging import log

try:  # Linux-only dependency
    import evdev
    from evdev import ecodes
except Exception:  # pragma: no cover - evdev is absent on Windows/macOS
    evdev = None
    ecodes = None

VIRTUAL_KEYBOARD_NAME = "VoiceFlow virtual keyboard"
DEVICE_RESCAN_SECONDS = 3.0

SETUP_COMMANDS = [
    "sudo usermod -aG input $USER",
    "echo 'KERNEL==\"uinput\", GROUP=\"input\", MODE=\"0660\", OPTIONS+=\"static_node=uinput\"' "
    "| sudo tee /etc/udev/rules.d/99-voiceflow-uinput.rules",
    "echo uinput | sudo tee /etc/modules-load.d/voiceflow-uinput.conf",
    "sudo modprobe uinput && sudo udevadm control --reload-rules && sudo udevadm trigger",
]


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def is_wayland() -> bool:
    return is_linux() and (
        os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY"))
    )


class EvdevKey:
    """Minimal stand-in for a pynput key, understood by ``normalize_key``."""

    __slots__ = ("name", "char")

    def __init__(self, name: Optional[str] = None, char: Optional[str] = None):
        self.name = name
        self.char = char

    def __repr__(self) -> str:
        return f"EvdevKey({self.char or self.name!r})"


def _key_table() -> dict[int, EvdevKey]:
    if ecodes is None:
        return {}
    names = {
        "KEY_LEFTALT": "alt_l", "KEY_RIGHTALT": "alt_r",
        "KEY_LEFTSHIFT": "shift_l", "KEY_RIGHTSHIFT": "shift_r",
        "KEY_LEFTCTRL": "ctrl_l", "KEY_RIGHTCTRL": "ctrl_r",
        "KEY_LEFTMETA": "cmd_l", "KEY_RIGHTMETA": "cmd_r",
        "KEY_SPACE": "space", "KEY_ESC": "esc", "KEY_ENTER": "enter",
        "KEY_TAB": "tab", "KEY_BACKSPACE": "backspace",
    }
    table = {getattr(ecodes, code): EvdevKey(name=name) for code, name in names.items()}
    for number in range(1, 13):
        table[getattr(ecodes, f"KEY_F{number}")] = EvdevKey(name=f"f{number}")
    for char in string.ascii_lowercase + string.digits:
        table[getattr(ecodes, f"KEY_{char.upper()}")] = EvdevKey(char=char)
    return table


def _modifier_codes() -> set[int]:
    if ecodes is None:
        return set()
    return {
        ecodes.KEY_LEFTALT, ecodes.KEY_RIGHTALT, ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT,
        ecodes.KEY_LEFTCTRL, ecodes.KEY_RIGHTCTRL, ecodes.KEY_LEFTMETA, ecodes.KEY_RIGHTMETA,
    }


def _is_keyboard(device) -> bool:
    if device.name == VIRTUAL_KEYBOARD_NAME:
        return False
    keys = device.capabilities().get(ecodes.EV_KEY, [])
    return ecodes.KEY_A in keys and ecodes.KEY_LEFTSHIFT in keys


def keyboards_readable() -> bool:
    """True when at least one physical keyboard can be read (user is in ``input``)."""
    if evdev is None:
        return False
    for path in evdev.list_devices():
        try:
            device = evdev.InputDevice(path)
        except OSError:
            continue
        try:
            if _is_keyboard(device):
                return True
        finally:
            device.close()
    return False


def uinput_writable() -> bool:
    return evdev is not None and any(
        os.path.exists(path) and os.access(path, os.W_OK) for path in ("/dev/uinput", "/dev/input/uinput")
    )


def should_use_evdev_listener() -> bool:
    return is_wayland() and keyboards_readable()


def should_use_virtual_keyboard() -> bool:
    return is_wayland() and uinput_writable()


class EvdevKeyboardListener:
    """Global key listener over every keyboard device; mirrors pynput's Listener API."""

    def __init__(self, on_press: Callable, on_release: Callable):
        self.on_press = on_press
        self.on_release = on_release
        self._keys = _key_table()
        self._devices: dict[str, object] = {}
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, name="evdev-keyboard", daemon=True)
        self._thread.start()
        log("Listening for shortcuts through the Linux input devices (Wayland mode).")

    def stop(self) -> None:
        self._running = False
        with self._lock:
            for device in self._devices.values():
                try:
                    device.close()
                except OSError:
                    pass
            self._devices.clear()

    def held_modifiers(self) -> set[int]:
        """Modifier keys physically held right now, according to the kernel."""
        held: set[int] = set()
        with self._lock:
            for device in list(self._devices.values()):
                try:
                    held.update(device.active_keys())
                except OSError:
                    pass
        return held & _modifier_codes()

    def handle_event(self, code: int, value: int) -> None:
        """Translate one key event (value 1 = down, 2 = auto-repeat, 0 = up)."""
        key = self._keys.get(code)
        if key is None:
            return
        try:
            if value in (1, 2):
                self.on_press(key)
            elif value == 0:
                self.on_release(key)
        except Exception as e:
            log(f"Shortcut handler error: {e}")

    def _scan(self) -> None:
        for path in evdev.list_devices():
            if path in self._devices:
                continue
            try:
                device = evdev.InputDevice(path)
            except OSError:
                continue
            if _is_keyboard(device):
                with self._lock:
                    self._devices[path] = device
            else:
                device.close()

    def _run(self) -> None:
        last_scan = 0.0
        while self._running:
            if time.time() - last_scan > DEVICE_RESCAN_SECONDS:
                self._scan()  # also picks up keyboards plugged in later
                last_scan = time.time()
            with self._lock:
                devices = list(self._devices.values())
            if not devices:
                time.sleep(0.5)
                continue
            try:
                readable, _, _ = select.select(devices, [], [], 0.5)
            except (OSError, ValueError):
                readable = []
            for device in readable:
                try:
                    for event in device.read():
                        if event.type == ecodes.EV_KEY:
                            self.handle_event(event.code, event.value)
                except OSError:  # keyboard unplugged
                    with self._lock:
                        self._devices.pop(device.path, None)
                    try:
                        device.close()
                    except OSError:
                        pass


_active_listener: Optional[EvdevKeyboardListener] = None
_virtual_keyboard = None
_virtual_keyboard_lock = threading.Lock()


def set_active_listener(listener: Optional[EvdevKeyboardListener]) -> None:
    global _active_listener
    _active_listener = listener


def wait_for_modifiers_released(timeout: float = 1.0) -> None:
    """On Wayland a physically held Alt/Shift would merge with our Ctrl+V, and the
    compositor cannot be told to release it, so wait for the user to let go."""
    listener = _active_listener
    if listener is None:
        return
    deadline = time.time() + timeout
    while listener.held_modifiers() and time.time() < deadline:
        time.sleep(0.02)


def _virtual_keyboard_device():
    global _virtual_keyboard
    with _virtual_keyboard_lock:
        if _virtual_keyboard is None:
            keys = [
                ecodes.KEY_LEFTCTRL, ecodes.KEY_LEFTSHIFT, ecodes.KEY_LEFTALT, ecodes.KEY_LEFTMETA,
                ecodes.KEY_C, ecodes.KEY_V, ecodes.KEY_Z,
            ]
            _virtual_keyboard = evdev.UInput({ecodes.EV_KEY: keys}, name=VIRTUAL_KEYBOARD_NAME)
            time.sleep(0.25)  # give the compositor time to register the new device
        return _virtual_keyboard


def send_shortcut(key: str, shift: bool = False) -> None:
    """Press Ctrl(+Shift)+<key> through the virtual keyboard."""
    wait_for_modifiers_released()
    device = _virtual_keyboard_device()
    codes = [ecodes.KEY_LEFTCTRL] + ([ecodes.KEY_LEFTSHIFT] if shift else []) + [getattr(ecodes, f"KEY_{key.upper()}")]
    for code in codes:
        device.write(ecodes.EV_KEY, code, 1)
        device.syn()
        time.sleep(0.01)
    for code in reversed(codes):
        device.write(ecodes.EV_KEY, code, 0)
        device.syn()
        time.sleep(0.01)


def _compositor_reports_active_window() -> bool:
    return bool(
        (os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") and shutil.which("hyprctl"))
        or (os.environ.get("SWAYSOCK") and shutil.which("swaymsg"))
    )


def detect_platform_issues() -> list[dict]:
    """Linux setup problems to show in the dashboard, most important first."""
    if not is_linux():
        return []
    issues: list[dict] = []
    wayland = is_wayland()

    if wayland:
        if evdev is None:
            issues.append({
                "id": "evdev_missing",
                "level": "warning",
                "title": "Shortcuts and typing cannot work on Wayland yet",
                "detail": "The Python package 'evdev' is not installed. Install it, then restart VoiceFlow.",
                "commands": ["python3 -m pip install evdev"],
            })
        else:
            missing = []
            if not keyboards_readable():
                missing.append("read the keyboard (so your shortcut works in every app)")
            if not uinput_writable():
                missing.append("use a virtual keyboard (so VoiceFlow can paste into Wayland apps)")
            if missing:
                issues.append({
                    "id": "wayland_input_access",
                    "level": "warning",
                    "title": "One-time Linux setup needed for Wayland",
                    "detail": (
                        "Wayland blocks apps from seeing or sending keys for other apps, so VoiceFlow needs "
                        "permission to " + " and to ".join(missing) + ". Run these commands, then log out and back in. "
                        "Note: members of the 'input' group can read all keyboard input."
                    ),
                    "commands": SETUP_COMMANDS,
                })
        if not _compositor_reports_active_window():
            issues.append({
                "id": "wayland_app_detection",
                "level": "info",
                "title": "Per-app features are limited on this desktop",
                "detail": (
                    "GNOME and KDE on Wayland do not tell apps which window is focused, so Writing Profiles, "
                    "app-aware formatting and voice edit (select text, then dictate) are turned off. "
                    "They work on X11, Sway and Hyprland."
                ),
                "commands": [],
            })

    clipboard_tool = "wl-copy" if wayland else "xclip"
    if not (shutil.which(clipboard_tool) or shutil.which("xsel") or shutil.which("xclip")):
        issues.append({
            "id": "clipboard_tool",
            "level": "info",
            "title": "Install a clipboard helper for the most reliable pasting",
            "detail": "VoiceFlow has a built-in fallback, but the standard clipboard tool is more reliable.",
            "commands": ["sudo apt install wl-clipboard" if wayland else "sudo apt install xclip"],
        })
    return issues
