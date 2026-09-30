# VoiceFlow

VoiceFlow is a Windows desktop dictation app that turns speech into text in any
application. Hold the global dictation shortcut, speak, and release to paste the
transcript into the focused app.

## Current release: 3.2.1

- Global push-to-talk dictation (default: **Alt + Shift**)
- Local Faster-Whisper or Groq Whisper transcription
- Optional AI Polish with filler, repetition, stutter, and false-start cleanup
- Context-aware replies based on explicitly copied clipboard text
- Custom highlight-and-rewrite presets with validated global shortcuts
- Voice edit: select text, hold the dictation shortcut, and speak an instruction
  (skipped in terminals, code editors, and Excel, where copying has side effects)
- Searchable local transcript history with Copy and Delete controls
- Crash recovery with Retry for interrupted recordings
- Writing styles, deterministic word replacements, and reusable voice snippets
- Writing profiles per app: give Slack, Outlook, Chrome, etc. their own style,
  AI Polish on/off, and instructions (pick apps from the ones currently open)
- Learning from corrections: fix a transcript in History and VoiceFlow offers to
  save the change as a word replacement (e.g. "docker compose" → "docker-compose")
- Configurable history retention and one-click local-history deletion
- Groq API keys stored in the operating-system credential store
- File transcription and a compact mini window
- First-run onboarding and selectable text throughout the app

History is stored in `~/.voiceflow/voiceflow.db`. Temporary recovery audio is
kept only when a recording fails or the app is interrupted, then removed after
a successful retry or when its history item is deleted.

## Run locally

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

The desktop window opens automatically. The local dashboard is served only on
`127.0.0.1:5000`. Every API request must carry a random token that is generated
at each launch and embedded in the dashboard page, and requests with any other
`Host` header are refused, so web pages open in your browser cannot call the
local API.

## Linux setup

VoiceFlow works on X11 out of the box. On **Wayland** (the default on Ubuntu,
Fedora and most new distros), apps are not allowed to see keys typed into other
apps or to send keys to them, so VoiceFlow uses the Linux input devices instead.
Run this once, then log out and back in:

```bash
sudo usermod -aG input $USER
echo 'KERNEL=="uinput", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput"' | sudo tee /etc/udev/rules.d/99-voiceflow-uinput.rules
echo uinput | sudo tee /etc/modules-load.d/voiceflow-uinput.conf
sudo modprobe uinput && sudo udevadm control --reload-rules && sudo udevadm trigger
```

The dashboard shows these commands (with a Copy button) whenever the setup is
missing. Being in the `input` group lets your user's programs read keyboard
input, which is what makes global shortcuts possible on Wayland.

Also recommended: `sudo apt install wl-clipboard` (Wayland) or `xclip` (X11).

What works where:

| Feature | X11 | Wayland: Sway / Hyprland | Wayland: GNOME / KDE |
|---|---|---|---|
| Shortcuts, dictation, pasting | ✅ | ✅ (after setup) | ✅ (after setup) |
| Pasting into terminals (Ctrl+Shift+V) | ✅ | ✅ | ❌ terminal not detectable; paste manually |
| Writing profiles, app-aware formatting, voice edit | ✅ | ✅ | ❌ the focused app cannot be detected |

On desktops without a tray icon (e.g. GNOME), closing the window minimizes it;
launching VoiceFlow again brings the running window back.

## Test

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python -m compileall -q app.py dictation_agent.py voiceflow_core build.py
node --check static\js\app.js
```

## Build for Windows

```powershell
python build.py
```

This creates `dist\VoiceFlow.exe`. With Inno Setup 6 installed, create the
installer with:

```powershell
ISCC.exe VoiceFlow.iss
```

The resulting installer is `dist\VoiceFlow_Setup.exe`.

## Release

Pushes and pull requests only build and test. To publish a release:

1. Bump `APP_VERSION` in `voiceflow_core/version.py` and `AppVersion` in
   `VoiceFlow.iss` to the same value.
2. Commit, then tag and push: `git tag v3.1.1 && git push origin v3.1.1`.

CI refuses to release if the tag does not match `APP_VERSION`, which keeps the
in-app update check accurate.

## Privacy notes

- Local Whisper transcription stays on the computer.
- Groq transcription and AI features send the relevant audio or text to Groq
  only when those options are selected.
- Context-aware reply mode reads clipboard text because copied text is the
  context supplied by the user.
- Transcript history and recovery audio are local and can be cleared in the
  History screen.
