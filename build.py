import PyInstaller.__main__
import os
import sys

print("Building VoiceFlow...")

# Use the correct path separator for the current OS (; for Windows, : for Mac/Linux)
sep = os.pathsep

PyInstaller.__main__.run([
    'app.py',
    '--name=VoiceFlow',
    '--windowed', # Hide the terminal console
    '--onefile', # Make it a single executable
    f'--add-data=templates{sep}templates', # Include templates folder
    f'--add-data=static{sep}static', # Include static folder
    '--hidden-import=pynput.keyboard._win32',
    '--hidden-import=pynput.mouse._win32',
    '--hidden-import=pynput.keyboard._darwin',
    '--hidden-import=pynput.mouse._darwin',
    '--hidden-import=pynput.keyboard._xorg',
    '--hidden-import=pynput.mouse._xorg',
    '--collect-all=faster_whisper',
    '--collect-all=ctranslate2',
    '--collect-all=tokenizers',
    '--collect-all=groq',
    '--collect-all=httpx',
    '--collect-all=pyperclip',
    '--collect-all=numpy',
    '--noconfirm',
    '--clean'
])

print("Build complete! You can find the executable in the 'dist' folder.")
