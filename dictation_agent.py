import threading
import sys
import pyaudio
import pyautogui
from pynput import keyboard
import collections
import queue
import tkinter as tk
import json
import os
import time

CONFIG_FILE = os.path.expanduser('~/.voiceflow_config.json')

_MODIFIER_MAP = {
    'alt_l': 'alt', 'alt_r': 'alt', 'alt': 'alt',
    'shift_l': 'shift', 'shift_r': 'shift', 'shift': 'shift',
    'ctrl_l': 'ctrl', 'ctrl_r': 'ctrl', 'ctrl': 'ctrl',
    'cmd_l': 'cmd', 'cmd_r': 'cmd', 'cmd': 'cmd',
}

DEFAULT_PROMPT = "You are a strict grammar-correction API. You do not answer questions, converse, or add any new information. Your ONLY job is to fix grammatical and structural errors in the user's text and return the corrected text. Do NOT wrap the text in quotes, do NOT explain the changes, and do NOT include any preamble. If the text is already perfect, return it exactly as is."
DEFAULT_CONTEXT_PROMPT = "The dictated text is intended as a response or addition to the text in the clipboard. Rewrite the dictated text to be a polite, professional, and well-formulated response. DO NOT include the clipboard text in your output."

def safe_clipboard_get():
    try:
        import pyperclip
        return pyperclip.paste()
    except Exception:
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            result = root.clipboard_get()
            root.destroy()
            return result
        except Exception:
            return ""

def safe_clipboard_set(text):
    try:
        import pyperclip
        pyperclip.copy(text)
    except Exception:
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            root.clipboard_clear()
            root.clipboard_append(text)
            root.update()
            root.destroy()
        except Exception:
            pass

def log(msg):
    try:
        print(f"[dictation] {msg}", flush=True)
    except Exception:
        pass  # Silently ignore in --windowed mode where stdout is None
