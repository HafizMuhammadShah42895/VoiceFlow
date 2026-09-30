import sys
import os

# Prevent crash in --windowed mode on Windows where stdout/stderr are None
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

import hmac
import secrets

from flask import Flask, render_template, jsonify, request
from dictation_agent import DictationAgent, safe_clipboard_set
from voiceflow_core import SingleInstance, SystemTray, APP_VERSION, is_newer_version

if getattr(sys, 'frozen', False):
    base_dir = sys._MEIPASS
else:
    base_dir = os.path.dirname(os.path.abspath(__file__))

HOST = '127.0.0.1'
PORT = 5000
# Browsers always send the port for a non-default port, so a DNS-rebinding page
# (Host: attacker.example:5000) can never match these.
ALLOWED_HOSTS = {f'{HOST}:{PORT}', f'localhost:{PORT}'}
# Per-launch secret embedded in the dashboard HTML. Other web pages cannot read
# that HTML (same-origin policy) and cannot attach a custom header to a
# cross-origin request without a CORS preflight, which this server never grants.
API_TOKEN = secrets.token_urlsafe(32)
TOKEN_HEADER = 'X-VoiceFlow-Token'
RELEASES_URL = "https://github.com/HafizMuhammadShah42895/VoiceFlow/releases"

app = Flask(
    __name__,
    template_folder=os.path.join(base_dir, 'templates'),
    static_folder=os.path.join(base_dir, 'static')
)
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024  # 1 GiB local file limit

agent = DictationAgent()


@app.before_request
def protect_local_api():
    if request.host not in ALLOWED_HOSTS:
        return jsonify({'ok': False, 'error': 'Forbidden host'}), 403
    if request.path.startswith('/api/'):
        supplied = request.headers.get(TOKEN_HEADER, '')
        if not hmac.compare_digest(supplied, API_TOKEN):
            return jsonify({'ok': False, 'error': 'Missing or invalid API token'}), 403
    return None


@app.after_request
def disable_caching(response):
    # Pages carry the per-launch token; never let a stale copy be reused.
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.route('/')
def index():
    return render_template('index.html', app_version=APP_VERSION, api_token=API_TOKEN)

@app.route('/mini')
def mini():
    return render_template('mini.html', api_token=API_TOKEN)

@app.route('/api/status')
def get_status():
    return jsonify(agent.get_config())

@app.route('/api/config', methods=['POST'])
def set_config():
    data = request.get_json(silent=True)
    try:
        agent.update_config(data)
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
    return jsonify({'ok': True, 'hotkey': list(agent.hotkey)})

@app.route('/api/check_update')
def check_update():
    try:
        import urllib.request
        import json
        req = urllib.request.Request(
            "https://api.github.com/repos/HafizMuhammadShah42895/VoiceFlow/releases/latest",
            headers={"User-Agent": "VoiceFlow-Desktop"}
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        latest_tag = data.get("tag_name", "").lstrip("v")
        return jsonify({
            "ok": True,
            "update_available": is_newer_version(latest_tag, APP_VERSION),
            "latest_version": latest_tag,
            "current_version": APP_VERSION,
            "release_url": data.get("html_url", RELEASES_URL)
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "update_available": False, "current_version": APP_VERSION})

@app.route('/api/transcribe_file', methods=['POST'])
def transcribe_file_api():
    if 'file' not in request.files:
        return jsonify({'ok': False, 'error': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'ok': False, 'error': 'No selected file'}), 400
    if file:
        import tempfile
        extension = os.path.splitext(file.filename)[1].lower()
        if not extension or len(extension) > 10 or not extension[1:].isalnum():
            extension = '.audio'
        descriptor, filepath = tempfile.mkstemp(prefix='voiceflow-upload-', suffix=extension)
        os.close(descriptor)
        try:
            file.save(filepath)
            text = agent.transcribe_file(filepath)
        finally:
            try:
                os.remove(filepath)
            except OSError:
                pass

        if text:
            return jsonify({'ok': True, 'text': text})
        else:
            return jsonify({'ok': False, 'error': 'Transcription failed'}), 500

@app.route('/api/analytics', methods=['GET'])
def get_analytics():
    return jsonify(agent.get_analytics())

@app.route('/api/history', methods=['GET', 'DELETE'])
def get_history():
    try:
        if request.method == 'DELETE':
            return jsonify({'ok': True, 'deleted': agent.clear_history()})
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)
        query = request.args.get('q', '', type=str)
        return jsonify({'ok': True, 'items': agent.get_history(limit, offset, query)})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/history/<job_id>', methods=['GET', 'DELETE'])
def history_item(job_id):
    if request.method == 'DELETE':
        try:
            if agent.delete_history_item(job_id):
                return jsonify({'ok': True})
            return jsonify({'ok': False, 'error': 'History item not found'}), 404
        except Exception as e:
            return jsonify({'ok': False, 'error': str(e)}), 500

    item = agent.get_history_item(job_id)
    if not item:
        return jsonify({'ok': False, 'error': 'History item not found'}), 404
    return jsonify({'ok': True, 'item': item})

@app.route('/api/history/<job_id>/copy', methods=['POST'])
def copy_history_item(job_id):
    if agent.copy_history_item(job_id):
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': 'No transcript text was available to copy'}), 404

@app.route('/api/history/<job_id>/paste', methods=['POST'])
def paste_history_item(job_id):
    if agent.paste_history_item(job_id):
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': 'VoiceFlow could not paste this transcript'}), 409

@app.route('/api/history/<job_id>/retry', methods=['POST'])
def retry_history_item(job_id):
    item = agent.retry_history_item(job_id)
    if item:
        return jsonify({'ok': item.get('status') == 'completed', 'item': item})
    return jsonify({'ok': False, 'error': 'No recoverable audio is available for this transcript'}), 409

