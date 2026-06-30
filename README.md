# Voice-to-Text Writing System

A lightweight dictation system that types what you say into **any application** using global hotkeys.

## How it works

A Python background agent listens for a **push-to-talk hotkey** (default: hold **W + R**). While you hold the keys, it records your microphone. When you release, it transcribes the speech and types the text into whatever window has focus — Notepad, Chrome, VS Code, anything.

## Features

- **Global dictation** — types into any app, not just the web editor
- **Push-to-talk** — hold W+R to record, release to transcribe & type
- **Configurable hotkey** — change the key combo in Settings
- **Web editor** — save, copy, clear, word/char count, dark mode, auto-save

## Run locally

```bash
# 1. Create virtual environment
python -m venv venv
venv\Scripts\activate

# 2. Install dependencies (may prompt to install Microsoft Visual C++ build tools for pyaudio)
pip install -r requirements.txt

# 3. Start the server + dictation agent
python app.py

# 4. Open browser
start http://localhost:5000
```

## Usage

1. Open `http://localhost:5000` in your browser
2. Click any window (Notepad, browser, editor) to put the cursor where you want text
3. Press and **hold** W + R on your keyboard
4. Speak clearly into your microphone
5. Release W + R — the transcribed text appears at your cursor
6. Repeat anytime

To change the hotkey, click the gear icon in the web editor and set two keys.

## Notes

- Requires microphone access
- Transcription uses Google's free speech recognition API (requires internet)
- The web editor is optional — dictation works globally even without it
