"""Floating HUD overlay for desktop dictation visual feedback."""

import os
import sys
import time

NOTIFICATION_SECONDS = 2.0
ERROR_SECONDS = 3.0

_STATE_ICONS = {
    "listening": ("◉", "#f38ba8"),
    "processing": ("⋯", "#f9e2af"),
    "ai_edit": ("✦", "#cba6f7"),
    "error": ("✕", "#f38ba8"),
    "notification": ("✓", "#a6e3a1"),
}
_TRANSIENT_STATES = {"notification", "error"}


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

    def start(self) -> None:
        import tkinter as tk

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

    def update_loop(self) -> None:
        self.frame_count += 1

        if self.current_state in _TRANSIENT_STATES and time.time() > self.transient_end_time:
            self.current_state = self._resume_state
            self.message_text = ""

        state = self.current_state
        if state == "idle":
            self._rendered = None
            if self.root:
                self.root.withdraw()
        else:
            self._render(state)
            self._show_centered()

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

    def _show_centered(self) -> None:
        if not self.root:
            return
        self.root.deiconify()
        self.root.update_idletasks()
        ws = self.root.winfo_screenwidth()
        hs = self.root.winfo_screenheight()
        w = self.root.winfo_width()
        x = (ws - w) // 2
        y = hs - 150
        self.root.geometry(f"+{x}+{y}")

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
