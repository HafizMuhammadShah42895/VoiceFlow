"""Foreground application detection and app-aware writing rules."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

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
        """
        return (
            self.category not in SELECTION_CAPTURE_UNSAFE_CATEGORIES
            and self.process_name not in SELECTION_CAPTURE_UNSAFE_PROCESSES
        )


SELECTION_CAPTURE_UNSAFE_CATEGORIES = {"terminal", "code"}
# Excel copies the active cell when nothing is selected.
SELECTION_CAPTURE_UNSAFE_PROCESSES = {"excel.exe"}

APP_RULES = {
    "email": {
        "processes": {"outlook.exe", "thunderbird.exe", "olk.exe", "hxn.exe"},
        "instruction": (
            "The user is writing in an email app. Use a clear, professional email tone. "
            "Prefer complete sentences and clean paragraph structure."
        ),
    },
    "chat": {
        "processes": {"slack.exe", "teams.exe", "ms-teams.exe", "discord.exe", "whatsapp.exe", "telegram.exe"},
        "instruction": (
            "The user is writing in a workplace chat app. Keep it short, direct, friendly, and conversational. "
            "Do not add email greetings or sign-offs."
        ),
    },
    "terminal": {
        "processes": {"windowsterminal.exe", "cmd.exe", "powershell.exe", "pwsh.exe", "wt.exe", "conhost.exe"},
        "instruction": (
            "The user is writing in a terminal. Preserve commands literally. Do not improve grammar, "
            "do not change capitalization, do not alter flags, paths, punctuation, quotes, or code-like text."
        ),
    },
    "code": {
        "processes": {"code.exe", "cursor.exe", "devenv.exe", "pycharm64.exe", "webstorm64.exe", "idea64.exe"},
        "instruction": (
            "The user is writing in a code editor. Preserve code-like tokens such as snake_case, camelCase, "
            "file names, paths, commands, backticks, punctuation, and indentation."
        ),
    },
    "browser": {
        "processes": {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe"},
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
