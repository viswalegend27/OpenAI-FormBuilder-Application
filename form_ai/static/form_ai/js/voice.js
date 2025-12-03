// ============================================================
// STATE & CONFIGURATION
// ============================================================

const VoiceState = {
    sessionId: null,
    conversationSaved: false,
    pc: null,
    dc: null,
    micStream: null,
    remoteEl: null,
    verifiedData: null,
    verificationToolCallId: null,
    messages: [],
    isNewAssistantResponse: true,
    micPausedForVerification: false,
    currentAssistant: null,
    aiStreaming: ''
};

const INTERVIEW_ID = window.INTERVIEW_ID || '';
const VERIFICATION_FIELDS = Array.isArray(window.VERIFICATION_FIELDS) ? window.VERIFICATION_FIELDS : [];
const verificationInputMap = new Map();

// ============================================================
// UTILITIES
// ============================================================

const $ = id => document.getElementById(id);
const voiceLog = (...args) => console.log('[Voice]', ...args);

let toastTimer;
const toast = (msg, ms = 3000) => {
    const t = $('toast-message');
    if (!t) return Promise.resolve();

    t.textContent = msg;
    t.classList.add('show');
    clearTimeout(toastTimer);

    return new Promise(resolve => {
        if (ms <= 0) return resolve();
        toastTimer = setTimeout(() => {
        t.classList.remove('show');
        resolve();
        }, ms);
    });
};

// ============================================================
// MESSAGE HANDLING
// ============================================================

const pushMessage = (role, text) => {
    const content = text?.trim();
    if (!content) return;
    VoiceState.messages.push({ role, content, ts: new Date().toISOString() });
};

const updateLastAssistant = text => {
    const content = text?.trim();
    if (!content) return;

    if (VoiceState.isNewAssistantResponse) {
        pushMessage('assistant', content);
        VoiceState.isNewAssistantResponse = false;
        return;
    }

    for (let i = VoiceState.messages.length - 1; i >= 0; i--) {
        if (VoiceState.messages[i].role === 'assistant') {
        VoiceState.messages[i].content = content;
        VoiceState.messages[i].ts = new Date().toISOString();
        return;
        }
    }
    pushMessage('assistant', content);
};

// ============================================================
// DOM RENDERING
// ============================================================

const appendMessageToDom = (role, text = '', saveToMemory = true) => {
    const conv = $('conversation');
    if (!conv) return null;

    conv.classList.remove('empty');

    const msg = document.createElement('div');
    msg.className = `message ${role === 'user' ? 'user' : 'assistant'}`;

    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    bubble.textContent = text;

    const meta = document.createElement('div');
    meta.className = 'meta';
    meta.textContent = role === 'user' ? 'You' : 'Tyler';

    msg.append(bubble, meta);
    conv.appendChild(msg);
    conv.scrollTop = conv.scrollHeight;

    if (saveToMemory && text?.trim()) pushMessage(role, text);

    return { msgEl: msg, bubbleEl: bubble };
    };

    const updateStreaming = (el, text) => {
    if (!el || !text) return;
    el.bubbleEl.textContent = text;
    el.msgEl.classList.add('streaming');
    updateLastAssistant(text);
    el.msgEl.scrollIntoView({ block: 'end', behavior: 'smooth' });
    };

    const finalize = (el, text) => {
    if (!el) return;
    const trimmed = text?.trim() || '';

    if (!trimmed) {
    el.msgEl.remove();
    return;
    }

    el.bubbleEl.textContent = trimmed;
    el.msgEl.classList.remove('streaming');
    updateLastAssistant(trimmed);
    el.msgEl.scrollIntoView({ block: 'end', behavior: 'smooth' });
};

// ============================================================
// VERIFICATION SYSTEM
// ============================================================

