import threading
import sys
import pyaudio
import pyautogui
from pynput import keyboard
import collections
import queue
import tkinter as tk

_MODIFIER_MAP = {
    'alt_l': 'alt', 'alt_r': 'alt', 'alt': 'alt',
    'shift_l': 'shift', 'shift_r': 'shift', 'shift': 'shift',
    'ctrl_l': 'ctrl', 'ctrl_r': 'ctrl', 'ctrl': 'ctrl',
    'cmd_l': 'cmd', 'cmd_r': 'cmd', 'cmd': 'cmd',
}

DEFAULT_PROMPT = "You are a strict grammar-correction API. You do not answer questions, converse, or add any new information. Your ONLY job is to fix grammatical and structural errors in the user's text and return the corrected text. Do NOT wrap the text in quotes, do NOT explain the changes, and do NOT include any preamble. If the text is already perfect, return it exactly as is."

def log(msg):
    try:
        print(f"[dictation] {msg}", flush=True)
    except Exception:
        pass  # Silently ignore in --windowed mode where stdout is None

class FloatingOverlay:
    def __init__(self):
        self.root = None
        self.label = None
        self.current_state = 'idle'
        
    def start(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)
        self.root.attributes('-alpha', 0.9)
        self.root.configure(bg='#1e1e2e')
        
        self.label = tk.Label(self.root, text="", font=("Segoe UI", 12, "bold"), fg="#cdd6f4", bg="#1e1e2e", padx=15, pady=8)
        self.label.pack()
        
        ws = self.root.winfo_screenwidth()
        hs = self.root.winfo_screenheight()
        x = ws - 250
        y = hs - 150
        self.root.geometry(f"+{x}+{y}")
        
        self.root.withdraw()
        self.update_loop()
        self.root.mainloop()

    def update_loop(self):
        if self.current_state == 'listening':
            self.label.config(text="🎙️ Listening...", fg="#a6e3a1")
            self.root.deiconify()
        elif self.current_state == 'processing':
            self.label.config(text="⚙️ Processing...", fg="#f9e2af")
            self.root.deiconify()
        elif self.current_state == 'ai_edit':
            self.label.config(text="✨ AI Rewrite...", fg="#cba6f7")
            self.root.deiconify()
        else:
            self.root.withdraw()
            
        self.root.after(100, self.update_loop)

    def set_state(self, state):
        self.current_state = state

