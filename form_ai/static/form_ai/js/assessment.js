/**
 * ============================================================
 * ASSESSMENT INTERVIEW - WebRTC Voice Interface
 * Optimized Production Version
 * ============================================================
 */

// ============================================================
// GLOBAL STATE
// ============================================================

window.currentSessionId = null;
window._pc = null;
window._dc = null;
window._micStream = null;
window._remoteEl = null;

const conversationMessages = [];
const qaMapping = {};

let isNewAssistantResponse = true;
let currentQuestionIndex = 0;
let sessionCreated = false;

const LOG_STYLES = {
    info: "color:#2563eb;font-weight:700",
    success: "color:#16a34a;font-weight:700",
    warn: "color:#d97706;font-weight:700",
    error: "color:#dc2626;font-weight:700"
};

const logInfo = (msg, ...rest) => console.log(`%c[ASSESSMENT] ${msg}`, LOG_STYLES.info, ...rest);
const logSuccess = (msg, ...rest) => console.log(`%c[ASSESSMENT] ${msg}`, LOG_STYLES.success, ...rest);
const logWarn = (msg, ...rest) => console.warn(`%c[ASSESSMENT] ${msg}`, LOG_STYLES.warn, ...rest);
const logError = (msg, ...rest) => console.error(`%c[ASSESSMENT] ${msg}`, LOG_STYLES.error, ...rest);

const startButtonEl = document.getElementById("start");
const defaultStartLabel = startButtonEl ? (startButtonEl.textContent.trim() || "Start Assessment") : "Start Assessment";
const setStartButtonState = (label, disabled) => {
    if (!startButtonEl) return;
    if (label) startButtonEl.textContent = label;
    if (typeof disabled === "boolean") startButtonEl.disabled = disabled;
};

const sanitizeQuestionList = (source) => {
    if (!Array.isArray(source)) return [];
    return source
        .map((item) => {
            if (typeof item === "string") return item.trim();
            if (item && typeof item === "object") {
                return (item.text || item.question || item.prompt || "").trim();
            }
            return typeof item === "number" ? String(item) : "";
        })
        .filter((text) => text && text.length);
};

const ASSESSMENT_QUESTION_TEXT = sanitizeQuestionList(window.ASSESSMENT_QUESTIONS);
const MAX_ASSESSMENT_QUESTIONS = ASSESSMENT_QUESTION_TEXT.length || 3;

logSuccess("Assessment UI ready");
logInfo(`Loaded ${MAX_ASSESSMENT_QUESTIONS} assessment question(s)`);

// ============================================================
// UTILITIES
// ============================================================

const $ = (id) => document.getElementById(id);
let toastTimer;

function toast(msg, ms = 3000) {
    const t = $("toast-message");
    if (!t) return Promise.resolve();
    t.textContent = msg;
    t.classList.add("show");
    clearTimeout(toastTimer);
    return new Promise((resolve) => {
        if (ms <= 0) return resolve();
        toastTimer = setTimeout(() => {
            t.classList.remove("show");
            resolve();
        }, ms);
    });
}

async function waitForIceGathering(pc, timeout = 3000) {
    if (pc.iceGatheringState === "complete") return;
    return new Promise((res) => {
        const done = () => {
            pc.removeEventListener("icegatheringstatechange", done);
            clearTimeout(timer);
            res();
        };
        const timer = setTimeout(() => {
            pc.removeEventListener("icegatheringstatechange", done);
            res();
        }, timeout);
        pc.addEventListener("icegatheringstatechange", done);
    });
}

// ============================================================
// MESSAGE MANAGEMENT
// ============================================================

const pushMessage = (role, text) => {
    if (!text || !text.trim()) return;
    conversationMessages.push({
        role,
        content: text.trim(),
        ts: new Date().toISOString()
    });
};

const updateLastAssistant = (text) => {
    if (!text || !text.trim()) return;
    
    if (isNewAssistantResponse) {
        pushMessage("assistant", text);
        isNewAssistantResponse = false;
        return;
    }
    
    for (let i = conversationMessages.length - 1; i >= 0; i--) {
        if (conversationMessages[i].role === "assistant") {
            conversationMessages[i].content = text.trim();
            conversationMessages[i].ts = new Date().toISOString();
            return;
        }
    }
    pushMessage("assistant", text);
};

// ============================================================
// DOM RENDERING
// ============================================================