function renderVerificationFields() {
    const container = $('verification-fields-container');
    if (!container) return;

    container.innerHTML = '';

    if (!VERIFICATION_FIELDS.length) {
    container.innerHTML = '<p class="muted-text">No verification fields configured.</p>';
    return;
    }

    VERIFICATION_FIELDS.forEach(field => {
    const wrapper = document.createElement('div');
    wrapper.className = `field-group${field.source === 'question' ? ' question-field' : ''}`;

    const label = document.createElement('label');
    label.setAttribute('for', `verify-${field.key}`);
    label.textContent = field.label || field.key;

    const input = field.type === 'textarea'
        ? document.createElement('textarea')
        : document.createElement('input');

    input.id = `verify-${field.key}`;
    input.dataset.key = field.key;
    input.placeholder = field.placeholder || field.label || field.key;

    if (field.type === 'textarea') {
        input.rows = Math.min(6, Math.max(3, Math.ceil((input.placeholder.length || 80) / 40)));
    } else {
        input.type = field.input_type || 'text';
    }

    if (field.helper_text && field.source === 'question') {
        const helper = document.createElement('p');
        helper.className = 'field-helper';
        helper.textContent = field.helper_text;
        wrapper.append(label, helper, input);
    } else {
        wrapper.append(label, input);
    }

    container.appendChild(wrapper);
    verificationInputMap.set(field.key, input);
    });
    }

    const pauseMic = paused => {
    VoiceState.micStream?.getAudioTracks().forEach(track => {
    track.enabled = !paused;
    });
    VoiceState.micPausedForVerification = paused;
    };

    const showVerificationPopup = data => {
    const popup = $('verification-popup');
    if (!popup) return;

    VERIFICATION_FIELDS.forEach(field => {
    const input = verificationInputMap.get(field.key);
    if (input) {
        input.value = data?.[field.key] ?? VoiceState.verifiedData?.[field.key] ?? '';
    }
    });

    popup.style.display = 'flex';
    if (!VoiceState.micPausedForVerification) pauseMic(true);
    };

    const hideVerificationPopup = () => {
    const popup = $('verification-popup');
    if (popup) popup.style.display = 'none';
    if (VoiceState.micPausedForVerification) pauseMic(false);
    };

    const normalizeVerifiedData = data => {
    if (!data || !VERIFICATION_FIELDS.length) return null;

    const cleaned = {};
    VERIFICATION_FIELDS.forEach(field => {
    const value = data[field.key]?.toString().trim();
    if (value) cleaned[field.key] = value;
    });

    return Object.keys(cleaned).length ? cleaned : null;
    };

    const buildVerificationSummary = cleaned => {
    if (!cleaned) return '';

    const lines = ['Candidate confirmed their details:'];
    VERIFICATION_FIELDS.forEach(field => {
    const value = cleaned[field.key];
    if (!value) return;

    const label = field.label || field.key;
    const prefix = field.source === 'question' && field.sequence_number
        ? `Q${field.sequence_number}: ${label}\n  `
        : `${label}: `;
    lines.push(`- ${prefix}${value}`);
    });

    return lines.join('\n');
    };

    const sendVerifyToolOutput = (status, data = null) => {
    const { verificationToolCallId, dc } = VoiceState;
    if (!verificationToolCallId || dc?.readyState !== 'open') return false;

    const output = data ? { status, data } : { status };

    dc.send(JSON.stringify({
    type: 'conversation.item.create',
    item: {
        type: 'function_call_output',
        call_id: verificationToolCallId,
        output: JSON.stringify(output)
    }
    }));
    dc.send(JSON.stringify({ type: 'response.create' }));
    VoiceState.verificationToolCallId = null;

    return true;
};

// ============================================================
// WEBRTC HELPERS
// ============================================================

