import PyInstaller.__main__
import os
import sys

print("Building VoiceFlow...")

# Use the correct path separator for the current OS (; for Windows, : for Mac/Linux)
sep = os.pathsep

cmd = [
    'app.py',
    '--name=VoiceFlow',
    '--windowed', # Hide the terminal console
    '--onefile', # Make it a single executable
    '--icon=app.ico',
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
]

if sys.platform.startswith('linux'):
    cmd.extend([
        '--hidden-import=PyQt5',
        '--hidden-import=PyQtWebEngine',
        '--hidden-import=qtpy',
        '--collect-all=PyQt5',
        '--collect-all=qtpy'
    ])

PyInstaller.__main__.run(cmd)

print("Build complete! You can find the executable in the 'dist' folder.")