const appendMessageToDom = (role, text = "", saveToMemory = true) => {
    const conv = $("conversation");
    if (!conv) return null;

    const welcome = conv.querySelector('.welcome-message');
    if (welcome) welcome.remove();

    if (conv.classList.contains("empty")) conv.classList.remove("empty");

    const msg = document.createElement("div");
    msg.className = "message " + (role === "user" ? "user" : "assistant");

    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = text;

    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = role === "user" ? "You" : "Tyler";

    msg.append(bubble, meta);
    conv.appendChild(msg);
    conv.scrollTop = conv.scrollHeight;

    if (saveToMemory && text && text.trim()) {
        pushMessage(role, text);
    }

    return { msgEl: msg, bubbleEl: bubble };
};

const updateStreaming = (el, text) => {
    if (!el || !text) return;
    el.bubbleEl.textContent = text;
    el.msgEl.classList.add("streaming");
    updateLastAssistant(text);
    el.msgEl.scrollIntoView({ block: "end", behavior: "smooth" });
};

const finalize = (el, text) => {
    if (!el) return;
    const trimmedText = (text || "").trim();
    if (!trimmedText) {
        el.msgEl.remove();
        return;
    }
    el.bubbleEl.textContent = trimmedText;
    el.msgEl.classList.remove("streaming");
    updateLastAssistant(trimmedText);
    el.msgEl.scrollIntoView({ block: "end", behavior: "smooth" });
};

// ============================================================
// QUESTION TRACKING (Simple & Reliable)
// ============================================================

function isLikelyQuestion(text) {
    const lower = text.toLowerCase();
    const questionIndicators = [
        'question',
        'what is',
        'what are',
        'how does',
        'explain',
        'describe',
        'can you tell',
        'moving on',
        "let's move"
    ];
    
    return questionIndicators.some(indicator => lower.includes(indicator));
}

// ============================================================
// WEBRTC SESSION
// ============================================================