class AnimatedGIF:
    def __init__(self, path):
        self.frames = []
        try:
            import os, tkinter as tk
            if not os.path.exists(path):
                return
            idx = 0
            while True:
                frame = tk.PhotoImage(file=path, format=f"gif -index {idx}")
                self.frames.append(frame)
                idx += 1
        except Exception:
            pass

    def get_frame(self, index):
        if not self.frames:
            return None
        return self.frames[(index // 2) % len(self.frames)]  # //2 slows down animation slightly

class FloatingOverlay:
    def __init__(self):
        self.root = None
        self.label = None
        self.current_state = 'idle'
        self.live_text = ""
        self.volume_level = 0.0
        self.notification_text = ""
        self.error_text = ""
        self.notification_end_time = 0
        
    def start(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)
        self.root.attributes('-alpha', 0.95)
        self.root.configure(bg='#18181b')
        
        base_dir = os.path.dirname(os.path.abspath(__file__))
        img_dir = os.path.join(base_dir, 'static', 'img')
        self.gifs = {
            'listening': AnimatedGIF(os.path.join(img_dir, 'listening.gif')),
            'processing': AnimatedGIF(os.path.join(img_dir, 'processing.gif')),
            'ai_edit': AnimatedGIF(os.path.join(img_dir, 'ai.gif')),
            'notification': AnimatedGIF(os.path.join(img_dir, 'success.gif')),
            'error': AnimatedGIF(os.path.join(img_dir, 'error.gif')),
        }
        
        self.label = tk.Label(self.root, text="", font=("Segoe UI Emoji", 24), fg="#f4f4f5", bg="#18181b", padx=15, pady=8, justify="center")
        self.label.pack()
        
        self.root.withdraw()
        self.update_loop()
        self.root.mainloop()

    def update_volume(self, volume):
        self.volume_level = volume

    def update_loop(self):
        self.frame_count = getattr(self, 'frame_count', 0) + 1
        
        if self.current_state != 'idle':
            gif = self.gifs.get(self.current_state)
            frame = gif.get_frame(self.frame_count) if gif else None
            
            if self.current_state == 'listening':
                if frame:
                    self.label.config(image=frame, text="")
                else:
                    self.label.config(image="", text="◉", fg="#f38ba8")
            elif self.current_state == 'processing':
                if frame:
                    self.label.config(image=frame, text="")
                else:
                    self.label.config(image="", text="⋯", fg="#f9e2af")
            elif self.current_state == 'ai_edit':
                if frame:
                    self.label.config(image=frame, text="")
                else:
                    self.label.config(image="", text="✦", fg="#cba6f7")
            elif self.current_state == 'error':
                if frame:
                    self.label.config(image=frame, text="")
                else:
                    self.label.config(image="", text="✕", fg="#f38ba8")
            elif self.current_state == 'notification':
                import time
                if time.time() > self.notification_end_time:
                    self.set_state('idle')
                else:
                    if frame:
                        self.label.config(image=frame, text="")
                    else:
                        self.label.config(image="", text="✓", fg="#a6e3a1")

            if self.current_state != 'idle':
                self._show_centered()
        else:
            self.root.withdraw()
            
        self.root.after(50, self.update_loop)

    def _show_centered(self):
        self.root.deiconify()
        self.root.update_idletasks()
        ws = self.root.winfo_screenwidth()
        hs = self.root.winfo_screenheight()
        w = self.root.winfo_width()
        x = (ws - w) // 2
        y = hs - 150
        
        self.root.geometry(f"+{x}+{y}")

    def set_state(self, state):
        self.current_state = state
        if state != 'listening':
            self.live_text = ""

    def set_live_text(self, text):
        self.live_text = text

    def show_error(self, message):
        self.error_text = message
        self.current_state = 'error'

    def show_notification(self, message):
        import time
        self.notification_text = message
        self.current_state = 'notification'
        self.notification_end_time = time.time() + 2.0

class DictationAgent:
    def __init__(self):
        self.hotkey = {'alt', 'shift'}
        self.context_hotkey = {'ctrl', 'shift'}
        self.keys_pressed = set()
        self.is_recording = False
        self._is_context_recording = False
        self.context_prompt = DEFAULT_CONTEXT_PROMPT
        self.main_dictation_ai = False
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
        
        self.ai_presets = [
            {
                "id": "preset_1",
                "name": "Default Grammar Polish",
                "hotkeys": ["ctrl", "shift"],
                "prompt": DEFAULT_PROMPT
            }
        ]
        
        self.api_key = ""
        self.run_at_startup = False
        self.use_local_llm = False
        self.dictation_language = "auto"
        self.transcription_engine = "local"
        self.custom_vocabulary = ""
        self.context_aware_dictation = False
        self.remove_filler_words = False
        self.output_mode = "type"
        self._load_config()
        
        self._is_ai_editing = False
        self.status = 'idle'
        self._last_callback_time = time.time()
        self.overlay = FloatingOverlay()
        threading.Thread(target=self.overlay.start, daemon=True).start()

    def _load_config(self):
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if 'hotkey' in data and len(data['hotkey']) >= 2:
                        self.set_hotkey(data['hotkey'][0], data['hotkey'][1])
                    if 'context_hotkey' in data and len(data['context_hotkey']) >= 2:
                        self.set_context_hotkey(data['context_hotkey'][0], data['context_hotkey'][1])
                    if 'ai_presets' in data:
                        self.ai_presets = data['ai_presets']
                    if 'api_key' in data:
                        self.api_key = data['api_key']
                    if 'dictation_language' in data:
                        self.dictation_language = data['dictation_language']
                    if 'use_local_llm' in data:
                        self.use_local_llm = data['use_local_llm']
                    if 'transcription_engine' in data:
                        self.transcription_engine = data['transcription_engine']
                    if 'custom_vocabulary' in data:
                        self.custom_vocabulary = data['custom_vocabulary']
                    if 'context_prompt' in data:
                        self.context_prompt = data['context_prompt']
                    if 'main_dictation_ai' in data:
                        self.main_dictation_ai = data['main_dictation_ai']
                    if 'context_aware_dictation' in data:
                        self.context_aware_dictation = data['context_aware_dictation']
                    if 'remove_filler_words' in data:
                        self.remove_filler_words = data['remove_filler_words']
                    if 'output_mode' in data:
                        self.output_mode = data['output_mode']
                    if 'run_at_startup' in data:
                        self.set_startup(data['run_at_startup'])
                log("Configuration loaded from disk.")
        except Exception as e:
            log(f"Failed to load config: {e}")

    def save_config(self):
        try:
            data = self.get_config()
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f)
            log("Configuration saved to disk.")
        except Exception as e:
            log(f"Failed to save config: {e}")

    def start(self):
        self._running = True
        self._pa = pyaudio.PyAudio()
        
        self._reopen_stream()
        
        # Start watchdog to recover from unplugged headphones
        threading.Thread(target=self._audio_watchdog, daemon=True).start()

        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.start()
        log("Agent started — hold Alt + Shift to dictate")

        self._check_imports()

    def _check_imports(self):
        try:
            import numpy
            import faster_whisper
            self._has_speechrec = True
            log("Dependencies found. Local Whisper will be loaded on demand.")
        except ImportError:
            self._has_speechrec = False
            log("WARNING: faster_whisper or numpy not installed!")
            
    def _get_whisper_model(self):
        if not self._has_speechrec:
            return None
        if self.whisper_model is None:
            self.overlay.show_notification("Loading AI... (first time only)")
            log("Loading Faster-Whisper model (base)... this may take a moment.")
            try:
                from faster_whisper import WhisperModel
                self.whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
                log("Whisper model loaded!")
                self.overlay.set_state('idle')
            except Exception as e:
                log(f"Failed to load Whisper model: {e}")
                self._has_speechrec = False
                self.overlay.set_state('idle')
        return self.whisper_model

    def _reopen_stream(self):
        try:
            if self._stream:
                self._stream.stop_stream()
                self._stream.close()
        except:
            pass
            
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
            self._last_callback_time = time.time()
            log("Audio stream connected.")
        except Exception as e:
            log(f"Failed to open audio stream: {e}")

    def _audio_watchdog(self):
        while self._running:
            time.sleep(1.0)
            # If we haven't received audio data in 2 seconds, the device was likely unplugged
            if time.time() - self._last_callback_time > 2.0:
                if not self.is_recording:
                    log("Hardware interrupt detected. Rebuilding audio stream...")
                    self._reopen_stream()
                else:
                    self._last_callback_time = time.time() # don't interrupt active recordings unless necessary

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

        if self.context_hotkey.issubset(self.keys_pressed) and not self.is_recording:
            self._is_context_recording = True
            self._start_recording()
            return

        if self.hotkey.issubset(self.keys_pressed) and not self.is_recording:
            self._is_context_recording = False
            self._start_recording()
            return
            
        if not self.is_recording and not self._is_ai_editing:
            for preset in self.ai_presets:
                preset_keys = set()
                for k in preset.get("hotkeys", []):
                    if isinstance(k, str):
                        lk = k.lower()
                        preset_keys.add(_MODIFIER_MAP.get(lk, lk))
                
                if preset_keys and preset_keys.issubset(self.keys_pressed):
                    threading.Thread(target=self._trigger_ai_edit, args=(preset.get("prompt", DEFAULT_PROMPT),), daemon=True).start()
                    break

    def _on_release(self, key):
        try:
            n = self._normalize(key)
            if n and n in self.keys_pressed:
                self.keys_pressed.remove(n)
        except Exception as e:
            log(f"Key release error: {e}")
            return

        if self.is_recording:
            if self._is_context_recording:
                if not self.context_hotkey.issubset(self.keys_pressed):
                    self._stop_recording()
            else:
                if not self.hotkey.issubset(self.keys_pressed):
                    self._stop_recording()

    def _start_recording(self):
        log("Recording started")
        try:
            import winsound
            import sys, os
            if getattr(sys, 'frozen', False):
                b_dir = sys._MEIPASS
            else:
                b_dir = os.path.dirname(os.path.abspath(__file__))
            winsound.PlaySound(os.path.join(b_dir, 'static', 'sounds', 'start.wav'), winsound.SND_FILENAME | winsound.SND_ASYNC)
        except:
            pass
        self.is_recording = True
        self.status = 'listening'
        self.overlay.set_live_text("")
        self.overlay.set_state('listening')
        self._audio_chunks = list(self._rolling_buffer)
        threading.Thread(target=self._live_transcription_worker, daemon=True).start()

    def _live_transcription_worker(self):
        while self.is_recording:
            start_time = time.time()
            while self.is_recording and time.time() - start_time < 1.5:
                time.sleep(0.1)
                
            if not self.is_recording:
                break
                
            chunks = list(self._audio_chunks)
            if not chunks:
                continue
                
            raw = b''.join(chunks)
            secs = len(raw) / (self._sample_rate * 2)
            if secs < 1.0:
                continue
                
            text = self._transcribe(raw)
            if text and self.is_recording:
                self.overlay.set_live_text(text)

    def _audio_callback(self, in_data, frame_count, time_info, status):
        self._last_callback_time = time.time()
        self._rolling_buffer.append(in_data)
        
        try:
            import numpy as np
            audio_data = np.frombuffer(in_data, dtype=np.int16).astype(np.float32)
            volume = float(np.sqrt(np.mean(np.square(audio_data))) / 32768.0)
            if hasattr(self.overlay, 'update_volume'):
                self.overlay.update_volume(volume)
        except:
            pass

        if self.is_recording:
            self._audio_chunks.append(in_data)
        return (None, pyaudio.paContinue)

    def _stop_recording(self):
        log("Recording stopped, processing...")
        try:
            import winsound
            import sys, os
            if getattr(sys, 'frozen', False):
                b_dir = sys._MEIPASS
            else:
                b_dir = os.path.dirname(os.path.abspath(__file__))
            winsound.PlaySound(os.path.join(b_dir, 'static', 'sounds', 'stop.wav'), winsound.SND_FILENAME | winsound.SND_ASYNC)
        except:
            pass
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
                if text and text.strip():
                    use_ai = False
                    if self._is_context_recording:
                        use_ai = True
                    elif getattr(self, 'remove_filler_words', False):
                        use_ai = True
                    elif getattr(self, 'main_dictation_ai', False):
                        use_ai = True

                    if use_ai:
                        self.overlay.set_state('ai_edit')
                        text = self._apply_llm_post_processing(text)
                        
                    if text and text.strip():
                        text = self._apply_voice_commands(text)
                        log(f"Typing: \"{text[:60]}...\"")
                        self._type_text(text)
                    else:
                        log("No text to type (empty after AI)")
                else:
                    log("No text to type (nothing detected)")
            else:
                log("No audio captured")

            self.status = 'idle'
            self.overlay.set_state('idle')
            
        threading.Thread(target=process, daemon=True).start()

    def _apply_llm_post_processing(self, text):
        if not self._is_context_recording and not getattr(self, 'remove_filler_words', False) and not getattr(self, 'main_dictation_ai', False):
            return text
            
        if not getattr(self, 'api_key', None):
            log("API key missing. Cannot post-process with Groq.")
            return text
            
        system_prompt = "You are a professional text editor. Your ONLY job is to output the final edited text. DO NOT add conversational replies, preambles, or quotes."
        user_prompt = f"Here is the dictated text: {text}\n\n"
        
        if getattr(self, 'remove_filler_words', False):
            user_prompt += "Instruction: Remove all filler words (e.g. 'um', 'uh', 'like', 'you know'), false starts, and stutters to make the text clean and professional, without changing the meaning.\n"
        elif not self._is_context_recording and getattr(self, 'main_dictation_ai', False):
            user_prompt += f"Instruction: {getattr(self, 'default_prompt', DEFAULT_PROMPT)}\n"
            
        if self._is_context_recording:
            try:
                # import pyperclip
                clipboard_text = safe_clipboard_get()
                if clipboard_text and len(clipboard_text.strip()) > 0:
                    user_prompt += f"Instruction: {getattr(self, 'context_prompt', DEFAULT_CONTEXT_PROMPT)}\n[CLIPBOARD START]\n{clipboard_text}\n[CLIPBOARD END]\n"
            except Exception as e:
                log(f"Failed to read clipboard for context: {e}")
                
        try:
            from groq import Groq
            client = Groq(api_key=self.api_key)
            completion = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                model="openai/gpt-oss-20b",
                temperature=0.3,
            )
            edited_text = completion.choices[0].message.content.strip()
            return edited_text
        except Exception as e:
            log(f"Groq LLM error during post-processing: {e}")
            return text

    def _apply_voice_commands(self, text):
        import re
        commands = {
            r'(?i)\s*\bnew paragraph\b\s*[.,!?]*\s*': '\n\n',
            r'(?i)\s*\bnew line\b\s*[.,!?]*\s*': '\n',
            r'(?i)\s*\bcomma\b\s*[.,!?]*\s*': ', ',
            r'(?i)\s*\bperiod\b\s*[.,!?]*\s*': '. ',
            r'(?i)\s*\bquestion mark\b\s*[.,!?]*\s*': '? ',
            r'(?i)\s*\bexclamation point\b\s*[.,!?]*\s*': '! ',
            r'(?i)\s*\bexclamation mark\b\s*[.,!?]*\s*': '! '
        }
        for pattern, replacement in commands.items():
            text = re.sub(pattern, replacement, text)
        
        text = re.sub(r'\s+([,\.\?!])', r'\1', text)
        return text.strip()

    def _transcribe(self, raw_bytes):
        engine = getattr(self, 'transcription_engine', 'local')
        if engine == 'groq':
            if not self.api_key:
                log("API key missing. Cannot use Groq for transcription.")
                return None
            try:
                import tempfile
                import wave
                import os
                from groq import Groq
                
                # Save raw_bytes to a temporary wav file
                fd, temp_path = tempfile.mkstemp(suffix=".wav")
                os.close(fd)
                with wave.open(temp_path, 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2) # 16-bit
                    wf.setframerate(self._sample_rate)
                    wf.writeframes(raw_bytes)
                
                log("Transcribing with Groq Whisper...")
                client = Groq(api_key=self.api_key)
                lang = None if getattr(self, 'dictation_language', 'auto') == "auto" else self.dictation_language
                
                base_prompt = "Here is a transcription with correct capitalization, commas, and periods."
                vocab = getattr(self, 'custom_vocabulary', '').strip()
                if vocab:
                    base_prompt += f" Vocabulary: {vocab}"
                
                kwargs = {
                    "file": (os.path.basename(temp_path), open(temp_path, "rb").read()),
                    "model": "whisper-large-v3-turbo",
                    "prompt": base_prompt,
                    "response_format": "text"
                }
                if lang:
                    kwargs["language"] = lang
                    
                transcription = client.audio.transcriptions.create(**kwargs)
                
                try:
                    os.remove(temp_path)
                except:
                    pass
                    
                log("Transcription received from Groq")
                return transcription.strip()
            except Exception as e:
                log(f"Groq Transcription error: {e}")
                return None
                
        model = self._get_whisper_model()
        if not model:
            log("Cannot transcribe locally: faster_whisper not installed or model failed to load")
            return None

        try:
            import numpy as np
            # Convert raw_bytes (int16) to float32 normalized
            audio_data = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            
            log("Transcribing with Faster-Whisper...")
            
            lang = None if getattr(self, 'dictation_language', 'auto') == "auto" else self.dictation_language
            base_prompt = "Here is a transcription with correct capitalization, commas, and periods."
            vocab = getattr(self, 'custom_vocabulary', '').strip()
            if vocab:
                base_prompt += f" Vocabulary: {vocab}"
                
            segments, info = model.transcribe(
                audio_data, 
                language=lang,
                beam_size=1,
                vad_filter=False,
                initial_prompt=base_prompt
            )
            
            text = " ".join([segment.text for segment in segments])
            log("Transcription received")
            return text.strip()
        except Exception as e:
            log(f"Transcription error: {e}")
            return None

    def transcribe_file(self, filepath):
        engine = getattr(self, 'transcription_engine', 'local')
        if engine == 'groq':
            if not self.api_key:
                log("API key missing. Cannot use Groq for transcription.")
                return None
            try:
                import os
                from groq import Groq
                log(f"Transcribing file with Groq: {filepath}")
                client = Groq(api_key=self.api_key)
                lang = None if getattr(self, 'dictation_language', 'auto') == "auto" else self.dictation_language
                
                base_prompt = "Here is a transcription with correct capitalization, commas, and periods."
                vocab = getattr(self, 'custom_vocabulary', '').strip()
                if vocab:
                    base_prompt += f" Vocabulary: {vocab}"
                    
                kwargs = {
                    "file": (os.path.basename(filepath), open(filepath, "rb").read()),
                    "model": "whisper-large-v3-turbo",
                    "prompt": base_prompt,
                    "response_format": "text"
                }
                if lang:
                    kwargs["language"] = lang
                    
                transcription = client.audio.transcriptions.create(**kwargs)
                log("File transcription complete (Groq)")
                return transcription.strip()
            except Exception as e:
                log(f"Groq File transcription error: {e}")
                return None

        model = self._get_whisper_model()
        if not model:
            log("Cannot transcribe: faster_whisper not installed or model failed to load")
            return None
            
        try:
            log(f"Transcribing file locally: {filepath}")
            lang = None if getattr(self, 'dictation_language', 'auto') == "auto" else self.dictation_language
            base_prompt = "Here is a transcription with correct capitalization, commas, and periods."
            vocab = getattr(self, 'custom_vocabulary', '').strip()
            if vocab:
                base_prompt += f" Vocabulary: {vocab}"
                
            segments, info = model.transcribe(
                filepath, 
                language=lang,
                beam_size=1,
                vad_filter=True,
                initial_prompt=base_prompt
            )
            text = " ".join([segment.text for segment in segments])
            log("File transcription complete")
            return text.strip()
        except Exception as e:
            log(f"File transcription error: {e}")
            return None

    def _enhance_with_llm(self, text, prompt):
        if self.use_local_llm:
            log("Sending to Local Ollama LLM for polish...")
            try:
                import urllib.request
                import json
                
                url = "http://localhost:11434/api/chat"
                payload = {
                    "model": "llama3",
                    "messages": [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": text}
                    ],
                    "stream": False
                }
                req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(req, timeout=120) as response:
                    res_data = json.loads(response.read().decode('utf-8'))
                    polished = res_data.get('message', {}).get('content', '').strip()
                    log("Local AI polish complete.")
                    return polished
            except Exception as e:
                log(f"Local Ollama API Error: {e}")
                self.overlay.show_error("❌ Ollama Offline!")
                import time
                time.sleep(2.5)
                return None

        if not self.api_key:
            log("API key missing. Skipping AI enhancement.")
            self.overlay.show_error("❌ API Key Missing!")
            import time
            time.sleep(2.5)
            return None
        try:
            from groq import Groq
            client = Groq(api_key=self.api_key)
            log("Sending to Groq LLM for polish...")
            response = client.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": prompt
                    },
                    {
                        "role": "user",
                        "content": text
                    }
                ],
                model="llama3-8b-8192",
                temperature=0.0,
            )
            polished = response.choices[0].message.content.strip()
            log("AI polish complete.")
            return polished
        except Exception as e:
            log(f"Groq API Error: {e}")
            self.overlay.show_error("❌ Groq API Error!")
            import time
            time.sleep(2.5)
            return None

    def _type_text(self, text):
        try:
            # import pyperclip
            safe_clipboard_set(text + ' ')
            
            mode = getattr(self, 'output_mode', 'type')
            if mode == 'type':
                pyautogui.hotkey('ctrl', 'v')
            else:
                self.overlay.show_notification("📋 Copied to Clipboard!")
                
            self._update_analytics(text)
        except Exception as e:
            log(f"Type error: {e}")

    def _update_analytics(self, text):
        if not text:
            return
        words = len(text.split())
        analytics_file = os.path.expanduser('~/.voiceflow_analytics.json')
        try:
            if os.path.exists(analytics_file):
                with open(analytics_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            else:
                data = {'total_words': 0, 'sessions': 0}
            
            data['total_words'] += words
            data['sessions'] += 1
            
            with open(analytics_file, 'w', encoding='utf-8') as f:
                json.dump(data, f)
        except Exception as e:
            log(f"Failed to update analytics: {e}")

    def _trigger_ai_edit(self, prompt):
        self._is_ai_editing = True
        try:
            import winsound
            import sys, os
            if getattr(sys, 'frozen', False):
                b_dir = sys._MEIPASS
            else:
                b_dir = os.path.dirname(os.path.abspath(__file__))
            winsound.PlaySound(os.path.join(b_dir, 'static', 'sounds', 'start.wav'), winsound.SND_FILENAME | winsound.SND_ASYNC)
        except:
            pass
        self.overlay.set_state('ai_edit')
        log("AI Edit triggered on selected text...")
        
        try:
            # import pyperclip
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
                old_clipboard = safe_clipboard_get()
            except:
                old_clipboard = ""
            
            # Clear clipboard to detect if copy was successful
            safe_clipboard_set('')
            
            # Copy selected text
            log("Simulating Ctrl+C...")
            pyautogui.hotkey('ctrl', 'c')
            time.sleep(0.3)
            
            try:
                selected_text = safe_clipboard_get().strip()
            except:
                selected_text = ""
            
            if not selected_text:
                log("No text selected or copy failed!")
                safe_clipboard_set(old_clipboard)
                return
                
            log(f"Selected: \"{selected_text[:30]}...\"")
            
            new_text = self._enhance_with_llm(selected_text, prompt)
            
            if new_text is None:
                log("AI Edit aborted due to error.")
                safe_clipboard_set(old_clipboard)
                return
            
            # Paste the new text over the selection
            safe_clipboard_set(new_text)
            
            kb.release(Key.ctrl)
            kb.release(Key.shift)
            kb.release(Key.alt)
            
            log("Simulating Ctrl+V...")
            pyautogui.hotkey('ctrl', 'v')
            
            # Small delay to ensure paste happens before restoring old clipboard
            time.sleep(0.3)
            safe_clipboard_set(old_clipboard)
            
            try:
                import winsound
                import sys, os
                if getattr(sys, 'frozen', False):
                    b_dir = sys._MEIPASS
                else:
                    b_dir = os.path.dirname(os.path.abspath(__file__))
                winsound.PlaySound(os.path.join(b_dir, 'static', 'sounds', 'stop.wav'), winsound.SND_FILENAME | winsound.SND_ASYNC)
            except:
                pass
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
        
    def set_context_hotkey(self, key1, key2):
        k1 = _MODIFIER_MAP.get(key1.lower(), key1.lower())
        k2 = _MODIFIER_MAP.get(key2.lower(), key2.lower())
        self.context_hotkey = {k1, k2}
        self.keys_pressed.clear()
        log(f"Context hotkey set to: {self.context_hotkey}")

    def set_startup(self, enabled):
        self.run_at_startup = enabled
        import os, sys
        
        if getattr(sys, 'frozen', False):
            path = f'"{sys.executable}"'
            exe_path = sys.executable
        else:
            python_exe = sys.executable
            if sys.platform == 'win32' and python_exe.lower().endswith("python.exe"):
                python_exe = python_exe[:-10] + "pythonw.exe"
            path = f'"{python_exe}" "{os.path.abspath(sys.argv[0])}"'
            exe_path = f'{python_exe} {os.path.abspath(sys.argv[0])}'

        if sys.platform == 'win32':
            try:
                import winreg
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
                if enabled:
                    winreg.SetValueEx(key, "VoiceFlow", 0, winreg.REG_SZ, path)
                    log("Added to Windows Startup.")
                else:
                    try:
                        winreg.DeleteValue(key, "VoiceFlow")
                        log("Removed from Windows Startup.")
                    except FileNotFoundError:
                        pass
                winreg.CloseKey(key)
            except Exception as e:
                log(f"Failed to update Windows startup registry: {e}")
        elif sys.platform.startswith('linux'):
            try:
                autostart_dir = os.path.expanduser('~/.config/autostart')
                os.makedirs(autostart_dir, exist_ok=True)
                desktop_file = os.path.join(autostart_dir, 'VoiceFlow.desktop')
                
                if enabled:
                    content = f"""[Desktop Entry]
Type=Application
Exec={exe_path}
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Name=VoiceFlow
Comment=AI Dictation Everywhere
"""
                    with open(desktop_file, 'w') as f:
                        f.write(content)
                    log("Added to Linux Autostart.")
                else:
                    if os.path.exists(desktop_file):
                        os.remove(desktop_file)
                    log("Removed from Linux Autostart.")
            except Exception as e:
                log(f"Failed to update Linux autostart: {e}")

    def get_config(self):
        keys = list(self.hotkey)
        while len(keys) < 2:
            keys.append(keys[0] if keys else 'ctrl')
            
        c_keys = list(self.context_hotkey)
        while len(c_keys) < 2:
            c_keys.append(c_keys[0] if c_keys else 'shift')
            
        return {
            'status': self.status,
            'hotkey': keys[:2],
            'context_hotkey': c_keys[:2],
            'ai_presets': self.ai_presets,
            'api_key': self.api_key,
            'default_prompt': DEFAULT_PROMPT,
            'default_context_prompt': DEFAULT_CONTEXT_PROMPT,
            'context_prompt': getattr(self, 'context_prompt', DEFAULT_CONTEXT_PROMPT),
            'main_dictation_ai': getattr(self, 'main_dictation_ai', False),
            'run_at_startup': self.run_at_startup,
            'use_local_llm': getattr(self, 'use_local_llm', False),
            'transcription_engine': getattr(self, 'transcription_engine', 'local'),
            'custom_vocabulary': getattr(self, 'custom_vocabulary', ''),
            'context_aware_dictation': getattr(self, 'context_aware_dictation', False),
            'remove_filler_words': getattr(self, 'remove_filler_words', False),
            'output_mode': getattr(self, 'output_mode', 'type'),
            'dictation_language': getattr(self, 'dictation_language', 'auto')
        }
