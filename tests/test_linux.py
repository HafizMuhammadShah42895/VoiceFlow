"""Linux / Wayland behaviour. Most tests simulate Linux so they also run on Windows."""

import os
import sys
import unittest
from unittest import mock

from voiceflow_core import app_context, clipboard, linux_input
from voiceflow_core.app_context import AppContext, _category_for_process
from voiceflow_core.hotkeys import normalize_key
from voiceflow_core.secrets import CredentialStore


class LinuxAppDetectionTests(unittest.TestCase):
    def test_linux_process_names_have_categories(self):
        self.assertEqual(_category_for_process("gnome-terminal-server"), "terminal")
        self.assertEqual(_category_for_process("kitty"), "terminal")
        self.assertEqual(_category_for_process("code"), "code")
        self.assertEqual(_category_for_process("firefox"), "browser")
        self.assertEqual(_category_for_process("slack"), "chat")
        self.assertEqual(_category_for_process("thunderbird"), "email")

    def test_unknown_linux_app_is_never_probed_with_ctrl_c(self):
        with mock.patch.object(app_context.sys, "platform", "linux"):
            self.assertFalse(AppContext().allows_selection_capture)
            self.assertFalse(AppContext(process_name="kitty", category="terminal").allows_selection_capture)
            self.assertTrue(AppContext(process_name="gedit").allows_selection_capture)
        with mock.patch.object(app_context.sys, "platform", "darwin"):
            self.assertTrue(AppContext().allows_selection_capture)

    def test_hyprland_active_window(self):
        env = {"HYPRLAND_INSTANCE_SIGNATURE": "abc", "XDG_SESSION_TYPE": "wayland"}
        window = {"pid": 4242, "class": "kitty", "title": "~/project"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(app_context.sys, "platform", "linux"), \
                mock.patch.object(app_context, "_run_json", return_value=window), \
                mock.patch.object(app_context, "_linux_process_name", side_effect=lambda pid, fallback: fallback):
            context = app_context.get_foreground_app_context()
        self.assertEqual((context.process_name, context.category), ("kitty", "terminal"))
        self.assertFalse(context.allows_selection_capture)

    def test_sway_focused_window_and_open_apps(self):
        tree = {"nodes": [{"nodes": [
            {"pid": 1, "app_id": "firefox", "name": "Docs", "focused": False},
            {"pid": 2, "app_id": "foot", "name": "shell", "focused": True},
        ]}], "floating_nodes": []}
        env = {"SWAYSOCK": "/run/sway.sock", "XDG_SESSION_TYPE": "wayland"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(app_context.sys, "platform", "linux"), \
                mock.patch.object(app_context, "_run_json", return_value=tree), \
                mock.patch.object(app_context, "_linux_process_name", side_effect=lambda pid, fallback: fallback):
            self.assertEqual(app_context.get_foreground_app_context().process_name, "foot")
            self.assertEqual([a["process_name"] for a in app_context.list_open_apps()], ["firefox", "foot"])

    def test_gnome_wayland_does_not_trust_stale_x11_windows(self):
        env = {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(app_context.sys, "platform", "linux"), \
                mock.patch.object(app_context, "_x11_windows") as x11:
            self.assertEqual(app_context.get_foreground_app_context(), AppContext())
        x11.assert_not_called()


class LinuxPlatformIssueTests(unittest.TestCase):
    def issues(self, keyboards=True, uinput=True, compositor=False, tools=True):
        with mock.patch.object(linux_input, "is_linux", return_value=True), \
                mock.patch.object(linux_input, "is_wayland", return_value=True), \
                mock.patch.object(linux_input, "evdev", object()), \
                mock.patch.object(linux_input, "keyboards_readable", return_value=keyboards), \
                mock.patch.object(linux_input, "uinput_writable", return_value=uinput), \
                mock.patch.object(linux_input, "_compositor_reports_active_window", return_value=compositor), \
                mock.patch.object(linux_input.shutil, "which", return_value="/usr/bin/x" if tools else None):
            return {issue["id"]: issue for issue in linux_input.detect_platform_issues()}

    def test_wayland_without_permissions_explains_the_fix(self):
        issues = self.issues(keyboards=False, uinput=False)
        setup = issues["wayland_input_access"]
        self.assertEqual(setup["level"], "warning")
        self.assertIn("sudo usermod -aG input $USER", setup["commands"])
        self.assertIn("read the keyboard", setup["detail"])
        self.assertIn("virtual keyboard", setup["detail"])

    def test_fully_set_up_hyprland_has_no_issues(self):
        self.assertEqual(self.issues(compositor=True), {})

    def test_gnome_wayland_notes_limited_app_detection_and_clipboard_tool(self):
        issues = self.issues(tools=False)
        self.assertEqual(set(issues), {"wayland_app_detection", "clipboard_tool"})

    def test_no_issues_reported_off_linux(self):
        with mock.patch.object(linux_input, "is_linux", return_value=False):
            self.assertEqual(linux_input.detect_platform_issues(), [])


class LinuxClipboardTests(unittest.TestCase):
    def test_terminal_paste_uses_ctrl_shift_v_through_virtual_keyboard(self):
        with mock.patch.object(clipboard.sys, "platform", "linux"), \
                mock.patch.object(clipboard.linux_input, "should_use_virtual_keyboard", return_value=True), \
                mock.patch.object(clipboard.linux_input, "send_shortcut") as send, \
                mock.patch.object(clipboard, "safe_clipboard_set", return_value=True), \
                mock.patch.object(clipboard, "force_release_modifiers"):
            self.assertTrue(clipboard.paste_text("ls -la", restore_clipboard=False, terminal=True))
            self.assertTrue(clipboard.paste_text("hello", restore_clipboard=False))
        self.assertEqual(send.call_args_list, [mock.call("v", shift=True), mock.call("v", shift=False)])

    def test_clipboard_falls_back_to_long_lived_window(self):
        store = {}

        class FakeRoot:
            def clipboard_clear(self):
                store.clear()

            def clipboard_append(self, text):
                store["text"] = text

            def update_idletasks(self):
                pass

            def clipboard_get(self):
                return store["text"]

        broken = mock.MagicMock()
        broken.copy.side_effect = RuntimeError("no xclip")
        broken.paste.side_effect = RuntimeError("no xclip")
        clipboard.set_clipboard_host(lambda func: func(FakeRoot()))
        try:
            with mock.patch.dict(sys.modules, {"pyperclip": broken}):
                self.assertTrue(clipboard.safe_clipboard_set("dictated text"))
                self.assertEqual(clipboard.safe_clipboard_get(), "dictated text")
        finally:
            clipboard.set_clipboard_host(None)


class CredentialStoreAvailabilityTests(unittest.TestCase):
    def test_fail_backend_is_not_available(self):
        class FailRing:
            priority = 0

        backend = mock.Mock()
        backend.get_keyring.return_value = FailRing()
        self.assertFalse(CredentialStore(backend).available)

        class RealRing:
            priority = 5

        backend.get_keyring.return_value = RealRing()
        self.assertTrue(CredentialStore(backend).available)


@unittest.skipUnless(linux_input.evdev is not None, "evdev is only installed on Linux")
class EvdevListenerTests(unittest.TestCase):
    def test_translates_kernel_key_events(self):
        ecodes = linux_input.ecodes
        pressed, released = [], []
        listener = linux_input.EvdevKeyboardListener(
            on_press=lambda key: pressed.append(normalize_key(key)),
            on_release=lambda key: released.append(normalize_key(key)),
        )
        listener.handle_event(ecodes.KEY_LEFTALT, 1)
        listener.handle_event(ecodes.KEY_RIGHTSHIFT, 1)
        listener.handle_event(ecodes.KEY_RIGHTSHIFT, 2)  # auto-repeat
        listener.handle_event(ecodes.KEY_A, 1)
        listener.handle_event(ecodes.KEY_SPACE, 1)
        listener.handle_event(ecodes.KEY_ESC, 1)
        listener.handle_event(ecodes.KEY_LEFTALT, 0)
        listener.handle_event(ecodes.KEY_VOLUMEUP, 1)  # ignored
        self.assertEqual(pressed, ["alt", "shift", "shift", "a", "space", "esc"])
        self.assertEqual(released, ["alt"])


if __name__ == "__main__":
    unittest.main()
