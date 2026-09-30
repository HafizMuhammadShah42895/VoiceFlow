"""Foreground application detection and app-aware writing rules."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional

from voiceflow_core.safe_logging import log


@dataclass(frozen=True)
class AppContext:
    process_name: str = ""
    window_title: str = ""
    category: str = "default"
    instruction: str = ""
    window_handle: int = 0

    @property
    def allows_selection_capture(self) -> bool:
        """Whether sending Ctrl+C to detect a selection is harmless in this app.

        Terminals treat Ctrl+C as an interrupt, and code editors copy the whole
        current line when nothing is selected, so voice edit is skipped there.
        On Linux the focused app is often unknown (GNOME/KDE on Wayland), and an
        unknown app could be a terminal, so it is never probed.
        """
        if sys.platform.startswith("linux") and not self.process_name:
            return False
        return (
            self.category not in SELECTION_CAPTURE_UNSAFE_CATEGORIES
            and self.process_name not in SELECTION_CAPTURE_UNSAFE_PROCESSES
        )


SELECTION_CAPTURE_UNSAFE_CATEGORIES = {"terminal", "code"}
# Excel copies the active cell when nothing is selected.
SELECTION_CAPTURE_UNSAFE_PROCESSES = {"excel.exe"}

APP_RULES = {
    "email": {
        "processes": {"outlook.exe", "thunderbird.exe", "olk.exe", "hxn.exe", "thunderbird", "evolution", "geary"},
        "instruction": (
            "The user is writing in an email app. Use a clear, professional email tone. "
            "Prefer complete sentences and clean paragraph structure."
        ),
    },
    "chat": {
        "processes": {
            "slack.exe", "teams.exe", "ms-teams.exe", "discord.exe", "whatsapp.exe", "telegram.exe",
            "slack", "discord", "teams-for-linux", "telegram-desktop", "signal-desktop", "element-desktop",
        },
        "instruction": (
            "The user is writing in a workplace chat app. Keep it short, direct, friendly, and conversational. "
            "Do not add email greetings or sign-offs."
        ),
    },
    "terminal": {
        "processes": {
            "windowsterminal.exe", "cmd.exe", "powershell.exe", "pwsh.exe", "wt.exe", "conhost.exe",
            "gnome-terminal-server", "gnome-terminal", "kgx", "ptyxis", "ptyxis-agent", "konsole", "kitty",
            "alacritty", "wezterm-gui", "foot", "footclient", "xterm", "uxterm", "urxvt", "tilix",
            "terminator", "xfce4-terminal", "mate-terminal", "lxterminal", "qterminal", "ghostty", "st",
        },
        "instruction": (
            "The user is writing in a terminal. Preserve commands literally. Do not improve grammar, "
            "do not change capitalization, do not alter flags, paths, punctuation, quotes, or code-like text."
        ),
    },
    "code": {
        "processes": {
            "code.exe", "cursor.exe", "devenv.exe", "pycharm64.exe", "webstorm64.exe", "idea64.exe",
            "code", "code-oss", "codium", "cursor", "pycharm", "idea", "webstorm", "sublime_text", "zed",
        },
        "instruction": (
            "The user is writing in a code editor. Preserve code-like tokens such as snake_case, camelCase, "
            "file names, paths, commands, backticks, punctuation, and indentation."
        ),
    },
    "browser": {
        "processes": {
            "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe",
            "chrome", "google-chrome", "chromium", "chromium-browser", "firefox", "firefox-bin",
            "brave", "brave-browser", "opera", "vivaldi-bin", "microsoft-edge", "msedge",
        },
        "instruction": (
            "The user is writing in a browser. Use a balanced, natural style unless the text clearly looks like "
            "chat, email, code, or a form field."
        ),
    },
}


def _category_for_process(process_name: str) -> str:
    name = (process_name or "").lower()
    for category, rule in APP_RULES.items():
        if name in rule["processes"]:
            return category
    return "default"


# ------------------------------------------------------------------ Linux


def _run_json(command: list[str]):
    try:
        output = subprocess.run(command, capture_output=True, text=True, timeout=0.8, check=True).stdout
        return json.loads(output)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _linux_process_name(pid: Optional[int], fallback: str = "") -> str:
    """Executable name for a PID, e.g. 'gnome-terminal-server' or 'firefox'."""
    name = ""
    if pid:
        try:
            name = os.path.basename(os.readlink(f"/proc/{pid}/exe"))
        except OSError:
            try:
                with open(f"/proc/{pid}/comm", encoding="utf-8") as f:
                    name = f.read().strip()
            except OSError:
                name = ""
    # Sandboxed (Flatpak) apps report the sandbox helper; their window class is more useful.
    if not name or name in {"bwrap", "flatpak-bwrap"}:
        name = fallback
    return (name or "").lower()


def _sway_windows(node: dict, windows: list[dict]) -> None:
    if node.get("pid"):
        windows.append(node)
    for child in node.get("nodes", []) + node.get("floating_nodes", []):
        _sway_windows(child, windows)


def _x11_windows(active_only: bool) -> list[tuple[int, str, str]]:
    """(pid, title, wm_class) for the active X11 window, or for all client windows."""
    from Xlib import X, display as xdisplay

    connection = xdisplay.Display()
    try:
        root = connection.screen().root
        atom = connection.intern_atom("_NET_ACTIVE_WINDOW" if active_only else "_NET_CLIENT_LIST")
        prop = root.get_full_property(atom, X.AnyPropertyType)
        window_ids = [wid for wid in (prop.value if prop else []) if wid]
        results = []
        for wid in window_ids:
            window = connection.create_resource_object("window", wid)
            pid_prop = window.get_full_property(connection.intern_atom("_NET_WM_PID"), X.AnyPropertyType)
            name_prop = window.get_full_property(connection.intern_atom("_NET_WM_NAME"), X.AnyPropertyType)
            title = name_prop.value if name_prop else b""
            title = title.decode("utf-8", "replace") if isinstance(title, bytes) else str(title)
            # WM_CLASS is (instance, class); the class is the stable app name
            # (e.g. Firefox's instance is "Navigator" but its class is "firefox").
            wm_class = window.get_wm_class() or ("", "")
            results.append((int(pid_prop.value[0]) if pid_prop else 0, title, wm_class[1] or wm_class[0] or ""))
        return results
    finally:
        connection.close()


def _linux_windows(active_only: bool) -> list[tuple[str, str]]:
    """(process_name, title) pairs from whichever source this desktop supports."""
    wayland = os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY"))
    try:
        if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
            data = _run_json(["hyprctl", "activewindow" if active_only else "clients", "-j"])
            clients = [data] if isinstance(data, dict) else (data or [])
            return [
                (_linux_process_name(c.get("pid"), c.get("class", "")), c.get("title", ""))
                for c in clients if c.get("pid")
            ]
        if os.environ.get("SWAYSOCK"):
            tree = _run_json(["swaymsg", "-t", "get_tree", "-r"]) or {}
            windows: list[dict] = []
            _sway_windows(tree, windows)
            if active_only:
                windows = [w for w in windows if w.get("focused")]
            return [
                (_linux_process_name(w.get("pid"), w.get("app_id") or ""), w.get("name") or "")
                for w in windows
            ]
        if wayland:
            # GNOME/KDE on Wayland only expose X11 (XWayland) windows; trusting
            # that would report a stale app while a native Wayland app is focused.
            return []
        if os.environ.get("DISPLAY"):
            return [
                (_linux_process_name(pid, wm_class), title)
                for pid, title, wm_class in _x11_windows(active_only)
            ]
    except Exception as e:
        log(f"Could not read Linux windows: {e}")
    return []


def _linux_foreground_app_context() -> AppContext:
    windows = _linux_windows(active_only=True)
    if not windows or not windows[0][0]:
        return AppContext()
    process_name, title = windows[0]
    category = _category_for_process(process_name)
    return AppContext(
        process_name=process_name,
        window_title=title,
        category=category,
        instruction=APP_RULES.get(category, {}).get("instruction", ""),
    )


def _linux_open_apps() -> list[dict[str, str]]:
    apps: dict[str, str] = {}
    for process_name, title in _linux_windows(active_only=False):
        if process_name and process_name not in {"voiceflow", "python3", "python"}:
            apps.setdefault(process_name, title)
    return [{"process_name": name, "window_title": title} for name, title in sorted(apps.items())]


# ---------------------------------------------------------------- Windows


def _window_title(user32, hwnd) -> str:
    import ctypes

    title_buffer = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
    return title_buffer.value


def _process_name_for_window(hwnd) -> str:
    """Return the lowercase executable name that owns a window, or ""."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return ""
    try:
        path_buffer = ctypes.create_unicode_buffer(4096)
        size = wintypes.DWORD(len(path_buffer))
        if not kernel32.QueryFullProcessImageNameW(handle, 0, path_buffer, ctypes.byref(size)):
            return ""
        return os.path.basename(path_buffer.value).lower()
    finally:
        kernel32.CloseHandle(handle)