const sanitizeSdp = answer => {
    if (!answer || typeof answer !== 'string') return '';

    const extraTokens = /\s(ufrag|network-id|network-cost)\s[^ \r\n]+/gi;

    return answer
    .split(/\r?\n/)
    .filter(line => {
        const trimmed = line.trim();
        if (!trimmed) return false;
        if (trimmed.startsWith('a=candidate') && /\sTCP\s/i.test(trimmed)) return false;
        return true;
    })
    .map(line => line.startsWith('a=candidate') ? line.replace(extraTokens, '') : line)
    .join('\r\n') + '\r\n';
    };

    const waitForIceGathering = (pc, timeout = 3000) => {
    if (pc.iceGatheringState === 'complete') return Promise.resolve();

    return new Promise(resolve => {
    let timer;

    const done = () => {
        pc.removeEventListener('icegatheringstatechange', check);
        clearTimeout(timer);
        resolve();
    };

    const check = () => {
        if (pc.iceGatheringState === 'complete') done();
    };

    timer = setTimeout(done, timeout);
    pc.addEventListener('icegatheringstatechange', check);
    });
};

// ============================================================
// DATA CHANNEL MESSAGE HANDLER
// ============================================================

const handleDataChannelMessage = (msg, setStatus) => {
const { type } = msg;

switch (type) {
    case 'session.created':
    VoiceState.dc.send(JSON.stringify({ type: 'response.create' }));
    setStatus('Connected');
    break;

    case 'conversation.item.input_audio_transcription.completed': {
    const transcript = msg.transcript?.trim();
    if (transcript) appendMessageToDom('user', transcript, true);
    break;
    }

    case 'response.created':
    VoiceState.aiStreaming = '';
    VoiceState.isNewAssistantResponse = true;
    VoiceState.currentAssistant = appendMessageToDom('assistant', '', false);
    break;

    case 'response.audio_transcript.delta':
    VoiceState.aiStreaming += msg.delta || '';
    if (VoiceState.aiStreaming) {
        updateStreaming(VoiceState.currentAssistant, VoiceState.aiStreaming);
    }
    break;

    case 'response.audio_transcript.done': {
    const finalText = (msg.transcript || VoiceState.aiStreaming || '').trim();
    
    if (finalText) {
        if (VoiceState.currentAssistant) {
        finalize(VoiceState.currentAssistant, finalText);
        } else {
        appendMessageToDom('assistant', finalText, true);
        }
    } else if (VoiceState.currentAssistant?.msgEl) {
        VoiceState.currentAssistant.msgEl.remove();
    }
    
    VoiceState.aiStreaming = '';
    VoiceState.currentAssistant = null;
    VoiceState.isNewAssistantResponse = true;
    break;
    }

    case 'response.function_call_arguments.done': {
    if (VoiceState.currentAssistant?.bubbleEl && 
        !VoiceState.currentAssistant.bubbleEl.textContent.trim()) {
        VoiceState.currentAssistant.msgEl.remove();
    }
    VoiceState.currentAssistant = null;
    VoiceState.isNewAssistantResponse = true;

    if (msg.name === 'verify_information') {
        VoiceState.verificationToolCallId = msg.call_id;
        appendMessageToDom(
        'assistant',
        'Before we conclude, would you like to verify and confirm your information?',
        true
        );
        try {
        showVerificationPopup(JSON.parse(msg.arguments || '{}'));
        } catch {
        showVerificationPopup({});
        }
    }
    break;
    }
}
};

// ============================================================
// CORE VOICE SESSION
// ============================================================