class DictationAgent:
    def __init__(self):
        self.hotkey = {'alt', 'shift'}
        self.keys_pressed = set()
        self.is_recording = False
        self._audio_chunks = []
        self._sample_rate = 16000
        self._chunk_size = 1024
        self._rolling_buffer = collections.deque(maxlen=8)
        self._running = False
        self._listener = None
        self._stream = None
        self._pa = None
        self._has_speechrec = False
        self.whisper_model = None
        self.ai_hotkey = {'ctrl', 'shift'}
        self.api_key = ""
        self.custom_prompt = DEFAULT_PROMPT
        self._is_ai_editing = False
        self.status = 'idle'
        self.overlay = FloatingOverlay()
        threading.Thread(target=self.overlay.start, daemon=True).start()

    def start(self):
        self._running = True
        self._pa = pyaudio.PyAudio()
        
        try:
            self._stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self._sample_rate,
                input=True,
                frames_per_buffer=self._chunk_size,
                stream_callback=self._audio_callback
            )
            self._stream.start_stream()
        except Exception as e:
            log(f"Failed to open audio stream: {e}")

        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.start()
        log("Agent started — hold Alt + Shift to dictate")

        self._check_imports()
        if not self._has_speechrec:
            log("WARNING: faster_whisper or numpy not installed!")
        else:
            log("Loading Faster-Whisper model (base.en)... this may take a moment.")
            try:
                from faster_whisper import WhisperModel
                self.whisper_model = WhisperModel("base.en", device="cpu", compute_type="int8")
                log("Whisper model loaded!")
            except Exception as e:
                log(f"Failed to load Whisper model: {e}")
                self._has_speechrec = False

    def stop(self):
        self._running = False
        if self._listener:
            self._listener.stop()
        if self._stream:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except:
                pass
        if self._pa:
            self._pa.terminate()
        log("Agent stopped")

    def _check_imports(self):
        try:
            import faster_whisper
            import numpy as np
            self._has_speechrec = True
        except ImportError:
            self._has_speechrec = False

    def _normalize(self, key):
        name = None
        if hasattr(key, 'char') and key.char:
            name = key.char.lower()
        elif hasattr(key, 'name'):
            name = key.name.lower()
        return _MODIFIER_MAP.get(name, name)

    def _on_press(self, key):
        try:
            n = self._normalize(key)
            if n:
                self.keys_pressed.add(n)
        except Exception as e:
            log(f"Key press error: {e}")
            return

        if self.hotkey.issubset(self.keys_pressed) and not self.is_recording:
            self._start_recording()
        elif self.ai_hotkey.issubset(self.keys_pressed) and not self.is_recording and not self._is_ai_editing:
            threading.Thread(target=self._trigger_ai_edit, daemon=True).start()

    def _on_release(self, key):
        try:
            n = self._normalize(key)
            if n and n in self.keys_pressed:
                self.keys_pressed.remove(n)
        except Exception as e:
            log(f"Key release error: {e}")
            return

        if not self.hotkey.issubset(self.keys_pressed) and self.is_recording:
            self._stop_recording()

    def _start_recording(self):
        log("Recording started")
        self.is_recording = True
        self.status = 'listening'
        self.overlay.set_state('listening')
        self._audio_chunks = list(self._rolling_buffer)

    def _audio_callback(self, in_data, frame_count, time_info, status):
        self._rolling_buffer.append(in_data)
        if self.is_recording:
            self._audio_chunks.append(in_data)
        return (None, pyaudio.paContinue)

    def _stop_recording(self):
        log("Recording stopped, processing...")
        self.is_recording = False
        self.keys_pressed.clear()
        self.status = 'processing'
        self.overlay.set_state('processing')

        chunks = self._audio_chunks
        self._audio_chunks = []

        def process():
            if chunks:
                raw = b''.join(chunks)
                secs = len(raw) / (self._sample_rate * 2)
                log(f"Captured {len(raw)} bytes ({secs:.1f}s)")

                text = self._transcribe(raw)
                if text:
                    log(f"Typing: \"{text[:60]}...\"")
                    self._type_text(text)
                else:
                    log("No text to type")
            else:
                log("No audio captured")

            self.status = 'idle'
            self.overlay.set_state('idle')
            
        threading.Thread(target=process, daemon=True).start()

    def _transcribe(self, raw_bytes):
        if not self._has_speechrec or not self.whisper_model:
            log("Cannot transcribe: faster_whisper not installed or model failed to load")
            return None

        try:
            import numpy as np
            # Convert raw_bytes (int16) to float32 normalized
            audio_data = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            
            log("Transcribing with Faster-Whisper...")
            segments, info = self.whisper_model.transcribe(
                audio_data, 
                beam_size=5,
                vad_filter=True,
                initial_prompt="Here is a transcription with correct capitalization, commas, and periods."
            )
            
            text = " ".join([segment.text for segment in segments])
            log("Transcription received")
            return text.strip()
        except Exception as e:
            log(f"Transcription error: {e}")
            return None

    def _enhance_with_llm(self, text):
        if not self.api_key:
            log("API key missing. Skipping AI enhancement.")
            return text
        try:
            from groq import Groq
            client = Groq(api_key=self.api_key)
            log("Sending to Groq LLM for polish...")
            response = client.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": self.custom_prompt
                    },
                    {
                        "role": "user",
                        "content": text
                    }
                ],
                model="llama-3.1-8b-instant",
                temperature=0.0,
            )
            polished = response.choices[0].message.content.strip()
            log("AI polish complete.")
            return polished
        except Exception as e:
            log(f"Groq API Error: {e}")
            return text

    def _type_text(self, text):
        try:
            import pyperclip
            pyperclip.copy(text + ' ')
            pyautogui.hotkey('ctrl', 'v')
        except Exception as e:
            log(f"Type error: {e}")

    def _trigger_ai_edit(self):
        self._is_ai_editing = True
        self.overlay.set_state('ai_edit')
        log("AI Edit triggered on selected text...")
        
        try:
            import pyperclip
            import time
            import pyautogui
            
            # Wait for user to physically release the hotkeys so they don't interfere with Ctrl+C/V
            wait_time = 0
            while self.keys_pressed and wait_time < 2.0:
                time.sleep(0.05)
                wait_time += 0.05
                
            self.keys_pressed.clear()
            
            # Force release physical modifier keys just in case they are still physically held down
            from pynput.keyboard import Controller, Key
            kb = Controller()
            kb.release(Key.ctrl)
            kb.release(Key.shift)
            kb.release(Key.alt)
            time.sleep(0.1)
            
            # Save current clipboard
            try:
                old_clipboard = pyperclip.paste()
            except:
                old_clipboard = ""
            
            # Clear clipboard to detect if copy was successful
            pyperclip.copy('')
            
            # Copy selected text
            log("Simulating Ctrl+C...")
            pyautogui.hotkey('ctrl', 'c')
            time.sleep(0.3)
            
            try:
                selected_text = pyperclip.paste().strip()
            except:
                selected_text = ""
            
            if not selected_text:
                log("No text selected or copy failed!")
                pyperclip.copy(old_clipboard)
                return
                
            log(f"Selected: \"{selected_text[:30]}...\"")
            
            new_text = self._enhance_with_llm(selected_text)
            
            # Paste the new text over the selection
            pyperclip.copy(new_text)
            
            kb.release(Key.ctrl)
            kb.release(Key.shift)
            kb.release(Key.alt)
            
            log("Simulating Ctrl+V...")
            pyautogui.hotkey('ctrl', 'v')
            
            # Small delay to ensure paste happens before restoring old clipboard
            time.sleep(0.3)
            pyperclip.copy(old_clipboard)
            
            log("AI Edit complete.")
        except Exception as e:
            log(f"AI Edit error: {e}")
        finally:
            self._is_ai_editing = False
            self.overlay.set_state('idle')

    def set_hotkey(self, key1, key2):
        k1 = _MODIFIER_MAP.get(key1.lower(), key1.lower())
        k2 = _MODIFIER_MAP.get(key2.lower(), key2.lower())
        self.hotkey = {k1, k2}
        self.keys_pressed.clear()
        log(f"Hotkey set to: {self.hotkey}")

    def set_ai_hotkey(self, key1, key2):
        k1 = _MODIFIER_MAP.get(key1.lower(), key1.lower())
        k2 = _MODIFIER_MAP.get(key2.lower(), key2.lower())
        self.ai_hotkey = {k1, k2}
        self.keys_pressed.clear()
        log(f"AI Hotkey set to: {self.ai_hotkey}")

    def get_config(self):
        keys = list(self.hotkey)
        while len(keys) < 2:
            keys.append(keys[0] if keys else 'ctrl')
        ai_keys = list(self.ai_hotkey)
        while len(ai_keys) < 2:
            ai_keys.append(ai_keys[0] if ai_keys else 'ctrl')
        return {
            'status': self.status,
            'hotkey': keys[:2],
            'ai_hotkey': ai_keys[:2],
            'api_key': self.api_key,
            'custom_prompt': self.custom_prompt,
            'default_prompt': DEFAULT_PROMPT
        }