@app.route('/api/history/latest/copy', methods=['POST'])
def copy_latest_history_item():
    if agent.copy_history_item():
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': 'There is no transcript to copy yet'}), 404

@app.route('/api/history/latest/paste', methods=['POST'])
def paste_latest_history_item():
    if agent.paste_history_item():
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': 'There is no transcript to paste yet'}), 404


def install_linux_desktop_entry():
    """Create/refresh the application-menu shortcut on Linux desktops."""
    import shutil
    apps_dir = os.path.expanduser('~/.local/share/applications')
    icons_dir = os.path.expanduser('~/.local/share/icons')
    os.makedirs(apps_dir, exist_ok=True)
    os.makedirs(icons_dir, exist_ok=True)

    desktop_file = os.path.join(apps_dir, 'VoiceFlow.desktop')
    icon_dest = os.path.join(icons_dir, 'voiceflow_icon.png')

    icon_src = os.path.join(base_dir, 'static', 'img', 'logo_final.png')
    if os.path.exists(icon_src):
        shutil.copy2(icon_src, icon_dest)

    if getattr(sys, 'frozen', False):
        exec_line = f'"{os.path.abspath(sys.executable)}"'
    else:
        # Each argument is quoted separately; quoting both together makes the
        # launcher look for a single executable named "python app.py".
        exec_line = f'"{sys.executable}" "{os.path.abspath(sys.argv[0])}"'

    content = f"""[Desktop Entry]
Type=Application
Name=VoiceFlow
Comment=AI Dictation Everywhere
Exec={exec_line}
Icon={icon_dest}
Terminal=false
Categories=Utility;
"""
    with open(desktop_file, 'w') as f:
        f.write(content)


if __name__ == '__main__':
    import threading
    import multiprocessing
    import webview

    multiprocessing.freeze_support()

    # Phase 1: Single Instance Mutex Protection
    single_instance = SingleInstance("VoiceFlow_SingleInstance_Mutex")
    if single_instance.is_running:
        print("[VoiceFlow] Another instance is already running. Bringing it to focus.")
        single_instance.focus_existing_window("VoiceFlow Dashboard")
        sys.exit(0)

    agent.start()

    def run_flask():
        app.run(debug=False, host=HOST, port=PORT, use_reloader=False)

    # Start Flask server in a background thread
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()

    base_url = f'http://{HOST}:{PORT}'

    class Api:
        def __init__(self):
            self._main_window = None
            self._mini_window = None

        def switch_to_mini(self):
            if self._main_window:
                self._main_window.hide()
            if not self._mini_window:
                self._mini_window = webview.create_window(
                    'VoiceFlow Mini',
                    f'{base_url}/mini',
                    width=220,
                    height=120,
                    frameless=True,
                    on_top=True,
                    easy_drag=True,
                    text_select=True,
                    js_api=self
                )
            else:
                self._mini_window.show()

        def switch_to_main(self):
            if self._mini_window:
                self._mini_window.hide()
            if self._main_window:
                self._main_window.show()

        def copy_text(self, text):
            """Reliable clipboard fallback for the embedded browser UI."""
            if not isinstance(text, str):
                return False
            return safe_clipboard_set(text)

        def copy_last_transcript(self):
            return agent.copy_history_item()

        def paste_last_transcript(self):
            return agent.paste_history_item()

        def quit_app(self):
            quit_voiceflow()

    api = Api()

    main_window = webview.create_window(
        'VoiceFlow Dashboard',
        base_url,
        width=600,
        height=750,
        min_size=(600, 750),
        text_select=True,
        js_api=api
    )
    api._main_window = main_window

    is_quitting = False

    def quit_voiceflow():
        global is_quitting
        is_quitting = True
        try:
            tray.stop()
        except Exception:
            pass
        try:
            agent.stop()
        except Exception:
            pass
        try:
            single_instance.release()
        except Exception:
            pass
        try:
            main_window.destroy()
        except Exception:
            pass
        os._exit(0)

    def on_closing():
        if not is_quitting:
            # Minimize to tray instead of quitting!
            main_window.hide()
            return False
        return True

    def on_closed():
        quit_voiceflow()

    main_window.events.closing += on_closing
    main_window.events.closed += on_closed

    # Phase 3: System Tray
    def open_dashboard():
        if main_window:
            main_window.show()
            main_window.restore()

    def check_for_updates():
        open_dashboard()
        try:
            main_window.evaluate_js('window.checkAppUpdates && window.checkAppUpdates(true)')
        except Exception as e:
            print(f"Could not start update check: {e}")

    tray = SystemTray(
        on_open_dashboard=open_dashboard,
        on_toggle_pause=agent.toggle_pause,
        on_copy_last=agent.copy_history_item,
        on_paste_last=agent.paste_history_item,
        on_undo_voice_edit=agent.undo_last_voice_edit,
        on_check_updates=check_for_updates,
        on_quit=quit_voiceflow,
        is_paused_fn=lambda: agent.is_paused,
    )
    tray.start()

    if sys.platform.startswith('linux'):
        if os.environ.get('XDG_SESSION_TYPE', '').lower() == 'wayland':
            print("\n[WARNING] Wayland display server detected!")
            print("Global hotkeys (like Alt+Shift) may not work on Wayland due to security restrictions.")
            print("If dictation hotkeys fail, please switch to an 'Xorg / X11' session at your login screen.\n")

        try:
            install_linux_desktop_entry()
        except Exception as e:
            print(f"Failed to create Linux app shortcut: {e}")

    # Start the webview application
    icon_path = os.path.join(base_dir, 'static', 'img', 'logo_icon.ico')
    webview.start(icon=icon_path)

    # Fallback cleanup
    quit_voiceflow()