async function startVoice() {
    const statusEl = $('status');
    const remote = $('remote');
    const stopBtn = $('stop');
    let sessionCreated = false;

    const setStatus = msg => { if (statusEl) statusEl.textContent = msg; };

    try {
    if (!INTERVIEW_ID) {
        toast('Select an interview before starting');
        return;
    }

    voiceLog('Starting session for interview', INTERVIEW_ID);
    setStatus('Requesting mic...');

    VoiceState.micStream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true }
    });

    VoiceState.pc = new RTCPeerConnection({
        iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
    });

    VoiceState.dc = VoiceState.pc.createDataChannel('oai-events');

    VoiceState.dc.addEventListener('open', () => {
        if (stopBtn) stopBtn.disabled = false;
    });

    VoiceState.dc.addEventListener('error', e => console.error('DataChannel error:', e));

    VoiceState.dc.addEventListener('message', e => {
        try {
        const msg = JSON.parse(e.data);
        
        if (msg?.type && !msg.type.includes('audio')) {
            console.log('Event:', msg.type, msg);
        }
        
        if (msg.type === 'session.created' && sessionCreated) return;
        
        handleDataChannelMessage(msg, setStatus);
        
        if (msg.type === 'session.created') sessionCreated = true;
        } catch (err) {
        console.warn('Non-JSON message:', err);
        }
    });

    VoiceState.pc.addEventListener('track', ev => {
        if (remote.srcObject) return;
        
        remote.srcObject = ev.streams[0];
        remote.volume = 1;
        remote.muted = false;
        VoiceState.remoteEl = remote;
        
        remote.play().catch(() => {
        setStatus('Connected - click to allow audio');
        document.addEventListener('click', () => remote.play(), { once: true });
        });
    });

    VoiceState.micStream.getAudioTracks().forEach(t => {
        VoiceState.pc.addTrack(t, VoiceState.micStream);
    });

    setStatus('Creating offer...');
    const offer = await VoiceState.pc.createOffer();
    await VoiceState.pc.setLocalDescription(offer);
    await waitForIceGathering(VoiceState.pc, 3000);

    setStatus('Getting session...');
    const sessionUrl = `/api/session?interview_id=${encodeURIComponent(INTERVIEW_ID)}`;
    const sessResp = await fetch(sessionUrl);
    
    if (!sessResp.ok) throw new Error(await sessResp.text());

    const sess = await sessResp.json();
    VoiceState.sessionId = sess?.id || null;
    
    const ephemeralKey = sess?.client_secret?.value;
    if (!ephemeralKey) throw new Error('No ephemeral key');

    setStatus('Exchanging SDP...');
    voiceLog('Received realtime session', sess.id);

    const oaResp = await fetch(
    `https://api.openai.com/v1/realtime?model=${encodeURIComponent(sess.model)}`,
    {
        method: 'POST',
        headers: {
        Authorization: `Bearer ${ephemeralKey}`,
        'Content-Type': 'application/sdp'
        },
        body: VoiceState.pc.localDescription.sdp
    }
    );

    if (!oaResp.ok) throw new Error(await oaResp.text());

    const cleanSdp = sanitizeSdp(await oaResp.text());
    await VoiceState.pc.setRemoteDescription({ type: 'answer', sdp: cleanSdp });
    
    setStatus('Connected');

} catch (err) {
    console.error('startVoice error:', err);
    setStatus('Error: ' + (err?.message || err));
    toast('Error: ' + (err?.message || 'Unknown'));
}
}

// ============================================================
// SAVE CONVERSATION
// ============================================================

