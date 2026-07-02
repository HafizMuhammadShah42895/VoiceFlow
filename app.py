import sys
import os

# Prevent crash in --windowed mode on Windows where stdout/stderr are None
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

from flask import Flask, render_template, jsonify, request
from dictation_agent import DictationAgent

if getattr(sys, 'frozen', False):
    base_dir = sys._MEIPASS
else:
    base_dir = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__, 
            template_folder=os.path.join(base_dir, 'templates'),
            static_folder=os.path.join(base_dir, 'static'))

agent = DictationAgent()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/mini')
def mini():
    return render_template('mini.html')

@app.route('/api/status')
def get_status():
    return jsonify(agent.get_config())

@app.route('/api/config', methods=['POST'])
def set_config():
    try:
        data = request.get_json()
        if data:
            if 'key1' in data and 'key2' in data:
                agent.set_hotkey(data['key1'], data['key2'])
            if 'ai_presets' in data:
                agent.ai_presets = data['ai_presets']
            if 'api_key' in data:
                agent.api_key = data['api_key']
            if 'run_at_startup' in data:
                agent.set_startup(data['run_at_startup'])
            if 'dictation_language' in data:
                agent.dictation_language = data['dictation_language']
            if 'use_local_llm' in data:
                agent.use_local_llm = data['use_local_llm']
                
            agent.save_config()
            return jsonify({'ok': True, 'hotkey': list(agent.hotkey)})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 400

@app.route('/api/transcribe_file', methods=['POST'])
def transcribe_file_api():
    if 'file' not in request.files:
        return jsonify({'ok': False, 'error': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'ok': False, 'error': 'No selected file'}), 400
    if file:
        import tempfile
        import os
        temp_dir = tempfile.gettempdir()
        filepath = os.path.join(temp_dir, file.filename)
        file.save(filepath)
        
        text = agent.transcribe_file(filepath)
        
        try:
            os.remove(filepath)
        except:
            pass
            
        if text:
            return jsonify({'ok': True, 'text': text})
        else:
            return jsonify({'ok': False, 'error': 'Transcription failed'}), 500

@app.route('/api/analytics', methods=['GET'])
def get_analytics():
    import os, json
    analytics_file = os.path.expanduser('~/.voiceflow_analytics.json')
    try:
        if os.path.exists(analytics_file):
            with open(analytics_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        else:
            data = {'total_words': 0, 'sessions': 0}
        return jsonify(data)
    except:
        return jsonify({'total_words': 0, 'sessions': 0})

import webview
import threading
import sys

import multiprocessing

if __name__ == '__main__':
    multiprocessing.freeze_support()
    agent.start()
    
    def run_flask():
        app.run(debug=False, host='127.0.0.1', port=5000, use_reloader=False)

    # Start Flask server in a background thread
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()
    
    class Api:
        def __init__(self):
            self._main_window = None
            self._mini_window = None

        def switch_to_mini(self):
            if self._main_window:
                self._main_window.hide()
            if not self._mini_window:
                self._mini_window = webview.create_window('VoiceFlow Mini', 'http://127.0.0.1:5000/mini', width=220, height=120, frameless=True, on_top=True, easy_drag=True, js_api=self)
            else:
                self._mini_window.show()

        def switch_to_main(self):
            if self._mini_window:
                self._mini_window.hide()
            if self._main_window:
                self._main_window.show()

    api = Api()

    main_window = webview.create_window('VoiceFlow Dashboard', 'http://127.0.0.1:5000', width=600, height=750, min_size=(600, 750), js_api=api)
    api._main_window = main_window
    
    def on_closed():
        agent.stop()
        os._exit(0)
        
    main_window.events.closed += on_closed
    
    # Start the webview application
    webview.start()
    
    # Fallback stop
    agent.stop()
    os._exit(0)
