"""System tray integration for background desktop operation."""

import os
import sys
import threading
from typing import Callable, Optional

from voiceflow_core.safe_logging import log


class SystemTray:
    """Manages the Windows taskbar system tray icon and background menu."""

    def __init__(
        self,
        on_open_dashboard: Optional[Callable[[], None]] = None,
        on_toggle_pause: Optional[Callable[[], None]] = None,
        on_copy_last: Optional[Callable[[], None]] = None,
        on_paste_last: Optional[Callable[[], None]] = None,
        on_check_updates: Optional[Callable[[], None]] = None,
        on_quit: Optional[Callable[[], None]] = None,
        is_paused_fn: Optional[Callable[[], bool]] = None,
    ):
        self.on_open_dashboard = on_open_dashboard
        self.on_toggle_pause = on_toggle_pause
        self.on_copy_last = on_copy_last
        self.on_paste_last = on_paste_last
        self.on_check_updates = on_check_updates
        self.on_quit = on_quit
        self.is_paused_fn = is_paused_fn
        self._icon = None

    def _load_icon_image(self):
        from PIL import Image

        if getattr(sys, "frozen", False):
            base_dir = sys._MEIPASS
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        candidates = [
            os.path.join(base_dir, "static", "img", "logo_final.png"),
            os.path.join(base_dir, "static", "img", "logo_icon.ico"),
            os.path.join(base_dir, "app.ico"),
        ]
        for path in candidates:
            if os.path.exists(path):
                try:
                    return Image.open(path)
                except Exception:
                    pass

        # Fallback generated icon if images not found
        from PIL import ImageDraw
        img = Image.new("RGBA", (64, 64), color=(30, 30, 46, 255))
        draw = ImageDraw.Draw(img)
        draw.ellipse((8, 8, 56, 56), fill=(139, 92, 246))
        return img

    def start(self) -> None:
        """Start system tray icon in a dedicated background daemon thread."""
        try:
            import pystray

            image = self._load_icon_image()

            def _handle_open(icon, item):
                if self.on_open_dashboard:
                    self.on_open_dashboard()

            def _handle_pause(icon, item):
                if self.on_toggle_pause:
                    self.on_toggle_pause()

            def _handle_copy_last(icon, item):
                if self.on_copy_last:
                    self.on_copy_last()

            def _handle_paste_last(icon, item):
                if self.on_paste_last:
                    self.on_paste_last()

            def _handle_check_updates(icon, item):
                if self.on_check_updates:
                    self.on_check_updates()

            def _handle_quit(icon, item):
                if self.on_quit:
                    self.on_quit()

            def _pause_text(item):
                if self.is_paused_fn and self.is_paused_fn():
                    return "▶ Resume Dictation"
                return "⏸ Pause Dictation"

            menu = pystray.Menu(
                pystray.MenuItem("VoiceFlow Dashboard", _handle_open, default=True),
                pystray.MenuItem(_pause_text, _handle_pause),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Copy Last Transcript", _handle_copy_last),
                pystray.MenuItem("Paste Last Transcript", _handle_paste_last),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Check for Updates", _handle_check_updates),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit VoiceFlow", _handle_quit),
            )

            self._icon = pystray.Icon("VoiceFlow", image, "VoiceFlow (Running)", menu)
            threading.Thread(target=self._icon.run, daemon=True).start()
            log("System tray icon started.")
        except Exception as e:
            log(f"Failed to start system tray icon: {e}")

    def stop(self) -> None:
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None
