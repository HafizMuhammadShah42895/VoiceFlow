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
    const clearApiKey = document.getElementById('clear-api-key');
    const startupToggle = document.getElementById('startup-toggle');
    const languageSelect = document.getElementById('language-select');
    const transcriptionEngineSelect = document.getElementById('transcription-engine-select');
    const customVocabulary = document.getElementById('custom-vocabulary');
    const writingStyleSelect = document.getElementById('writing-style-select');
    const textReplacements = document.getElementById('text-replacements');
    const voiceSnippets = document.getElementById('voice-snippets');
    const outputModeSelect = document.getElementById('output-mode-select');
    const appAwareToggle = document.getElementById('app-aware-toggle');
    const triggerModeSelect = document.getElementById('trigger-mode-select');
    const silenceAutoStopToggle = document.getElementById('silence-auto-stop-toggle');
    const silenceTimeoutSelect = document.getElementById('silence-timeout-select');
    const historyRetentionSelect = document.getElementById('history-retention-select');
    const localLlmToggle = document.getElementById('local-llm-toggle');
    const hotkeySave = document.getElementById('hotkey-save');
    const statusDot = document.getElementById('status-dot');
    const statusText = document.getElementById('status-text');
    const toast = document.getElementById('toast');
    const statWords = document.getElementById('stat-words');
    const statTime = document.getElementById('stat-time');
    const presetsContainer = document.getElementById('presets-container');
    const addPresetBtn = document.getElementById('add-preset-btn');
    const historyList = document.getElementById('history-list');
    const historyEmpty = document.getElementById('history-empty');
    const historySearch = document.getElementById('history-search');
    const historyRefresh = document.getElementById('history-refresh');
    const historyClear = document.getElementById('history-clear');
    const copyLastTranscript = document.getElementById('copy-last-transcript');
    const onboardingModal = document.getElementById('onboarding-modal');
    const onboardingFinish = document.getElementById('onboarding-finish');

    const tokenMeta = document.querySelector('meta[name="voiceflow-token"]');
    const API_TOKEN = tokenMeta ? tokenMeta.content : '';

    // Every /api call must carry the per-launch token; the server rejects others.
    function apiFetch(url, options = {}) {
        const headers = new Headers(options.headers || {});
        headers.set('X-VoiceFlow-Token', API_TOKEN);
        return fetch(url, { ...options, headers });
    }

    let pollInterval = null;
    let lastStatus = null;
    let mainHotkeyKeys = ['alt', 'shift'];
    let presetsData = [];
    let historyData = [];
    let historySearchTimer = null;
    let apiKeyConfigured = false;

    function init() {
        loadHotkeyConfig();
        loadAnalytics();
        loadHistory();
        bindEvents();
        startStatusPolling();
        checkAppUpdates();
    }

    function showToast(message) {
        toast.textContent = message;
        toast.classList.add('show');
        clearTimeout(toast._hideTimer);
        toast._hideTimer = setTimeout(() => {
            toast.classList.remove('show');
        }, 2500);
    }

    async function copyText(text) {
        if (!text) return false;

        try {
            if (navigator.clipboard && navigator.clipboard.writeText) {
                await navigator.clipboard.writeText(text);
                return true;
            }
        } catch (_) {
            // Installed WebViews may deny the browser clipboard API. Fall back
            // to the native Python bridge exposed by the desktop window.
        }

        try {
            if (window.pywebview && window.pywebview.api && window.pywebview.api.copy_text) {
                return Boolean(await window.pywebview.api.copy_text(text));
            }
        } catch (_) {}

        return false;
    }

    function escapeHtml(value) {
        return String(value ?? '')
            .replaceAll('&', '&amp;')
            .replaceAll('<', '&lt;')
            .replaceAll('>', '&gt;')
            .replaceAll('"', '&quot;')
            .replaceAll("'", '&#039;');
    }

    function historyItemText(item) {
        return (item && (item.final_text || item.raw_text) || '').trim();
    }

    function formatHistoryDate(value) {
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return 'Unknown time';
        return date.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
    }

    function renderHistory() {
        if (!historyList || !historyEmpty) return;
        historyList.replaceChildren();
        historyEmpty.style.display = historyData.length ? 'none' : 'block';

        historyData.forEach(item => {
            const card = document.createElement('article');
            card.className = 'history-item';
            card.dataset.historyId = item.id;

            const header = document.createElement('div');
            header.className = 'history-item-header';
            const meta = document.createElement('span');
            meta.className = 'history-meta';
            const duration = item.duration_ms ? ` · ${(item.duration_ms / 1000).toFixed(1)}s` : '';
            meta.textContent = `${formatHistoryDate(item.created_at)} · ${item.mode}${duration}`;
            const status = document.createElement('span');
            const inProgress = !['completed', 'failed', 'cancelled'].includes(item.status);
            status.className = `history-status ${item.status === 'failed' ? 'failed' : ''} ${inProgress ? 'processing' : ''}`;
            status.textContent = item.status;
            header.append(meta, status);

            const textBlock = document.createElement('p');
            textBlock.className = 'history-text';
            textBlock.textContent = historyItemText(item) || 'No transcript text was captured.';

            card.append(header, textBlock);
            if (item.error_message) {
                const error = document.createElement('p');
                error.className = 'history-error';
                error.textContent = item.error_message;
                card.append(error);
            }

            const actions = document.createElement('div');
            actions.className = 'history-actions';
            const copy = document.createElement('button');
            copy.className = 'btn-secondary history-copy';
            copy.type = 'button';
            copy.textContent = 'Copy';
            copy.disabled = !historyItemText(item);
            if (item.status === 'failed' && item.audio_path) {
                const retry = document.createElement('button');
                retry.className = 'btn-secondary history-retry';
                retry.type = 'button';
                retry.textContent = 'Retry';
                actions.append(retry);
            }
            const remove = document.createElement('button');
            remove.className = 'btn-secondary history-delete';
            remove.type = 'button';
            remove.textContent = 'Delete';
            actions.append(copy, remove);
            card.append(actions);
            historyList.append(card);
        });
    }

    async function loadHistory() {
        if (!historyList) return;
        const query = historySearch ? historySearch.value.trim() : '';
        try {
            const response = await apiFetch(`/api/history?limit=100&q=${encodeURIComponent(query)}`);
            const data = await response.json();
            if (!response.ok || !data.ok) throw new Error(data.error || 'Could not load history');
            historyData = data.items || [];
            renderHistory();
        } catch (error) {
            showToast(error.message || 'Could not load history');
        }
    }

    window.loadHistory = loadHistory;

    function renderPresets() {
        if (!presetsContainer) return;
        presetsContainer.innerHTML = '';
        presetsData.forEach((preset, index) => {
            const card = document.createElement('div');
            card.className = 'preset-card';
            
            const k1 = preset.hotkeys && preset.hotkeys.length > 0 ? preset.hotkeys[0] : 'ctrl';
            const k2 = preset.hotkeys && preset.hotkeys.length > 1 ? preset.hotkeys[1] : 'space';

            card.innerHTML = `
                <div class="preset-header">
                    <input type="text" class="preset-title-input" value="${escapeHtml(preset.name)}" data-idx="${index}">
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
                <textarea class="input-field prompt-area preset-prompt-input" rows="3" data-idx="${index}">${escapeHtml(preset.prompt)}</textarea>
            `;
            presetsContainer.appendChild(card);
        });
    }

    function loadAnalytics() {
        apiFetch('/api/analytics')
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

    function formatHotkey(keys) {
        const isMac = /Mac/i.test(navigator.platform || navigator.userAgent);
        const names = { alt: 'Alt', shift: 'Shift', ctrl: 'Ctrl', cmd: isMac ? 'Cmd' : 'Win', space: 'Space' };
        return keys.map(k => names[k] || String(k).toUpperCase()).join(' + ');
    }

    function updateHotkeyLabels(keys) {
        mainHotkeyKeys = keys.slice(0, 2);
        const label = formatHotkey(mainHotkeyKeys);
        document.querySelectorAll('.main-hotkey-label').forEach(el => { el.textContent = label; });
        const practiceBox = document.getElementById('practice-dictation-box');
        if (practiceBox) practiceBox.placeholder = `Click here, then hold ${label} to dictate your first test sentence...`;
    }

    function loadHotkeyConfig() {
        apiFetch('/api/status')
            .then(r => r.json())
            .then(data => {
                if (data.hotkey && data.hotkey.length >= 2) {
                    hotkey1.value = data.hotkey[0];
                    hotkey2.value = data.hotkey[1];
                    updateHotkeyLabels(data.hotkey);
                }
                if (data.context_hotkey && data.context_hotkey.length >= 2 && contextHotkey1) {
                    contextHotkey1.value = data.context_hotkey[0];
                    contextHotkey2.value = data.context_hotkey[1];
                }
                if (data.api_key !== undefined) {
                    apiKey.value = data.api_key;
                }
                apiKeyConfigured = Boolean(data.api_key_configured);
                if (apiKeyConfigured && apiKey) apiKey.placeholder = 'Saved securely — enter a new key to replace it';
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
                if (data.writing_style !== undefined && writingStyleSelect) {
                    writingStyleSelect.value = data.writing_style;
                }
                if (data.text_replacements !== undefined && textReplacements) {
                    textReplacements.value = data.text_replacements;
                }
                if (data.voice_snippets !== undefined && voiceSnippets) {
                    voiceSnippets.value = data.voice_snippets;
                }
                if (data.output_mode !== undefined && outputModeSelect) {
                    outputModeSelect.value = data.output_mode;
                }
                if (data.app_aware_formatting !== undefined && appAwareToggle) {
                    appAwareToggle.checked = data.app_aware_formatting;
                }
                if (data.dictation_trigger_mode !== undefined && triggerModeSelect) {
                    triggerModeSelect.value = data.dictation_trigger_mode;
                }
                if (data.silence_auto_stop !== undefined && silenceAutoStopToggle) {
                    silenceAutoStopToggle.checked = data.silence_auto_stop;
                }
                if (data.silence_timeout_seconds !== undefined && silenceTimeoutSelect) {
                    silenceTimeoutSelect.value = String(data.silence_timeout_seconds);
                }
                if (data.history_retention_days !== undefined && historyRetentionSelect) {
                    historyRetentionSelect.value = String(data.history_retention_days);
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
                if (onboardingModal && data.onboarding_complete === false) {
                    onboardingModal.hidden = false;
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
        const writingStyle = writingStyleSelect ? writingStyleSelect.value : "natural";
        const replacements = textReplacements ? textReplacements.value : "";
        const snippets = voiceSnippets ? voiceSnippets.value : "";
        const outputMode = outputModeSelect ? outputModeSelect.value : "type";
        const appAwareFormatting = appAwareToggle ? appAwareToggle.checked : true;
        const triggerMode = triggerModeSelect ? triggerModeSelect.value : "hold";
        const silenceAutoStop = silenceAutoStopToggle ? silenceAutoStopToggle.checked : true;
        const silenceTimeoutSeconds = silenceTimeoutSelect ? Number(silenceTimeoutSelect.value) : 3;
        const historyRetentionDays = historyRetentionSelect ? Number(historyRetentionSelect.value) : 30;
        const mainDictationAi = mainDictationAiToggle ? mainDictationAiToggle.checked : false;
        const lang = languageSelect ? languageSelect.value : "auto";
        const cp = contextPrompt ? contextPrompt.value : "";

        const shortcutId = (keys) => keys.map(k => String(k).toLowerCase()).sort().join('+');
        if (shortcutId([k1, k2]) === shortcutId([ck1, ck2])) {
            showToast('Dictation and context shortcuts must be different');
            return;
        }
        const reservedShortcuts = new Set([
            shortcutId([k1, k2]),
            shortcutId([ck1, ck2])
        ]);
        const usedPresetShortcuts = new Set();

        for (const preset of presetsData) {
            const keys = preset.hotkeys || [];
            if (keys.length < 2 || keys[0] === keys[1]) {
                showToast(`Choose two different keys for "${preset.name}"`);
                return;
            }
            if (/Windows/i.test(navigator.userAgent) && keys.includes('cmd')) {
                showToast(`Use Ctrl, Alt, Shift, or Space for "${preset.name}" on Windows`);
                return;
            }
            const id = shortcutId(keys);
            if (reservedShortcuts.has(id)) {
                showToast(`"${preset.name}" conflicts with a dictation shortcut`);
                return;
            }
            if (usedPresetShortcuts.has(id)) {
                showToast(`Two AI presets use the same shortcut`);
                return;
            }
            usedPresetShortcuts.add(id);
        }

        const configPayload = {
                key1: k1, key2: k2, 
                context_key1: ck1,
                context_key2: ck2,
                run_at_startup: runAtStartup,
                use_local_llm: useLocalLlm,
                transcription_engine: transcriptionEngine,
                custom_vocabulary: customVocab,
                writing_style: writingStyle,
                text_replacements: replacements,
                voice_snippets: snippets,
                output_mode: outputMode,
                app_aware_formatting: appAwareFormatting,
                dictation_trigger_mode: triggerMode,
                silence_auto_stop: silenceAutoStop,
                silence_timeout_seconds: silenceTimeoutSeconds,
                history_retention_days: historyRetentionDays,
                main_dictation_ai: mainDictationAi,
                context_prompt: cp,
                dictation_language: lang,
                ai_presets: presetsData
        };
        if (key) configPayload.api_key = key;

        apiFetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(configPayload)
        })
        .then(r => r.json())
        .then(data => {
            if (data.ok) {
                if (key) {
                    apiKeyConfigured = true;
                    apiKey.value = '';
                    apiKey.placeholder = 'Saved securely — enter a new key to replace it';
                }
                updateHotkeyLabels([k1, k2]);
                showToast('Settings successfully applied!');
            } else {
                showToast(data.error || 'Failed to update settings');
            }
        })
        .catch(() => {
            showToast('Failed to update settings');
        });
    }

    function startStatusPolling() {
        pollInterval = setInterval(function() {
            apiFetch('/api/status')
                .then(r => r.json())
                .then(data => {
                    updateStatusUI(data.status);
                    // A dictation just finished: refresh the counters and history once.
                    if (lastStatus && lastStatus !== 'idle' && data.status === 'idle') {
                        loadAnalytics();
                        loadHistory();
                    }
                    lastStatus = data.status;
                })
                .catch(() => {});
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

        if (historyRefresh) historyRefresh.addEventListener('click', loadHistory);
        if (clearApiKey) {
            clearApiKey.addEventListener('click', async () => {
                if (!apiKeyConfigured) {
                    showToast('No API key is saved');
                    return;
                }
                if (!window.confirm('Remove the saved Groq API key from this computer?')) return;
                try {
                    const response = await apiFetch('/api/config', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ clear_api_key: true })
                    });
                    const data = await response.json();
                    if (!response.ok || !data.ok) throw new Error(data.error || 'Could not remove key');
                    apiKeyConfigured = false;
                    apiKey.value = '';
                    apiKey.placeholder = 'gsk_...';
                    showToast('Saved API key removed');
                } catch (error) {
                    showToast(error.message || 'Could not remove key');
                }
            });
        }
        let micStream = null;
        let micAnimId = null;

        function setWizardStep(stepNumber) {
            document.querySelectorAll('.wizard-step').forEach(s => s.style.display = 'none');
            const target = document.getElementById(`wizard-step-${stepNumber}`);
            if (target) target.style.display = 'block';

            [1, 2, 3].forEach(n => {
                const dot = document.getElementById(`dot-${n}`);
                if (dot) dot.classList.toggle('active', n === stepNumber);
            });

            if (stepNumber === 2) {
                startMicTest();
            } else {
                stopMicTest();
            }
        }

        async function startMicTest() {
            const fill = document.getElementById('mic-meter-fill');
            const icon = document.getElementById('mic-icon-wrapper');
            const label = document.getElementById('mic-status-label');
            if (!fill) return;

            try {
                if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
                    micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
                    const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
                    const source = audioCtx.createMediaStreamSource(micStream);
                    const analyser = audioCtx.createAnalyser();
                    analyser.fftSize = 256;
                    source.connect(analyser);

                    const dataArray = new Uint8Array(analyser.frequencyBinCount);

                    function pollMic() {
                        analyser.getByteFrequencyData(dataArray);
                        let sum = 0;
                        for (let i = 0; i < dataArray.length; i++) {
                            sum += dataArray[i];
                        }
                        const avg = sum / dataArray.length;
                        const percent = Math.min(100, Math.round((avg / 128) * 100));
                        fill.style.width = `${percent}%`;

                        if (percent > 10) {
                            if (icon) icon.classList.add('active');
                            if (label) label.textContent = 'Voice detected! Microphone is working.';
                        } else {
                            if (icon) icon.classList.remove('active');
                        }
                        micAnimId = requestAnimationFrame(pollMic);
                    }
                    pollMic();
                } else {
                    if (label) label.textContent = 'Microphone ready for Windows dictation.';
                    fill.style.width = '35%';
                }
            } catch (e) {
                if (label) label.textContent = 'Microphone ready for Windows dictation.';
                fill.style.width = '35%';
            }
        }

        function stopMicTest() {
            if (micAnimId) {
                cancelAnimationFrame(micAnimId);
                micAnimId = null;
            }
            if (micStream) {
                micStream.getTracks().forEach(t => t.stop());
                micStream = null;
            }
            const fill = document.getElementById('mic-meter-fill');
            if (fill) fill.style.width = '0%';
            const icon = document.getElementById('mic-icon-wrapper');
            if (icon) icon.classList.remove('active');
        }

        const next1 = document.getElementById('wizard-next-1');
        if (next1) next1.addEventListener('click', () => setWizardStep(2));

        const prev2 = document.getElementById('wizard-prev-2');
        if (prev2) prev2.addEventListener('click', () => setWizardStep(1));

        const next2 = document.getElementById('wizard-next-2');
        if (next2) next2.addEventListener('click', () => setWizardStep(3));

        const prev3 = document.getElementById('wizard-prev-3');
        if (prev3) prev3.addEventListener('click', () => setWizardStep(2));

        if (onboardingFinish) {
            onboardingFinish.addEventListener('click', async () => {
                stopMicTest();
                try {
                    const response = await apiFetch('/api/config', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ onboarding_complete: true })
                    });
                    const data = await response.json();
                    if (!response.ok || !data.ok) throw new Error(data.error || 'Setup failed');
                    onboardingModal.hidden = true;
                    showToast(`Welcome to VoiceFlow! Hold ${formatHotkey(mainHotkeyKeys)} to dictate anytime.`);
                } catch (error) {
                    showToast(error.message || 'Could not finish setup');
                }
            });
        }
        if (historyClear) {
            historyClear.addEventListener('click', async () => {
                if (!window.confirm('Permanently delete all local transcript history and recovery audio?')) return;
                try {
                    const response = await apiFetch('/api/history', { method: 'DELETE' });
                    const data = await response.json();
                    if (!response.ok || !data.ok) throw new Error(data.error || 'Clear failed');
                    historyData = [];
                    renderHistory();
                    loadAnalytics();
                    showToast(`Deleted ${data.deleted} history item${data.deleted === 1 ? '' : 's'}`);
                } catch (error) {
                    showToast(error.message || 'Could not clear history');
                }
            });
        }
        if (historySearch) {
            historySearch.addEventListener('input', () => {
                clearTimeout(historySearchTimer);
                historySearchTimer = setTimeout(loadHistory, 250);
            });
        }
        if (copyLastTranscript) {
            copyLastTranscript.addEventListener('click', async () => {
                const latest = historyData.find(item => historyItemText(item));
                if (latest && await copyText(historyItemText(latest))) {
                    showToast('Latest transcript copied');
                } else {
                    showToast('There is no transcript to copy yet');
                }
            });
        }
        if (historyList) {
            historyList.addEventListener('click', async event => {
                const card = event.target.closest('.history-item');
                if (!card) return;
                const item = historyData.find(entry => entry.id === card.dataset.historyId);
                if (!item) return;

                if (event.target.closest('.history-copy')) {
                    if (await copyText(historyItemText(item))) showToast('Transcript copied');
                    else showToast('Failed to copy transcript');
                }

                if (event.target.closest('.history-retry')) {
                    const retryButton = event.target.closest('.history-retry');
                    retryButton.disabled = true;
                    retryButton.textContent = 'Retrying…';
                    try {
                        const response = await apiFetch(`/api/history/${encodeURIComponent(item.id)}/retry`, { method: 'POST' });
                        const data = await response.json();
                        if (!response.ok || !data.ok) throw new Error(data.error || data.item?.error_message || 'Retry failed');
                        await loadHistory();
                        loadAnalytics();
                        showToast('Transcript recovered');
                    } catch (error) {
                        await loadHistory();
                        showToast(error.message || 'Could not recover transcript');
                    }
                }

                if (event.target.closest('.history-delete')) {
                    if (!window.confirm('Delete this transcript from local history?')) return;
                    try {
                        const response = await apiFetch(`/api/history/${encodeURIComponent(item.id)}`, { method: 'DELETE' });
                        const data = await response.json();
                        if (!response.ok || !data.ok) throw new Error(data.error || 'Delete failed');
                        historyData = historyData.filter(entry => entry.id !== item.id);
                        renderHistory();
                        loadAnalytics();
                        showToast('Transcript deleted');
                    } catch (error) {
                        showToast(error.message || 'Could not delete transcript');
                    }
                }
            });
        }
        
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

        window.copyTranscript = async function() {
            if (transcriptResult && transcriptResult.value) {
                if (await copyText(transcriptResult.value)) {
                    showToast('Transcript copied to clipboard!');
                } else {
                    showToast('Failed to copy');
                }
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

                apiFetch('/api/transcribe_file', {
                    method: 'POST',
                    body: formData
                })
                .then(response => response.json())
                .then(data => {
                    if (data.ok) {
                        uploadStatus.style.display = 'none';
                        transcriptContainer.style.display = 'block';
                        transcriptResult.value = data.text;
                        loadHistory();
                        loadAnalytics();
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

    function checkAppUpdates(manual = false) {
        if (manual) showToast('Checking for updates…');
        apiFetch('/api/check_update')
            .then(r => r.json())
            .then(data => {
                if (manual && (!data || !data.ok)) {
                    showToast('Could not check for updates');
                } else if (manual && !data.update_available) {
                    showToast(`VoiceFlow ${data.current_version} is up to date`);
                }
                if (data && data.ok && data.update_available) {
                    const banner = document.getElementById('update-banner');
                    const versionSpan = document.getElementById('update-version');
                    const link = document.getElementById('update-link');
                    if (banner && versionSpan && link) {
                        versionSpan.textContent = data.latest_version;
                        link.href = data.release_url || 'https://github.com/HafizMuhammadShah42895/VoiceFlow/releases';
                        banner.style.display = 'block';
                    }
                }
            })
            .catch(() => {
                if (manual) showToast('Could not check for updates');
            });
    }

    window.checkAppUpdates = checkAppUpdates;

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
