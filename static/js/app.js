(function() {
    'use strict';

    const hotkey1 = document.getElementById('hotkey-1');
    const hotkey2 = document.getElementById('hotkey-2');
    const aiKey1 = document.getElementById('ai-key-1');
    const aiKey2 = document.getElementById('ai-key-2');
    const apiKey = document.getElementById('api-key');
    const hotkeySave = document.getElementById('hotkey-save');
    const statusDot = document.getElementById('status-dot');
    const statusText = document.getElementById('status-text');
    const toast = document.getElementById('toast');

    let pollInterval = null;

    function init() {
        loadHotkeyConfig();
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

    function loadHotkeyConfig() {
        fetch('/api/status')
            .then(r => r.json())
            .then(data => {
                if (data.hotkey && data.hotkey.length === 2) {
                    hotkey1.value = data.hotkey[0];
                    hotkey2.value = data.hotkey[1];
                }
                if (data.ai_hotkey && data.ai_hotkey.length === 2) {
                    aiKey1.value = data.ai_hotkey[0];
                    aiKey2.value = data.ai_hotkey[1];
                }
                if (data.api_key !== undefined) {
                    apiKey.value = data.api_key;
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
        const ai1 = aiKey1.value || 'ctrl';
        const ai2 = aiKey2.value || 'shift';
        const key = apiKey.value.trim();

        fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ key1: k1, key2: k2, ai_key1: ai1, ai_key2: ai2, api_key: key })
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
        }, 800);
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

        window.addEventListener('beforeunload', function() {
            if (pollInterval) clearInterval(pollInterval);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
