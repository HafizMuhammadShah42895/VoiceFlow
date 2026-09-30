"""Floating HUD overlay for desktop dictation visual feedback."""

import os
import sys
import threading
import time

NOTIFICATION_SECONDS = 2.0
ERROR_SECONDS = 3.0
# Gap between the bottom of the HUD and the taskbar / bottom of the screen.
BOTTOM_MARGIN = 48

_STATE_ICONS = {
    "listening": ("◉", "#f38ba8"),
    "processing": ("⋯", "#f9e2af"),
    "ai_edit": ("✦", "#cba6f7"),
    "error": ("✕", "#f38ba8"),
    "notification": ("✓", "#a6e3a1"),
}
_TRANSIENT_STATES = {"notification", "error"}


def _enable_dpi_awareness() -> None:
    """Use real screen pixels before Tk measures the screen.

    pywebview switches the whole process to DPI-aware when the dashboard opens.
    If Tk started first it keeps its scaled measurements (e.g. 1536x864 on a
    1920x1080 screen at 125%), which put the HUD left of centre and too high.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _active_work_area():
    """Work area (screen minus taskbar) of the monitor the user is working on.

    Returns ``(left, top, right, bottom)`` in screen pixels, or None if unknown.
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.MonitorFromWindow.restype = wintypes.HMONITOR
        user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]

        MONITOR_DEFAULTTOPRIMARY = 1
        monitor = user32.MonitorFromWindow(user32.GetForegroundWindow(), MONITOR_DEFAULTTOPRIMARY)
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return None
        work = info.rcWork
        return work.left, work.top, work.right, work.bottom
    except Exception:
        return None


class AnimatedGIF:
    def __init__(self, path: str):
        self.frames = []
        try:
            import tkinter as tk
            if not os.path.exists(path):
                return
            idx = 0
            while True:
                frame = tk.PhotoImage(file=path, format=f"gif -index {idx}")
                self.frames.append(frame)
                idx += 1
        except Exception:
            pass

    def get_frame(self, index: int):
        if not self.frames:
            return None
        return self.frames[(index // 2) % len(self.frames)]


class FloatingOverlay:
    """Tk HUD. State setters may be called from any thread; only the Tk thread draws.

    Notifications and errors stay visible for their full duration. A request to
    go idle while one is showing is deferred until it expires, so a message is
    not wiped out by the pipeline finishing immediately afterwards.
    """

    def __init__(self):
        self.root = None
        self.label = None
        self.current_state = "idle"
        self.message_text = ""
        self.transient_end_time = 0.0
        self._resume_state = "idle"
        self.gifs = {}
        self.frame_count = 0
        self._rendered = None
        self._visible = False
        self._work_area = None
        self._position = None
        self._ui_thread = None

    def start(self) -> None:
        import tkinter as tk

        _enable_dpi_awareness()
        self._ui_thread = threading.current_thread()
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.95)
        self.root.configure(bg="#18181b")

        if getattr(sys, "frozen", False):
            base_dir = sys._MEIPASS
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        img_dir = os.path.join(base_dir, "static", "img")

        # Optional animated states; the icon glyphs are used when a GIF is absent.
        self.gifs = {
            "listening": AnimatedGIF(os.path.join(img_dir, "listening.gif")),
            "processing": AnimatedGIF(os.path.join(img_dir, "processing.gif")),
            "ai_edit": AnimatedGIF(os.path.join(img_dir, "ai.gif")),
            "notification": AnimatedGIF(os.path.join(img_dir, "success.gif")),
            "error": AnimatedGIF(os.path.join(img_dir, "error.gif")),
        }

        self.label = tk.Label(
            self.root,
            text="",
            font=("Segoe UI Emoji", 24),
            fg="#f4f4f5",
            bg="#18181b",
            padx=15,
            pady=8,
            justify="center",
            compound="left",
        )
        self.label.pack()

        self.root.withdraw()
        self.update_loop()
        self.root.mainloop()

    def call_in_ui(self, func, timeout: float = 1.0):
        """Run ``func(root)`` on the Tk thread and return its result.

        Tk is not thread-safe, so other threads (e.g. the clipboard fallback)
        must go through here.
        """
        root = self.root
        if root is None:
            raise RuntimeError("Overlay is not running")
        if threading.current_thread() is self._ui_thread:
            return func(root)
        done = threading.Event()
        result: dict = {}

        def task():
            try:
                result["value"] = func(root)
            except Exception as e:
                result["error"] = e
            finally:
                done.set()

        root.after(0, task)
        if not done.wait(timeout):
            raise TimeoutError("Overlay did not respond")
        if "error" in result:
            raise result["error"]
        return result.get("value")

    def update_loop(self) -> None:
        self.frame_count += 1

        if self.current_state in _TRANSIENT_STATES and time.time() > self.transient_end_time:
            self.current_state = self._resume_state
            self.message_text = ""

        state = self.current_state
        if state == "idle":
            self._rendered = None
            if self.root and self._visible:
                self.root.withdraw()
                self._visible = False
        else:
            self._render(state)
            self._show_at_bottom_center()

        if self.root:
            self.root.after(50, self.update_loop)

    def _render(self, state: str) -> None:
        icon, color = _STATE_ICONS.get(state, ("", "#f4f4f5"))
        message = self.message_text if state in _TRANSIENT_STATES else ""
        gif = self.gifs.get(state)
        frame = gif.get_frame(self.frame_count) if gif else None

        if message:
            text = message if frame else f"{icon}  {message}"
            font = ("Segoe UI", 13)
        else:
            text = "" if frame else icon
            font = ("Segoe UI Emoji", 24)

        key = (state, text, id(frame))
        if key == self._rendered:
            return
        self._rendered = key
        self.label.config(image=frame or "", text=text, fg=color, font=font)

    def _show_at_bottom_center(self) -> None:
        """Place the HUD centred just above the taskbar of the active monitor."""
        if not self.root:
            return
        self.root.update_idletasks()
        # Requested size is correct even before the window is first drawn,
        # unlike winfo_width(), which reports 1 until then.
        width = self.root.winfo_reqwidth()
        height = self.root.winfo_reqheight()

        if not self._visible:
            # Pick the monitor once per appearance so the HUD never jumps around.
            self._work_area = _active_work_area() or (
                0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()
            )
        left, top, right, bottom = self._work_area
        x = left + (right - left - width) // 2
        y = max(top, bottom - height - BOTTOM_MARGIN)

        if (x, y, width, height) != self._position:
            self._position = (x, y, width, height)
            self.root.geometry(f"+{x}+{y}")
        if not self._visible:
            self.root.deiconify()
            self.root.lift()
            self._visible = True

    def _transient_active(self) -> bool:
        return self.current_state in _TRANSIENT_STATES and time.time() <= self.transient_end_time

    def set_state(self, state: str) -> None:
        if state == "idle" and self._transient_active():
            self._resume_state = "idle"
            return
        self._resume_state = "idle"
        self.message_text = ""
        self.current_state = state

    def _show_transient(self, state: str, message: str, seconds: float) -> None:
        if self.current_state not in _TRANSIENT_STATES:
            self._resume_state = self.current_state
        self.message_text = message
        self.transient_end_time = time.time() + seconds
        self.current_state = state

    def show_error(self, message: str) -> None:
        self._show_transient("error", message, ERROR_SECONDS)

    def show_notification(self, message: str) -> None:
        self._show_transient("notification", message, NOTIFICATION_SECONDS)
