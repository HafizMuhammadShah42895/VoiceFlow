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

@app.route('/api/status')
def get_status():
    return jsonify(agent.get_config())

@app.route('/api/config', methods=['POST'])
def set_config():
    data = request.get_json()
    if data:
        if 'key1' in data and 'key2' in data:
            agent.set_hotkey(data['key1'], data['key2'])
        if 'ai_key1' in data and 'ai_key2' in data:
            agent.set_ai_hotkey(data['ai_key1'], data['ai_key2'])
        if 'api_key' in data:
            agent.api_key = data['api_key']
        if 'custom_prompt' in data:
            agent.custom_prompt = data['custom_prompt']
        if 'run_at_startup' in data:
            agent.set_startup(data['run_at_startup'])
            
        agent.save_config()
        return jsonify({'ok': True, 'hotkey': list(agent.hotkey)})
    return jsonify({'ok': False, 'error': 'Invalid payload'}), 400

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
    
    # Create the native desktop window
    window = webview.create_window('VoiceFlow Dashboard', 'http://127.0.0.1:5000', width=600, height=750, min_size=(600, 750))
    
    # Start the webview application
    webview.start()
    
    # Stop agent when the window is closed
    agent.stop()
    sys.exit(0)
