# VoiceFlow

VoiceFlow is a Windows desktop dictation app that turns speech into text in any
application. Hold the global dictation shortcut, speak, and release to paste the
transcript into the focused app.

## Current release: 3.1.0

- Global push-to-talk dictation (default: **Alt + Shift**)
- Local Faster-Whisper or Groq Whisper transcription
- Optional AI Polish with filler, repetition, stutter, and false-start cleanup
- Context-aware replies based on explicitly copied clipboard text
- Custom highlight-and-rewrite presets with validated global shortcuts
- Searchable local transcript history with Copy and Delete controls
- Crash recovery with Retry for interrupted recordings
- Writing styles, deterministic word replacements, and reusable voice snippets
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
`127.0.0.1:5000`.

## Test

```powershell
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

## Privacy notes

- Local Whisper transcription stays on the computer.
- Groq transcription and AI features send the relevant audio or text to Groq
  only when those options are selected.
- Context-aware reply mode reads clipboard text because copied text is the
  context supplied by the user.
- Transcript history and recovery audio are local and can be cleared in the
  History screen.
