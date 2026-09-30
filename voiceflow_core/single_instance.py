"""Cross-platform single-instance mutex and window focus support."""

import os
import sys
from typing import Optional

ERROR_ALREADY_EXISTS = 183


class SingleInstance:
    """Ensures only a single instance of VoiceFlow runs at any time."""

    def __init__(self, app_id: str = "VoiceFlow_App_Mutex"):
        self.app_id = app_id
        self.is_running = False
        self._mutex_handle = None
        self._lock_file = None
        self._acquire()

    def _acquire(self) -> None:
        if sys.platform == "win32":
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                self._mutex_handle = kernel32.CreateMutexW(None, False, self.app_id)
                last_error = kernel32.GetLastError()
                if last_error == ERROR_ALREADY_EXISTS:
                    self.is_running = True
            except Exception:
                self.is_running = False
        else:
            try:
                import fcntl
                lock_path = os.path.expanduser(f"~/.voiceflow_{self.app_id}.lock")
                self._lock_file = open(lock_path, "w")
                fcntl.lockf(self._lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.is_running = False
            except (IOError, OSError):
                self.is_running = True

    def release(self) -> None:
        if sys.platform == "win32" and self._mutex_handle:
            try:
                import ctypes
                ctypes.windll.kernel32.CloseHandle(self._mutex_handle)
            except Exception:
                pass
            self._mutex_handle = None
        elif self._lock_file:
            try:
                self._lock_file.close()
            except Exception:
                pass
            self._lock_file = None

    def focus_existing_window(self, window_title: str = "VoiceFlow Dashboard") -> bool:
        """Attempt to bring the already running VoiceFlow window to the foreground."""
        if sys.platform == "win32":
            try:
                import ctypes
                user32 = ctypes.windll.user32
                hwnd = user32.FindWindowW(None, window_title)
                if hwnd:
                    # 9 = SW_RESTORE
                    user32.ShowWindow(hwnd, 9)
                    user32.SetForegroundWindow(hwnd)
                    return True
            except Exception:
                pass
        return False
