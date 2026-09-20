(function() {
    'use strict';

    const hotkey1 = document.getElementById('hotkey-1');
    const hotkey2 = document.getElementById('hotkey-2');
    const contextHotkey1 = document.getElementById('context-hotkey-1');
    const contextHotkey2 = document.getElementById('context-hotkey-2');
    const contextPrompt = document.getElementById('context-prompt');
    const resetContextPromptBtn = document.getElementById('reset-context-prompt-btn');
    const mainDictationAiToggle = document.getElementById('main-dictation-ai-toggle');
    const apiKey = document.getElementById('api-key');
    const startupToggle = document.getElementById('startup-toggle');
    const languageSelect = document.getElementById('language-select');
    const transcriptionEngineSelect = document.getElementById('transcription-engine-select');
    const customVocabulary = document.getElementById('custom-vocabulary');
    const outputModeSelect = document.getElementById('output-mode-select');
    const contextAwareSelect = document.getElementById('context-aware-select');
    const fillerWordsToggle = document.getElementById('filler-words-toggle');
    const localLlmToggle = document.getElementById('local-llm-toggle');
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
                    <select class="input-field p-key-1" data-idx="${index}">
                        <option value="alt" ${k1==='alt'?'selected':''}>Alt</option>
                        <option value="shift" ${k1==='shift'?'selected':''}>Shift</option>
                        <option value="ctrl" ${k1==='ctrl'?'selected':''}>Ctrl</option>
                        <option value="cmd" ${k1==='cmd'?'selected':''}>Win</option>
                    </select>
                    <span class="plus">+</span>
                    <select class="input-field p-key-2" data-idx="${index}">
                        <option value="alt" ${k2==='alt'?'selected':''}>Alt</option>
                        <option value="shift" ${k2==='shift'?'selected':''}>Shift</option>
                        <option value="ctrl" ${k2==='ctrl'?'selected':''}>Ctrl</option>
                        <option value="space" ${k2==='space'?'selected':''}>Space</option>
                    </select>
                </div>
                <textarea class="input-field prompt-area preset-prompt-input" rows="3" data-idx="${index}">${preset.prompt}</textarea>
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
                if (data.hotkey && data.hotkey.length >= 2) {
                    hotkey1.value = data.hotkey[0];
                    hotkey2.value = data.hotkey[1];
                }
                if (data.context_hotkey && data.context_hotkey.length >= 2 && contextHotkey1) {
                    contextHotkey1.value = data.context_hotkey[0];
                    contextHotkey2.value = data.context_hotkey[1];
                }
                if (data.api_key !== undefined) {
                    apiKey.value = data.api_key;
                }
                if (data.run_at_startup !== undefined && startupToggle) {
                    startupToggle.checked = data.run_at_startup;
                }
                if (data.use_local_llm !== undefined && localLlmToggle) {
                    localLlmToggle.checked = data.use_local_llm;
                }
                if (data.transcription_engine !== undefined && transcriptionEngineSelect) {
                    transcriptionEngineSelect.value = data.transcription_engine;
                }
                if (data.custom_vocabulary !== undefined && customVocabulary) {
                    customVocabulary.value = data.custom_vocabulary;
                }
                if (data.context_aware_dictation !== undefined && contextAwareSelect) {
                    contextAwareSelect.value = data.context_aware_dictation ? "true" : "false";
                }
                if (data.output_mode !== undefined && outputModeSelect) {
                    outputModeSelect.value = data.output_mode;
                }
                if (data.remove_filler_words !== undefined && fillerWordsToggle) {
                    fillerWordsToggle.checked = data.remove_filler_words;
                }
                if (data.main_dictation_ai !== undefined && mainDictationAiToggle) {
                    mainDictationAiToggle.checked = data.main_dictation_ai;
                }
                if (data.dictation_language !== undefined && languageSelect) {
                    languageSelect.value = data.dictation_language;
                }
                if (data.context_prompt !== undefined && contextPrompt) {
                    contextPrompt.value = data.context_prompt;
                    
                    if (resetContextPromptBtn) {
                        resetContextPromptBtn.onclick = function(e) {
                            e.preventDefault();
                            contextPrompt.value = data.default_context_prompt;
                        };
                    }
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
        const ck1 = contextHotkey1 ? contextHotkey1.value : 'ctrl';
        const ck2 = contextHotkey2 ? contextHotkey2.value : 'shift';
        const key = apiKey.value.trim();
        const runAtStartup = startupToggle ? startupToggle.checked : true;
        const useLocalLlm = localLlmToggle ? localLlmToggle.checked : false;
        const transcriptionEngine = transcriptionEngineSelect ? transcriptionEngineSelect.value : "local";
        const customVocab = customVocabulary ? customVocabulary.value : "";
        const outputMode = outputModeSelect ? outputModeSelect.value : "type";
        const removeFillerWords = fillerWordsToggle ? fillerWordsToggle.checked : false;
        const mainDictationAi = mainDictationAiToggle ? mainDictationAiToggle.checked : false;
        const lang = languageSelect ? languageSelect.value : "auto";
        const cp = contextPrompt ? contextPrompt.value : "";

        fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                key1: k1, key2: k2, 
                context_key1: ck1,
                context_key2: ck2,
                api_key: key, 
                run_at_startup: runAtStartup,
                use_local_llm: useLocalLlm,
                transcription_engine: transcriptionEngine,
                custom_vocabulary: customVocab,
                output_mode: outputMode,
                remove_filler_words: removeFillerWords,
                main_dictation_ai: mainDictationAi,
                context_prompt: cp,
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