async function startAssessment() {
    const status = $("status");
    const remote = $("remote");
    const stopBtn = $("stop");
    
    let currentAssistant = null;
    let aiStreaming = "";

    try {
        status && (status.textContent = "Requesting microphone...");
        
        const mic = await navigator.mediaDevices.getUserMedia({
            audio: {
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true
            }
        });
        window._micStream = mic;

        const pc = new RTCPeerConnection({
            iceServers: [{ urls: "stun:stun.l.google.com:19302" }]
        });
        window._pc = pc;

        const dc = pc.createDataChannel("oai-events");
        window._dc = dc;

        // ========================================================
        // DATA CHANNEL EVENTS
        // ========================================================

        dc.addEventListener("open", () => {
            logSuccess("Data channel connected");
            stopBtn && (stopBtn.disabled = false);
        });

        dc.addEventListener("error", (e) => {
            logError("Connection error", e);
            toast("Connection error");
        });

        dc.addEventListener("message", (e) => {
            try {
                const msg = JSON.parse(e.data);

                // ===== SESSION CREATED =====
                if (msg.type === "session.created" && !sessionCreated) {
                    sessionCreated = true;
                    // -- [API CALL]: Trigger AI to start a response after session is established (WebRTC DataChannel)
                    dc.send(JSON.stringify({ type: "response.create" }));
                    status && (status.textContent = "Assessment in progress");
                    logSuccess("Realtime session started");
                }

                // ===== USER SPOKE =====
                if (msg.type === "conversation.item.input_audio_transcription.completed") {
                    const transcript = (msg.transcript || "").trim();
                    
                    if (transcript) {
                        appendMessageToDom("user", transcript, true);
                        
                        // Assign to current question sequentially
                        const qKey = `q${currentQuestionIndex + 1}`;
                        
                        if (currentQuestionIndex < MAX_ASSESSMENT_QUESTIONS && !qaMapping[qKey]) {
                            qaMapping[qKey] = transcript;
                            logSuccess(`${qKey} captured: "${transcript.substring(0, 60)}..."`);
                            currentQuestionIndex++;
                        }
                    }
                }

                // ===== ASSISTANT STARTS =====
                if (msg.type === "response.created") {
                    aiStreaming = "";
                    isNewAssistantResponse = true;
                    currentAssistant = appendMessageToDom("assistant", "", false);
                    return;
                }

                // ===== ASSISTANT STREAMING =====
                if (msg.type === "response.audio_transcript.delta") {
                    aiStreaming += msg.delta || "";
                    if (aiStreaming && currentAssistant) {
                        updateStreaming(currentAssistant, aiStreaming);
                    }
                    return;
                }

                // ===== ASSISTANT DONE =====
                if (msg.type === "response.audio_transcript.done") {
                    const finalText = (msg.transcript || aiStreaming || "").trim();

                    if (finalText) {
                        if (currentAssistant) {
                            finalize(currentAssistant, finalText);
                        } else {
                            appendMessageToDom("assistant", finalText, true);
                        }
                        
                        // Log if this looks like a question
                        if (isLikelyQuestion(finalText)) {
                            const nextQuestionNumber = Math.min(
                                currentQuestionIndex + 1,
                                MAX_ASSESSMENT_QUESTIONS
                            );
                            logWarn(`Waiting for response to Q${nextQuestionNumber}`);
                        }
                    } else if (currentAssistant && currentAssistant.msgEl) {
                        currentAssistant.msgEl.remove();
                    }

                    aiStreaming = "";
                    currentAssistant = null;
                    isNewAssistantResponse = true;
                    return;
                }

                // ===== ERROR =====
                if (msg.type === "error") {
                    logError("OpenAI error", msg);
                    toast("Session error occurred");
                }

            } catch (err) {
                // Ignore non-JSON messages
            }
        });

        // ========================================================
        // PEER CONNECTION
        // ========================================================

        pc.addEventListener("track", (ev) => {
            if (!remote.srcObject) {
                remote.srcObject = ev.streams[0];
                remote.volume = 1;
                remote.muted = false;
                window._remoteEl = remote;
                
                remote.play().catch(() => {
                    status && (status.textContent = "Click anywhere to enable audio");
                    document.addEventListener("click", () => remote.play(), { once: true });
                });
            }
        });

        pc.addEventListener("iceconnectionstatechange", () => {
            if (pc.iceConnectionState === "failed" || pc.iceConnectionState === "disconnected") {
                toast("Connection lost", 5000);
            }
        });

        // ========================================================
        // SETUP
        // ========================================================

        mic.getAudioTracks().forEach(t => pc.addTrack(t, mic));

        status && (status.textContent = "Creating connection...");
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        await waitForIceGathering(pc, 3000);

        // ========================================================
        // CREATE SESSION
        // ========================================================

        status && (status.textContent = "Getting session...");
        // -- [API CALL]: Create ephemeral session on backend (assessment mode) and retrieve ephemeral key
        const questionPayload = ASSESSMENT_QUESTION_TEXT;
        if (!questionPayload.length) {
            logWarn("Assessment question payload empty; backend will use interview defaults");
        }

        const sessResp = await fetch("/api/session", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                assessment_mode: true,
                qualification: window.USER_INFO?.qualification || "",
                experience: window.USER_INFO?.experience || "",
                questions: questionPayload,
                interview_id: window.INTERVIEW_ID || null
            })
        });

        if (!sessResp.ok) throw new Error("Session creation failed");

        const sess = await sessResp.json();
        window.currentSessionId = sess?.id || null;
        const ephemeralKey = sess?.client_secret?.value;
        
        if (!ephemeralKey) throw new Error("No ephemeral key");

        // ========================================================
        // CONNECT TO OPENAI
        // ========================================================

        status && (status.textContent = "Connecting...");
        // -- [API CALL]: Exchange SDP with OpenAI Realtime API using the ephemeral key
        const oaResp = await fetch(
            `https://api.openai.com/v1/realtime?model=${encodeURIComponent(sess.model)}`,
            {
                method: "POST",
                headers: {
                    Authorization: `Bearer ${ephemeralKey}`,
                    "Content-Type": "application/sdp"
                },
                body: pc.localDescription.sdp
            }
        );

        if (!oaResp.ok) throw new Error("OpenAI connection failed");

        const answerSdp = await oaResp.text();
        await pc.setRemoteDescription({ type: "answer", sdp: answerSdp });

        status && (status.textContent = "Connected");
        setStartButtonState("Running", true);
        logSuccess("Assessment channel active");

    } catch (err) {
        logError(`Fatal error: ${err.message}`);
        $("status") && ($("status").textContent = `Error: ${err.message}`);
        toast(`Error: ${err.message}`, 5000);
        cleanupResources();
        setStartButtonState(defaultStartLabel, false);
    }
}

// ============================================================
// CLEANUP
// ============================================================