async function saveConversationToServer() {
    const validMessages = VoiceState.messages.filter(m => m.content?.trim());

    if (!validMessages.length) {
    toast('No messages to save');
    return null;
    }

    const statusEl = $('status');

    try {
    const verifiedData = normalizeVerifiedData(VoiceState.verifiedData);

    voiceLog('Persisting conversation', {
        sessionId: VoiceState.sessionId,
        messages: validMessages.length,
        interviewId: INTERVIEW_ID,
        hasVerifiedData: Boolean(verifiedData)
    });

    if (statusEl) statusEl.textContent = 'Saving conversation...';

    const savePayload = {
        session_id: VoiceState.sessionId,
        messages: validMessages,
        interview_id: INTERVIEW_ID,
        ...(verifiedData && { verified_data: verifiedData })
    };

    const saveResp = await fetch('/api/conversation/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(savePayload)
    });

    if (!saveResp.ok) {
        console.error('Save failed:', await saveResp.text());
        toast('Save failed');
        return null;
    }

    const saveData = await saveResp.json();
    console.log('Conversation saved:', saveData);

    if (statusEl) statusEl.textContent = 'Analyzing responses...';

    const analyzePayload = {
        session_id: VoiceState.sessionId,
        ...(verifiedData && { verified_data: verifiedData })
    };

    const analyzeResp = await fetch('/api/conversation/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(analyzePayload)
    });

    if (!analyzeResp.ok) {
        console.error('Analysis failed:', await analyzeResp.text());
        toast('Conversation saved but analysis failed');
        return saveData;
    }

    const analyzeData = await analyzeResp.json();
    console.log('Analysis completed:', analyzeData);

    VoiceState.conversationSaved = true;
    toast('Conversation saved and analyzed');

    return { ...saveData, analysis: analyzeData };

    } catch (err) {
    console.error('Save/analyze error:', err);
    toast('Error: ' + err.message);
    return null;
    }
}

// ============================================================
// CLEANUP
// ============================================================

async function cleanup() {
    try {
        VoiceState.dc?.send(JSON.stringify({ type: 'session.disconnect' }));
    } catch {}

    VoiceState.micStream?.getTracks().forEach(t => t.stop());
    VoiceState.micStream = null;

    if (VoiceState.remoteEl) {
        VoiceState.remoteEl.pause?.();
        VoiceState.remoteEl.srcObject = null;
        VoiceState.remoteEl = null;
    }

    VoiceState.dc?.close?.();
    VoiceState.dc = null;

    VoiceState.pc?.getSenders?.().forEach(s => s.track?.stop?.());
    VoiceState.pc?.close?.();
    VoiceState.pc = null;
}

// ============================================================
// INITIALIZATION
// ============================================================

(() => {
  // Render verification fields
    renderVerificationFields();

    // Verification confirm handler
    $('verify-confirm')?.addEventListener('click', () => {
        const values = {};
        verificationInputMap.forEach((input, key) => {
        values[key] = input.value.trim();
        });
        VoiceState.verifiedData = values;
        hideVerificationPopup();

        const cleaned = normalizeVerifiedData(VoiceState.verifiedData);
        if (!cleaned) {
        toast('Add details before confirming');
        return;
        }

        toast('Information verified');
        
        if (sendVerifyToolOutput('verified', cleaned)) return;

        if (VoiceState.dc?.readyState === 'open') {
        const summary = buildVerificationSummary(cleaned);
        pushMessage('user', summary);
        
        VoiceState.dc.send(JSON.stringify({
            type: 'conversation.item.create',
            item: {
            type: 'message',
            role: 'user',
            content: [{ type: 'input_text', text: summary }]
            }
        }));
        VoiceState.dc.send(JSON.stringify({ type: 'response.create' }));
        }
    });

    // Verification cancel handler
    $('verify-cancel')?.addEventListener('click', () => {
        hideVerificationPopup();
        
        if (sendVerifyToolOutput('skipped')) {
        toast('Skipped verification');
        return;
        }
        toast('Verification cancelled');
    });

    // Stop button handler
    const stopBtn = $('stop');
    stopBtn?.addEventListener('click', async () => {
        stopBtn.disabled = true;
    
    const statusEl = $('status');
    if (statusEl) statusEl.textContent = 'Stopping...';

    await cleanup();

    if (statusEl) statusEl.textContent = 'Saving...';
    await saveConversationToServer();
    await toast('Conversation saved', 1500);
    
    location.reload();
    });

    // Start button handler
    $('start')?.addEventListener('click', () => {
        if (!INTERVIEW_ID) {
        toast('Missing interview configuration');
        return;
        }
        startVoice();
    });
})();

// Expose session ID for external access
Object.defineProperty(window, 'currentSessionId', {
    get: () => VoiceState.sessionId,
    set: val => { VoiceState.sessionId = val; }
});