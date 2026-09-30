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
    const profilesContainer = document.getElementById('profiles-container');
    const profilesEmpty = document.getElementById('profiles-empty');
    const addProfileBtn = document.getElementById('add-profile-btn');
    const platformIssues = document.getElementById('platform-issues');

    const PROFILE_STYLE_OPTIONS = [
        ['default', 'Use my main writing style'],
        ['natural', 'Natural — preserve my voice'],
        ['concise', 'Concise — remove repetition'],
        ['professional', 'Professional — polished and clear'],
        ['casual', 'Casual — warm and conversational']
    ];
    const PROFILE_POLISH_OPTIONS = [
        ['default', 'Follow the main AI Polish setting'],
        ['on', 'Always polish in these apps'],
        ['off', 'Off — type exactly what I say']
    ];
    const IS_WINDOWS = /Windows/i.test(navigator.userAgent);

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
    let profilesData = [];
    let openApps = [];
    let editingHistoryId = null;
    let editingDraft = '';
    const historySuggestions = {};

    function init() {
        loadHotkeyConfig();
        loadAnalytics();
        loadHistory();
        loadOpenApps();
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

    function el(tag, props = {}) {
        return Object.assign(document.createElement(tag), props);
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
            const card = el('article', { className: 'history-item' });
            card.dataset.historyId = item.id;
            const editing = editingHistoryId === item.id;

            const header = el('div', { className: 'history-item-header' });
            const duration = item.duration_ms ? ` · ${(item.duration_ms / 1000).toFixed(1)}s` : '';
            const profileName = item.metadata && item.metadata.profile ? ` · ${item.metadata.profile}` : '';
            const meta = el('span', {
                className: 'history-meta',
                textContent: `${formatHistoryDate(item.created_at)} · ${item.mode}${duration}${profileName}`
            });
            const inProgress = !['completed', 'failed', 'cancelled'].includes(item.status);
            const status = el('span', {
                className: `history-status ${item.status === 'failed' ? 'failed' : ''} ${inProgress ? 'processing' : ''}`,
                textContent: item.status
            });
            header.append(meta, status);
            card.append(header);

            if (editing) {
                const editor = el('textarea', {
                    className: 'input-field prompt-area history-edit',
                    value: editingDraft,
                    rows: 4
                });
                editor.setAttribute('aria-label', 'Corrected transcript');
                card.append(editor);
            } else {
                card.append(el('p', {
                    className: 'history-text',
                    textContent: historyItemText(item) || 'No transcript text was captured.'
                }));
            }
            if (item.error_message) {
                card.append(el('p', { className: 'history-error', textContent: item.error_message }));
            }

            const suggestions = historySuggestions[item.id];
            if (suggestions && suggestions.length) {
                const panel = el('div', { className: 'history-suggestions' });
                panel.append(el('p', {
                    className: 'setting-help',
                    textContent: 'Remember these fixes? They will be applied automatically next time:'
                }));
                suggestions.forEach((suggestion, index) => {
                    const row = el('div', { className: 'history-suggestion' });
                    row.append(el('span', { textContent: `“${suggestion.spoken}” → “${suggestion.replacement}”` }));
                    const add = el('button', { className: 'btn-secondary history-suggestion-add', type: 'button', textContent: 'Add' });
                    add.dataset.index = String(index);
                    row.append(add);
                    panel.append(row);
                });
                panel.append(el('button', { className: 'btn-secondary history-suggestions-dismiss', type: 'button', textContent: 'No thanks' }));
                card.append(panel);
            }

            const actions = el('div', { className: 'history-actions' });
            if (editing) {
                actions.append(
                    el('button', { className: 'btn-secondary history-cancel', type: 'button', textContent: 'Cancel' }),
                    el('button', { className: 'btn-primary history-save', type: 'button', textContent: 'Save fix' })
                );
            } else {
                if (item.status === 'failed' && item.audio_path) {
                    actions.append(el('button', { className: 'btn-secondary history-retry', type: 'button', textContent: 'Retry' }));
                }
                const hasText = Boolean(historyItemText(item));
                actions.append(
                    el('button', { className: 'btn-secondary history-fix', type: 'button', textContent: 'Fix', disabled: !hasText }),
                    el('button', { className: 'btn-secondary history-copy', type: 'button', textContent: 'Copy', disabled: !hasText }),
                    el('button', { className: 'btn-secondary history-delete', type: 'button', textContent: 'Delete' })
                );
            }
            card.append(actions);
            historyList.append(card);
        });

        if (editingHistoryId) {
            const editor = historyList.querySelector('.history-edit');
            if (editor && document.activeElement !== editor) editor.focus();
        }
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

    function normalizeAppName(name) {
        let app = String(name || '').trim().replace(/^"|"$/g, '').split(/[\\/]/).pop().toLowerCase();
        if (app && IS_WINDOWS && !app.endsWith('.exe')) app += '.exe';
        return app;
    }

    function profileSelect(labelText, field, options, value) {
        const wrapper = el('div', { className: 'setting-item' });
        const select = el('select', { className: 'input-field' });
        select.dataset.field = field;
        options.forEach(([optionValue, text]) => select.append(el('option', { value: optionValue, textContent: text })));
        select.value = value || 'default';
        wrapper.append(el('label', { textContent: labelText }), select);
        return wrapper;
    }

    function renderProfiles() {
        if (!profilesContainer) return;
        profilesContainer.replaceChildren();
        if (profilesEmpty) profilesEmpty.style.display = profilesData.length ? 'none' : 'block';

        profilesData.forEach((profile, index) => {
            const card = el('div', { className: 'preset-card profile-card' });
            card.dataset.idx = String(index);

            const header = el('div', { className: 'preset-header' });
            const name = el('input', {
                className: 'preset-title-input',
                type: 'text',
                value: profile.name || '',
                placeholder: 'Profile name'
            });
            name.dataset.field = 'name';
            name.setAttribute('aria-label', 'Profile name');
            header.append(name, el('button', { className: 'remove-preset-btn profile-remove', type: 'button', textContent: 'Remove' }));

            const options = el('div', { className: 'profile-row' });
            options.append(
                profileSelect('Writing style', 'writing_style', PROFILE_STYLE_OPTIONS, profile.writing_style),
                profileSelect('AI Polish', 'ai_polish', PROFILE_POLISH_OPTIONS, profile.ai_polish)
            );

            const instructions = el('textarea', {
                className: 'input-field prompt-area',
                rows: 2,
                value: profile.instructions || '',
                placeholder: 'Extra instructions (optional), e.g. "Start with Hi, and keep it under three sentences."'
            });
            instructions.dataset.field = 'instructions';
            instructions.setAttribute('aria-label', 'Extra instructions');

            const apps = el('div', { className: 'profile-apps' });
            if (!profile.apps.length) {
                apps.append(el('span', { className: 'setting-help', textContent: 'No apps yet. Add the apps this profile should apply to.' }));
            }
            profile.apps.forEach(app => {
                const chip = el('span', { className: 'app-chip', textContent: app });
                const remove = el('button', { className: 'app-chip-remove', type: 'button', textContent: '×', title: `Remove ${app}` });
                remove.dataset.app = app;
                remove.setAttribute('aria-label', `Remove ${app}`);
                chip.append(remove);
                apps.append(chip);
            });

            const addRow = el('div', { className: 'profile-add-app' });
            const picker = el('select', { className: 'input-field profile-app-select' });
            picker.setAttribute('aria-label', 'Choose an open app');
            picker.append(el('option', {
                value: '',
                textContent: openApps.length ? 'Choose an open app…' : 'Open the app, or type its name →'
            }));
            openApps.forEach(app => {
                const label = app.window_title ? `${app.process_name} — ${app.window_title}` : app.process_name;
                picker.append(el('option', { value: app.process_name, textContent: label.slice(0, 70) }));
            });
            const typed = el('input', { className: 'input-field profile-app-input', type: 'text', placeholder: 'e.g. slack.exe' });
            typed.setAttribute('aria-label', 'App name');
            addRow.append(picker, typed, el('button', { className: 'btn-secondary profile-app-add', type: 'button', textContent: 'Add app' }));

            card.append(header, options, instructions, el('label', { textContent: 'Used in these apps' }), apps, addRow);
            profilesContainer.append(card);
        });
    }

    function renderPlatformIssues(issues) {
        if (!platformIssues) return;
        platformIssues.replaceChildren();
        (issues || []).forEach(issue => {
            const card = el('section', { className: `card platform-issue ${issue.level === 'warning' ? 'warning' : 'info'}` });
            card.append(
                el('h3', { textContent: issue.title }),
                el('p', { className: 'setting-help', textContent: issue.detail })
            );
            if (issue.commands && issue.commands.length) {
                const commands = issue.commands.join('\n');
                card.append(el('pre', { className: 'platform-commands', textContent: commands }));
                const copy = el('button', { className: 'btn-secondary', type: 'button', textContent: 'Copy commands' });
                copy.addEventListener('click', async () => {
                    showToast(await copyText(commands) ? 'Commands copied — paste them into a terminal' : 'Could not copy');
                });
                card.append(copy);
            }
            platformIssues.append(card);
        });
    }

    function loadOpenApps() {
        apiFetch('/api/apps')
            .then(r => r.json())
            .then(data => {
                if (!data.ok) return;
                openApps = data.apps || [];
                // Do not rebuild the cards while the user is typing in one.
                if (!profilesContainer || !profilesContainer.contains(document.activeElement)) renderProfiles();
            })
            .catch(() => {});
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

    function updateContextHotkeyLabels(keys) {
        const label = formatHotkey(keys.slice(0, 2));
        document.querySelectorAll('.context-hotkey-label').forEach(el => { el.textContent = label; });
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
                    updateContextHotkeyLabels(data.context_hotkey);
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
                renderPlatformIssues(data.platform_issues);
                if (Array.isArray(data.writing_profiles)) {
                    profilesData = data.writing_profiles;
                    renderProfiles();
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

        const appOwners = {};
        for (const profile of profilesData) {
            if (!String(profile.name || '').trim()) {
                showToast('Give every writing profile a name');
                return;
            }
            for (const app of profile.apps) {
                if (appOwners[app]) {
                    showToast(`${app} is in both "${appOwners[app]}" and "${profile.name}"`);
                    return;
                }
                appOwners[app] = profile.name;
            }
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
                ai_presets: presetsData,
                writing_profiles: profilesData
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
                updateContextHotkeyLabels([ck1, ck2]);
                // The server normalizes app names; show exactly what was saved.
                loadHotkeyConfig();
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
                        if (!editingHistoryId) loadHistory();
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

                if (event.target.closest('.history-fix')) {
                    editingHistoryId = item.id;
                    editingDraft = historyItemText(item);
                    renderHistory();
                    return;
                }

                if (event.target.closest('.history-cancel')) {
                    editingHistoryId = null;
                    renderHistory();
                    return;
                }

                if (event.target.closest('.history-save')) {
                    const saveButton = event.target.closest('.history-save');
                    saveButton.disabled = true;
                    try {
                        const response = await apiFetch(`/api/history/${encodeURIComponent(item.id)}/correct`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ text: editingDraft })
                        });
                        const data = await response.json();
                        if (!response.ok || !data.ok) throw new Error(data.error || 'Could not save the fix');
                        historyData = historyData.map(entry => entry.id === item.id ? data.item : entry);
                        editingHistoryId = null;
                        if (data.suggestions && data.suggestions.length) historySuggestions[item.id] = data.suggestions;
                        renderHistory();
                        showToast('Transcript fixed');
                    } catch (error) {
                        saveButton.disabled = false;
                        showToast(error.message || 'Could not save the fix');
                    }
                    return;
                }

                if (event.target.closest('.history-suggestions-dismiss')) {
                    delete historySuggestions[item.id];
                    renderHistory();
                    return;
                }

                const addSuggestion = event.target.closest('.history-suggestion-add');
                if (addSuggestion) {
                    const suggestion = (historySuggestions[item.id] || [])[Number(addSuggestion.dataset.index)];
                    if (!suggestion) return;
                    addSuggestion.disabled = true;
                    try {
                        const response = await apiFetch('/api/replacements', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(suggestion)
                        });
                        const data = await response.json();
                        if (!response.ok || !data.ok) throw new Error(data.error || 'Could not add the replacement');
                        if (textReplacements) textReplacements.value = data.text_replacements;
                        historySuggestions[item.id] = historySuggestions[item.id].filter(entry => entry !== suggestion);
                        renderHistory();
                        showToast(data.added
                            ? `Added: ${suggestion.spoken} → ${suggestion.replacement}`
                            : `A replacement for "${suggestion.spoken}" already exists`);
                    } catch (error) {
                        addSuggestion.disabled = false;
                        showToast(error.message || 'Could not add the replacement');
                    }
                    return;
                }

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
        
        if (historyList) {
            historyList.addEventListener('input', event => {
                if (event.target.classList.contains('history-edit')) editingDraft = event.target.value;
            });
        }

        if (addProfileBtn) {
            addProfileBtn.addEventListener('click', () => {
                profilesData.push({
                    id: 'profile_' + Date.now(),
                    name: 'New profile',
                    apps: [],
                    writing_style: 'default',
                    ai_polish: 'default',
                    instructions: ''
                });
                renderProfiles();
                loadOpenApps();
                const names = profilesContainer.querySelectorAll('.preset-title-input');
                if (names.length) names[names.length - 1].select();
            });
        }

        if (profilesContainer) {
            const updateField = event => {
                const card = event.target.closest('.profile-card');
                const field = event.target.dataset.field;
                if (!card || !field) return;
                profilesData[Number(card.dataset.idx)][field] = event.target.value;
            };
            profilesContainer.addEventListener('input', updateField);
            profilesContainer.addEventListener('change', updateField);

            profilesContainer.addEventListener('click', event => {
                const card = event.target.closest('.profile-card');
                if (!card) return;
                const profile = profilesData[Number(card.dataset.idx)];

                if (event.target.closest('.profile-remove')) {
                    profilesData.splice(Number(card.dataset.idx), 1);
                    renderProfiles();
                    return;
                }

                const chipRemove = event.target.closest('.app-chip-remove');
                if (chipRemove) {
                    profile.apps = profile.apps.filter(app => app !== chipRemove.dataset.app);
                    renderProfiles();
                    return;
                }

                if (event.target.closest('.profile-app-add')) {
                    const typed = card.querySelector('.profile-app-input').value;
                    const picked = card.querySelector('.profile-app-select').value;
                    const app = normalizeAppName(typed || picked);
                    if (!app) {
                        showToast('Choose an open app or type its name');
                        return;
                    }
                    const owner = profilesData.find(other => other.apps.includes(app));
                    if (owner) {
                        showToast(owner === profile ? `${app} is already in this profile` : `${app} is already in "${owner.name}"`);
                        return;
                    }
                    profile.apps.push(app);
                    renderProfiles();
                }
            });
        }

        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'visible') loadOpenApps();
        });

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