function cleanupResources() {
    try {
        if (window._micStream?.getTracks) {
            window._micStream.getTracks().forEach(t => t.stop());
            window._micStream = null;
        }
    } catch (e) {}

    try {
        const remoteEl = window._remoteEl || $("remote");
        if (remoteEl) {
            remoteEl.pause?.();
            remoteEl.srcObject = null;
            window._remoteEl = null;
        }
    } catch (e) {}

    try {
        window._dc?.close?.();
        window._dc = null;
    } catch (e) {}

    try {
        window._pc?.getSenders?.().forEach(s => s.track?.stop?.());
        window._pc?.close?.();
        window._pc = null;
    } catch (e) {}
}

// ============================================================
// SAVE ASSESSMENT
// ============================================================

async function saveAssessmentToServer(assessmentId, sessionId = null) {
    const validMessages = conversationMessages
        .filter(m => m.content && m.content.trim())
        .sort((a, b) => new Date(a.ts) - new Date(b.ts));

    if (!validMessages.length) {
        toast("No conversation to save");
        return null;
    }

    logInfo("Persisting assessment transcript");
    logInfo(`Messages captured: ${validMessages.length}`);
    logInfo(`Answers captured: ${Object.keys(qaMapping).length}`, qaMapping);

    try {
        $("status") && ($("status").textContent = "Saving...");

        // Save messages
        // -- [API CALL]: Save assessment conversation messages to backend
        const saveResp = await fetch(`/assessment/${assessmentId}/save/`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                session_id: sessionId,
                messages: validMessages
            })
        });

        if (!saveResp.ok) {
            logError("Transcript save failed");
            toast("Save failed");
            return null;
        }

        const saveData = await saveResp.json();
        logSuccess("Transcript saved");

        // Analyze answers
        $("status") && ($("status").textContent = "Analyzing...");
        // -- [API CALL]: Request backend to analyze answers using captured Q&A mapping
        const analyzeResp = await fetch(`/assessment/${assessmentId}/analyze/`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ qa_mapping: qaMapping })
        });

        if (!analyzeResp.ok) {
            logError("Answer extraction failed");
            toast("Saved but analysis failed", 4000);
            return saveData;
        }

        const analyzeData = await analyzeResp.json();
        logSuccess("Answer extraction complete", analyzeData.answers);

        toast("Assessment completed!", 2000);

        setTimeout(() => {
            $("status") && ($("status").textContent = "Completed!");
            showCompletionMessage();
        }, 2000);

        return { ...saveData, analysis: analyzeData };

    } catch (err) {
        logError(`Save error: ${err.message}`);
        toast(`Error: ${err.message}`, 5000);
        return null;
    }
}

// ============================================================
// COMPLETION UI
// ============================================================

function showCompletionMessage() {
    const conv = $("conversation");
    if (!conv) return;

    const completion = document.createElement("div");
    completion.className = "completion-message";
    completion.innerHTML = `
        <div class="completion-content">
            <h3>Assessment Completed</h3>
            <p>Thank you for completing the technical assessment!</p>
            <p class="sub-text">Your responses have been recorded.</p>
            <p class="sub-text">You may now close this window.</p>
        </div>
    `;
    conv.appendChild(completion);
    conv.scrollTop = conv.scrollHeight;
}

// ============================================================
// EVENT LISTENERS
// ============================================================

startButtonEl?.addEventListener("click", () => {
    setStartButtonState("Starting...", true);
    startAssessment();
});

(() => {
    const stopBtn = $("stop");
    if (!stopBtn || stopBtn._wired) return;
    stopBtn._wired = true;

    stopBtn.addEventListener("click", async () => {
        logWarn("Stopping assessment session");
        
        stopBtn.disabled = true;
        $("status") && ($("status").textContent = "Ending...");

        try {
            if (window._dc?.readyState === "open") {
                // -- [API CALL]: Notify AI to disconnect the realtime session (WebRTC DataChannel)
                window._dc.send(JSON.stringify({ type: "session.disconnect" }));
            }
        } catch (e) {}

        cleanupResources();

        const assessmentId = window.ASSESSMENT_ID;
        if (assessmentId) {
            await saveAssessmentToServer(assessmentId, window.currentSessionId);
        } else {
            toast("Error: No assessment ID", 5000);
            logError("No assessment ID available");
        }

        setStartButtonState(defaultStartLabel, false);
    });
})();

// ============================================================
// INIT
// ============================================================

logInfo(`Assessment ID: ${window.ASSESSMENT_ID}`);
logInfo("Questions payload:", window.ASSESSMENT_QUESTIONS);
logInfo("User payload:", window.USER_INFO);