def get_foreground_app_context() -> AppContext:
    """Return the active app/process using local OS APIs only."""
    if sys.platform.startswith("linux"):
        return _linux_foreground_app_context()
    if sys.platform != "win32":
        return AppContext()

    try:
        import ctypes

        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return AppContext()

        window_title = _window_title(user32, hwnd)
        process_name = _process_name_for_window(hwnd)
        if not process_name:
            return AppContext(window_title=window_title, window_handle=hwnd)

        category = _category_for_process(process_name)
        instruction = APP_RULES.get(category, {}).get("instruction", "")
        return AppContext(
            process_name=process_name,
            window_title=window_title,
            category=category,
            instruction=instruction,
            window_handle=hwnd,
        )
    except Exception as e:
        log(f"Could not detect foreground app: {e}")
        return AppContext()


def list_open_apps() -> list[dict[str, str]]:
    """List apps that currently have a visible window, for choosing profile apps.

    Returns one entry per executable: ``{"process_name": ..., "window_title": ...}``.
    Only window titles and executable names are read, never window contents.
    """
    if sys.platform.startswith("linux"):
        return _linux_open_apps()
    if sys.platform != "win32":
        return []

    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        own_pid = os.getpid()
        apps: dict[str, str] = {}

        EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def visit(hwnd, _lparam):
            try:
                if not user32.IsWindowVisible(hwnd) or user32.GetWindowTextLengthW(hwnd) == 0:
                    return True
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value == own_pid:
                    return True
                process_name = _process_name_for_window(hwnd)
                if process_name and process_name not in IGNORED_APP_PROCESSES:
                    apps.setdefault(process_name, _window_title(user32, hwnd))
            except Exception:
                pass
            return True

        user32.EnumWindows(EnumWindowsProc(visit), 0)
        return [
            {"process_name": name, "window_title": title}
            for name, title in sorted(apps.items())
        ]
    except Exception as e:
        log(f"Could not list open apps: {e}")
        return []


# Shell and system windows that are never dictation targets.
IGNORED_APP_PROCESSES = {
    "explorer.exe",
    "textinputhost.exe",
    "applicationframehost.exe",
    "shellexperiencehost.exe",
    "searchhost.exe",
    "startmenuexperiencehost.exe",
    "systemsettings.exe",
}


def focus_window(window_handle: int) -> bool:
    """Bring a previously captured window back to the foreground (Windows only)."""
    if sys.platform != "win32" or not window_handle:
        return False
    try:
        import ctypes

        user32 = ctypes.windll.user32
        if not user32.IsWindow(window_handle):
            return False
        return bool(user32.SetForegroundWindow(window_handle))
    except Exception as e:
        log(f"Could not focus window: {e}")
        return False
