(function() {
    'use strict';

    const hotkey1 = document.getElementById('hotkey-1');
    const hotkey2 = document.getElementById('hotkey-2');
    const apiKey = document.getElementById('api-key');
    const startupSelect = document.getElementById('startup-select');
    const languageSelect = document.getElementById('language-select');
    const localLlmSelect = document.getElementById('local-llm-select');
    const hotkeySave = document.getElementById('hotkey-save');
    const statusDot = document.getElementById('status-dot');
    const statusText = document.getElementById('status-text');
    const toast = document.getElementById('toast');
    const statWords = document.getElementById('stat-words');
    const statTime = document.getElementById('stat-time');
    const presetsContainer = document.getElementById('presets-container');
    const addPresetBtn = document.getElementById('add-preset-btn');

    let pollInterval = null;
    let presetsData = [];

    function init() {
        loadHotkeyConfig();
        loadAnalytics();
        bindEvents();
        startStatusPolling();
    }

    function showToast(message) {
        toast.textContent = message;
        toast.classList.add('show');
        clearTimeout(toast._hideTimer);
        toast._hideTimer = setTimeout(() => {
            toast.classList.remove('show');
        }, 2500);
    }

    function renderPresets() {
        if (!presetsContainer) return;
        presetsContainer.innerHTML = '';
        presetsData.forEach((preset, index) => {
            const card = document.createElement('div');
            card.className = 'preset-card';
            
            const k1 = preset.hotkeys && preset.hotkeys.length > 0 ? preset.hotkeys[0] : 'ctrl';
            const k2 = preset.hotkeys && preset.hotkeys.length > 1 ? preset.hotkeys[1] : 'shift';

            card.innerHTML = `
                <div class="preset-header">
                    <input type="text" class="preset-title-input" value="${preset.name}" data-idx="${index}">
                    <button class="remove-preset-btn" data-idx="${index}">Remove</button>
                </div>
                <div class="hotkey-inputs">
                    <select class="hotkey-select p-key-1" data-idx="${index}">
                        <option value="alt" ${k1==='alt'?'selected':''}>Alt</option>
                        <option value="shift" ${k1==='shift'?'selected':''}>Shift</option>
                        <option value="ctrl" ${k1==='ctrl'?'selected':''}>Ctrl</option>
                        <option value="cmd" ${k1==='cmd'?'selected':''}>Win</option>
                    </select>
                    <span class="plus">+</span>
                    <select class="hotkey-select p-key-2" data-idx="${index}">
                        <option value="alt" ${k2==='alt'?'selected':''}>Alt</option>
                        <option value="shift" ${k2==='shift'?'selected':''}>Shift</option>
                        <option value="ctrl" ${k2==='ctrl'?'selected':''}>Ctrl</option>
                        <option value="space" ${k2==='space'?'selected':''}>Space</option>
                    </select>
                </div>
                <textarea class="prompt-area preset-prompt-input" rows="3" data-idx="${index}">${preset.prompt}</textarea>
            `;
            presetsContainer.appendChild(card);
        });
    }

    function loadAnalytics() {
        fetch('/api/analytics')
            .then(r => r.json())
            .then(data => {
                if (data.total_words !== undefined && statWords) {
                    statWords.textContent = data.total_words.toLocaleString();
                    const minutesSaved = Math.round(data.total_words / 40);
                    if (minutesSaved > 60) {
                        const hours = Math.floor(minutesSaved / 60);
                        const mins = minutesSaved % 60;
                        statTime.textContent = hours + 'h ' + mins + 'm';
                    } else {
                        statTime.textContent = minutesSaved + 'm';
                    }
                }
            })
            .catch(() => {});
    }

    function loadHotkeyConfig() {
        fetch('/api/status')
            .then(r => r.json())
            .then(data => {
                if (data.hotkey && data.hotkey.length === 2) {
                    hotkey1.value = data.hotkey[0];
                    hotkey2.value = data.hotkey[1];
                }
                if (data.api_key !== undefined) {
                    apiKey.value = data.api_key;
                }
                if (data.run_at_startup !== undefined) {
                    startupSelect.value = data.run_at_startup ? "true" : "false";
                }
                if (data.use_local_llm !== undefined) {
                    localLlmSelect.value = data.use_local_llm ? "true" : "false";
                }
                if (data.dictation_language !== undefined) {
                    languageSelect.value = data.dictation_language;
                }
                if (data.ai_presets !== undefined) {
                    presetsData = data.ai_presets;
                    renderPresets();
                }
            })
            .catch(() => {});
    }

    function saveHotkeyConfig() {
        const k1 = hotkey1.value || 'alt';
        const k2 = hotkey2.value || 'shift';
        if (k1 === k2) {
            showToast('Keys must be different');
            return;
        }
        const key = apiKey.value.trim();
        const runAtStartup = startupSelect.value === "true";
        const useLocalLlm = localLlmSelect.value === "true";
        const lang = languageSelect.value;

        fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                key1: k1, key2: k2, 
                api_key: key, 
                run_at_startup: runAtStartup,
                use_local_llm: useLocalLlm,
                dictation_language: lang,
                ai_presets: presetsData
            })
        })
        .then(r => r.json())
        .then(data => {
            if (data.ok) {
                showToast('Settings successfully applied!');
            }
        })
        .catch(() => {
            showToast('Failed to update settings');
        });
    }

    function startStatusPolling() {
        pollInterval = setInterval(function() {
            fetch('/api/status')
                .then(r => r.json())
                .then(data => {
                    updateStatusUI(data.status);
                })
                .catch(() => {});
                
            // Update analytics dynamically
            loadAnalytics();
        }, 1000);
    }

    function updateStatusUI(status) {
        statusDot.className = 'status-dot';
        if (status === 'listening') {
            statusDot.classList.add('listening');
            statusText.textContent = 'Listening...';
        } else if (status === 'processing') {
            statusDot.classList.add('processing');
            statusText.textContent = 'Processing...';
        } else if (status === 'ai_edit') {
            statusDot.classList.add('ai_edit');
            statusText.textContent = 'AI Polish...';
        } else if (status === 'loading_model') {
            statusDot.classList.add('loading');
            statusText.textContent = 'Loading AI model...';
        } else {
            statusText.textContent = 'Ready';
        }
    }

    function bindEvents() {
        hotkeySave.addEventListener('click', saveHotkeyConfig);
        
        if (addPresetBtn) {
            addPresetBtn.addEventListener('click', (e) => {
                e.preventDefault();
                presetsData.push({
                    id: 'preset_' + Date.now(),
                    name: 'New Polish Preset',
                    hotkeys: ['ctrl', 'space'],
                    prompt: 'Fix grammar and structural errors in the following text.'
                });
                renderPresets();
            });
        }

        if (presetsContainer) {
            presetsContainer.addEventListener('input', (e) => {
                const idx = e.target.getAttribute('data-idx');
                if (idx === null) return;
                if (e.target.classList.contains('preset-title-input')) {
                    presetsData[idx].name = e.target.value;
                } else if (e.target.classList.contains('preset-prompt-input')) {
                    presetsData[idx].prompt = e.target.value;
                } else if (e.target.classList.contains('p-key-1')) {
                    presetsData[idx].hotkeys[0] = e.target.value;
                } else if (e.target.classList.contains('p-key-2')) {
                    presetsData[idx].hotkeys[1] = e.target.value;
                }
            });

            presetsContainer.addEventListener('click', (e) => {
                if (e.target.classList.contains('remove-preset-btn')) {
                    const idx = e.target.getAttribute('data-idx');
                    presetsData.splice(idx, 1);
                    renderPresets();
                }
            });
        }

        window.addEventListener('beforeunload', function() {
            if (pollInterval) clearInterval(pollInterval);
        });

        // File Upload Handlers
        const dropZone = document.getElementById('drop-zone');
        const fileInput = document.getElementById('file-upload');
        const uploadStatus = document.getElementById('upload-status');
        const transcriptContainer = document.getElementById('transcript-container');
        const transcriptResult = document.getElementById('transcript-result');
        const uploadStatusText = document.getElementById('upload-status-text');

        window.copyTranscript = function() {
            if (transcriptResult && transcriptResult.value) {
                navigator.clipboard.writeText(transcriptResult.value).then(() => {
                    showToast('Transcript copied to clipboard!');
                }).catch(() => {
                    showToast('Failed to copy');
                });
            }
        };

        if (dropZone) {
            ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
                dropZone.addEventListener(eventName, preventDefaults, false);
            });

            function preventDefaults(e) {
                e.preventDefault();
                e.stopPropagation();
            }

            ['dragenter', 'dragover'].forEach(eventName => {
                dropZone.addEventListener(eventName, () => dropZone.classList.add('dragover'), false);
            });

            ['dragleave', 'drop'].forEach(eventName => {
                dropZone.addEventListener(eventName, () => dropZone.classList.remove('dragover'), false);
            });

            dropZone.addEventListener('drop', handleDrop, false);
            if(fileInput) {
                fileInput.addEventListener('change', function() {
                    if(this.files.length) handleFiles(this.files);
                });
            }

            function handleDrop(e) {
                let dt = e.dataTransfer;
                let files = dt.files;
                handleFiles(files);
            }

            function handleFiles(files) {
                if (!files.length) return;
                uploadFile(files[0]);
            }

            function uploadFile(file) {
                uploadStatus.style.display = 'flex';
                if(uploadStatusText) uploadStatusText.innerText = `Processing ${file.name}... this may take a few minutes for long audio.`;
                transcriptContainer.style.display = 'none';

                let formData = new FormData();
                formData.append('file', file);

                fetch('/api/transcribe_file', {
                    method: 'POST',
                    body: formData
                })
                .then(response => response.json())
                .then(data => {
                    if (data.ok) {
                        uploadStatus.style.display = 'none';
                        transcriptContainer.style.display = 'block';
                        transcriptResult.value = data.text;
                    } else {
                        if(uploadStatusText) uploadStatusText.innerText = 'Error: ' + data.error;
                    }
                })
                .catch(error => {
                    if(uploadStatusText) uploadStatusText.innerText = 'Error: ' + error.message;
                });
            }
        }
    }

    window.switchToMini = function() {
        if (window.pywebview && window.pywebview.api) {
            window.pywebview.api.switch_to_mini();
        } else {
            console.log("PyWebView API not available.");
        }
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
