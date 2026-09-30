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


def get_foreground_app_context() -> AppContext:
    """Return the active app/process using local OS APIs only."""
    if sys.platform != "win32":
        return AppContext()

    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return AppContext()

        title_buffer = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
        window_title = title_buffer.value

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return AppContext(window_title=window_title)

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not handle:
            return AppContext(window_title=window_title)

        try:
            path_buffer = ctypes.create_unicode_buffer(4096)
            size = wintypes.DWORD(len(path_buffer))
            if not kernel32.QueryFullProcessImageNameW(handle, 0, path_buffer, ctypes.byref(size)):
                return AppContext(window_title=window_title)
            process_name = os.path.basename(path_buffer.value).lower()
        finally:
            kernel32.CloseHandle(handle)

        category = _category_for_process(process_name)
        instruction = APP_RULES.get(category, {}).get("instruction", "")
        return AppContext(
            process_name=process_name,
            window_title=window_title,
            category=category,
            instruction=instruction,
        )
    except Exception as e:
        log(f"Could not detect foreground app: {e}")
        return AppContext()
