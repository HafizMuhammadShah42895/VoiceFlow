"""Floating HUD overlay for desktop dictation visual feedback."""

import os
import sys
import time
from typing import Optional


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
    def __init__(self):
        self.root = None
        self.label = None
        self.current_state = "idle"
        self.live_text = ""
        self.volume_level = 0.0
        self.notification_text = ""
        self.error_text = ""
        self.notification_end_time = 0.0
        self.gifs = {}
        self.frame_count = 0

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
        )
        self.label.pack()

        self.root.withdraw()
        self.update_loop()
        self.root.mainloop()

    def update_volume(self, volume: float) -> None:
        self.volume_level = volume

    def update_loop(self) -> None:
        self.frame_count += 1

        if self.current_state != "idle":
            gif = self.gifs.get(self.current_state)
            frame = gif.get_frame(self.frame_count) if gif else None

            if self.current_state == "listening":
                if frame:
                    self.label.config(image=frame, text="")
                else:
                    self.label.config(image="", text="◉", fg="#f38ba8")
            elif self.current_state == "processing":
                if frame:
                    self.label.config(image=frame, text="")
                else:
                    self.label.config(image="", text="⋯", fg="#f9e2af")
            elif self.current_state == "ai_edit":
                if frame:
                    self.label.config(image=frame, text="")
                else:
                    self.label.config(image="", text="✦", fg="#cba6f7")
            elif self.current_state == "error":
                if frame:
                    self.label.config(image=frame, text="")
                else:
                    self.label.config(image="", text="✕", fg="#f38ba8")
            elif self.current_state == "notification":
                if time.time() > self.notification_end_time:
                    self.set_state("idle")
                else:
                    if frame:
                        self.label.config(image=frame, text="")
                    else:
                        self.label.config(image="", text="✓", fg="#a6e3a1")

            if self.current_state != "idle":
                self._show_centered()
        else:
            if self.root:
                self.root.withdraw()

        if self.root:
            self.root.after(50, self.update_loop)

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

    def set_state(self, state: str) -> None:
        self.current_state = state
        if state != "listening":
            self.live_text = ""

    def set_live_text(self, text: str) -> None:
        self.live_text = text

    def show_error(self, message: str) -> None:
        self.error_text = message
        self.current_state = "error"

    def show_notification(self, message: str) -> None:
        self.notification_text = message
        self.current_state = "notification"
        self.notification_end_time = time.time() + 2.0
