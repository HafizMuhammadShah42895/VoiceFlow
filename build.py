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
    '--collect-binaries=ctranslate2',
    '--collect-data=ctranslate2',
    # PyInstaller's normal hooks handle these imported packages. Using
    # collect-all here also discovers their optional ML/test integrations and
    # previously pulled TensorFlow, PyTorch, OpenCV, and IPython into the app.
    '--hidden-import=tokenizers',
    '--hidden-import=groq',
    '--hidden-import=httpx',
    '--hidden-import=pyperclip',
    '--hidden-import=keyring.backends.Windows',
    '--hidden-import=pystray',
    '--hidden-import=pystray._win32',
    '--hidden-import=pystray._darwin',
    '--hidden-import=pystray._xorg',
    '--exclude-module=torch',
    '--exclude-module=tensorflow',
    '--exclude-module=cv2',
    '--exclude-module=matplotlib',
    '--exclude-module=IPython',
    '--exclude-module=jedi',
    '--exclude-module=zmq',
    '--exclude-module=pandas',
    '--exclude-module=scipy',
    '--exclude-module=numba',
    '--exclude-module=llvmlite',
    '--exclude-module=openpyxl',
    '--exclude-module=lxml',
    '--exclude-module=sqlalchemy',
    '--exclude-module=transformers',
    '--exclude-module=timm',
    '--exclude-module=torchvision',
    '--exclude-module=h5py',
    '--exclude-module=soundfile',
    '--exclude-module=yt_dlp',
    '--exclude-module=pydub',
    '--exclude-module=uvicorn',
    '--exclude-module=rich',
    '--exclude-module=dns',
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
