async function waitForIceGathering(pc, timeout = 3000) {
    if (pc.iceGatheringState === "complete") return;
    return new Promise((res) => {
        const done = () => { pc.removeEventListener("icegatheringstatechange", done); clearTimeout(timer); res(); };
        const timer = setTimeout(() => { pc.removeEventListener("icegatheringstatechange", done); res(); }, timeout);
        pc.addEventListener("icegatheringstatechange", done);
    });
}

window.currentSessionId = null;
window._conversationSaved = false;
window._pc = null;
window._dc = null;
window._micStream = null;
window._remoteEl = null;
window._verifiedData = null;
window._verificationToolCallId = null;

const INTERVIEW_ID = window.INTERVIEW_ID || "";
const voiceLog = (...args) => console.log("[Voice]", ...args);

const conversationMessages = [];
let isNewAssistantResponse = true;

const VERIFICATION_FIELDS = Array.isArray(window.VERIFICATION_FIELDS)
    ? window.VERIFICATION_FIELDS
    : [];
const verificationFieldLookup = {};
const verificationInputMap = new Map();
VERIFICATION_FIELDS.forEach((field) => {
    verificationFieldLookup[field.key] = field;
});

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
            toastTimer = null;
            resolve();
        }, ms);
    });
}

function renderVerificationFields() {
    const container = $("verification-fields-container");
    if (!container) return;

    container.innerHTML = "";

    if (!VERIFICATION_FIELDS.length) {
        const emptyState = document.createElement("p");
        emptyState.className = "muted-text";
        emptyState.textContent = "No verification fields configured.";
        container.appendChild(emptyState);
        return;
    }

    VERIFICATION_FIELDS.forEach((field) => {
        const wrapper = document.createElement("div");
        wrapper.className = "field-group";
        if (field.source === "question") {
            wrapper.classList.add("question-field");
        }

        const label = document.createElement("label");
        label.setAttribute("for", `verify-${field.key}`);
        label.textContent = field.label || field.key;

        const input =
            field.type === "textarea"
                ? document.createElement("textarea")
                : document.createElement("input");
        input.id = `verify-${field.key}`;
        input.dataset.key = field.key;
        input.placeholder = field.placeholder || field.label || field.key;

        if (field.type === "textarea") {
            input.rows = Math.min(6, Math.max(3, Math.ceil((input.placeholder.length || 80) / 40)));
        } else {
            input.type = field.input_type || "text";
        }

        wrapper.append(label, input);
        container.appendChild(wrapper);
        verificationInputMap.set(field.key, input);
    });
}

renderVerificationFields();

const appendMessageToDom = (role, text = "", saveToMemory = true) => {
    const conv = $("conversation");
    if (!conv) return null;

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

function showVerificationPopup(data) {
    const popup = $("verification-popup");
    if (!popup) return;

    VERIFICATION_FIELDS.forEach((field) => {
        const input = verificationInputMap.get(field.key);
        if (input) {
            const fallback = window._verifiedData?.[field.key];
            const value = data && data[field.key] !== undefined ? data[field.key] : fallback || "";
            input.value = value;
        }
    });

    popup.style.display = "flex";
}

function hideVerificationPopup() {
    $("verification-popup").style.display = "none";
}

function normalizeVerifiedData(data) {
    if (!data || !VERIFICATION_FIELDS.length) return null;
    const cleaned = {};
    VERIFICATION_FIELDS.forEach((field) => {
        const rawValue = data[field.key];
        if (rawValue === undefined || rawValue === null) {
            return;
        }
        const value = rawValue.toString().trim();
        if (value) {
            cleaned[field.key] = value;
        }
    });
    return Object.keys(cleaned).length ? cleaned : null;
}

function getVerifiedDataPayload() {
    return normalizeVerifiedData(window._verifiedData);
}

function buildVerificationSummary(cleaned) {
    if (!cleaned) return "";
    const lines = ["Candidate confirmed their details:"];
    VERIFICATION_FIELDS.forEach((field) => {
        const value = cleaned[field.key];
        if (!value) return;
        const label = field.label || field.key;
        if (field.source === "question" && field.sequence_number) {
            lines.push(`- Q${field.sequence_number}: ${label}\n  ${value}`);
        } else {
            lines.push(`- ${label}: ${value}`);
        }
    });
    return lines.join("\n");
}

function resetVerificationToolContext() {
    window._verificationToolCallId = null;
}

function sendVerifyToolOutput(status, data = null) {
    if (!window._verificationToolCallId || !window._dc || window._dc.readyState !== "open") {
        return false;
    }

    const output = { status };
    if (data) {
        output.data = data;
    }

    window._dc.send(JSON.stringify({
        type: "conversation.item.create",
        item: {
            type: "function_call_output",
            call_id: window._verificationToolCallId,
            output: JSON.stringify(output)
        }
    }));
    window._dc.send(JSON.stringify({ type: "response.create" }));
    resetVerificationToolContext();
    return true;
}

// Setup verification popup handlers
(() => {
    $("verify-confirm")?.addEventListener("click", () => {
        const latestValues = {};
        verificationInputMap.forEach((input, key) => {
            latestValues[key] = input.value.trim();
        });
        window._verifiedData = latestValues;
        hideVerificationPopup();

        const cleaned = getVerifiedDataPayload();
        if (!cleaned) {
            toast("Add details before confirming");
            return;
        }

        toast("Information verified");
        if (sendVerifyToolOutput("verified", cleaned)) {
            return;
        }

        if (window._dc && window._dc.readyState === "open") {
            const summaryText = buildVerificationSummary(cleaned);
            pushMessage("user", summaryText);

            window._dc.send(JSON.stringify({
                type: "conversation.item.create",
                item: {
                    type: "message",
                    role: "user",
                    content: [{
                        type: "input_text",
                        text: summaryText
                    }]
                }
            }));
            window._dc.send(JSON.stringify({ type: "response.create" }));
        }
    });

    $("verify-cancel")?.addEventListener("click", () => {
        hideVerificationPopup();
        if (sendVerifyToolOutput("skipped")) {
            toast("Skipped verification");
            return;
        }
        toast("Verification cancelled");
    });
})();

async function startVoice() {
    const status = $("status"), remote = $("remote"), stopBtn = $("stop");
    let currentAssistant = null, aiStreaming = "", sessionCreated = false;

    try {
        if (!INTERVIEW_ID) {
            toast("Select an interview before starting");
            return;
        }

        voiceLog("Starting session for interview", INTERVIEW_ID);
        status && (status.textContent = "Requesting mic...");
        const mic = await navigator.mediaDevices.getUserMedia({
            audio: { echoCancellation: true, noiseSuppression: true }
        });
        window._micStream = mic;

        const pc = new RTCPeerConnection({
            iceServers: [{ urls: "stun:stun.l.google.com:19302" }]
        });
        window._pc = pc;

        const dc = pc.createDataChannel("oai-events");
        window._dc = dc;

        dc.addEventListener("open", () => {
            stopBtn && (stopBtn.disabled = false);
        });

        dc.addEventListener("error", (e) => console.error("DataChannel err:", e));

        dc.addEventListener("message", (e) => {
            try {
                const msg = JSON.parse(e.data);

                if (msg?.type && !String(msg.type).includes("audio")) {
                    console.log("Event:", msg.type, msg);
                }

                if (msg.type === "session.created" && !sessionCreated) {
                    sessionCreated = true;
                    // -- [API CALL]: Trigger AI to start a response after session established (WebRTC DataChannel)
                    dc.send(JSON.stringify({ type: "response.create" }));
                    status && (status.textContent = "Connected");
                }

                if (msg.type === "conversation.item.input_audio_transcription.completed") {
                    const t = (msg.transcript || "").trim();
                    if (t) {
                        appendMessageToDom("user", t, true);
                    }
                }

                if (msg.type === "response.created") {
                    aiStreaming = "";
                    isNewAssistantResponse = true;
                    currentAssistant = appendMessageToDom("assistant", "", false);
                    return;
                }

                if (msg.type === "response.audio_transcript.delta") {
                    aiStreaming += msg.delta || "";
                    if (aiStreaming) {
                        updateStreaming(currentAssistant, aiStreaming);
                    }
                    return;
                }

                if (msg.type === "response.audio_transcript.done") {
                    const finalText = (msg.transcript || aiStreaming || "").trim();

                    if (finalText) {
                        if (currentAssistant) {
                            finalize(currentAssistant, finalText);
                        } else {
                            appendMessageToDom("assistant", finalText, true);
                        }
                    } else if (currentAssistant && currentAssistant.msgEl) {
                        currentAssistant.msgEl.remove();
                    }

                    aiStreaming = "";
                    currentAssistant = null;
                    isNewAssistantResponse = true;
                    return;
                }

                // Handle tool calls
                if (msg.type === "response.function_call_arguments.done") {
                    if (currentAssistant && currentAssistant.bubbleEl && !currentAssistant.bubbleEl.textContent.trim()) {
                        currentAssistant.msgEl.remove();
                    }
                    currentAssistant = null;
                    isNewAssistantResponse = true;

                    const funcName = msg.name;
                    const args = JSON.parse(msg.arguments || "{}");
                    
                    console.log("Tool call:", funcName, args);
                    
                    if (funcName === "verify_information") {
                        // Store the call_id and args for later verification
                        window._verificationToolCallId = msg.call_id;
                        appendMessageToDom("assistant", "Before we conclude, would you like to verify and confirm your information?", true);
                        showVerificationPopup(args);
                    }
                    return;
                }

            } catch (err) {
                console.warn("Non-JSON message:", e?.data || err);
            }
        });

        pc.addEventListener("track", (ev) => {
            if (!remote.srcObject) {
                remote.srcObject = ev.streams[0];
                remote.volume = 1;
                remote.muted = false;
                window._remoteEl = remote;
                remote.play().catch(() => {
                    status && (status.textContent = "Connected - click to allow audio");
                    document.addEventListener("click", () => remote.play(), { once: true });
                });
            }
        });

        mic.getAudioTracks().forEach(t => pc.addTrack(t, mic));

        status && (status.textContent = "Creating offer...");
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        await waitForIceGathering(pc, 3000);

        status && (status.textContent = "Getting session...");
        // -- [API CALL]: Get ephemeral session and key from backend
        const sessionUrl = INTERVIEW_ID
            ? `/api/session?interview_id=${encodeURIComponent(INTERVIEW_ID)}`
            : "/api/session";

        const sessResp = await fetch(sessionUrl);
        if (!sessResp.ok) throw new Error(await sessResp.text());
        const sess = await sessResp.json();
        window.currentSessionId = sess?.id || null;
        const ephemeralKey = sess?.client_secret?.value;
        if (!ephemeralKey) throw new Error("No ephemeral key");

        status && (status.textContent = "Exchanging SDP...");
        voiceLog("Received realtime session", sess.id);
        // -- [API CALL]: Exchange SDP with OpenAI Realtime API using ephemeral key
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
        if (!oaResp.ok) throw new Error(await oaResp.text());
        const answerSdp = await oaResp.text();
        await pc.setRemoteDescription({ type: "answer", sdp: answerSdp });

        status && (status.textContent = "Connected");
    } catch (err) {
        console.error("startVoice err:", err);
        $("status") && ($("status").textContent = "Error: " + (err?.message || err));
        toast("Error: " + (err?.message || "Unknown"));
    }
}

async function saveConversationToServer(sessionId = null) {
    const validMessages = conversationMessages.filter(m =>
        m.content && m.content.trim().length > 0
    );

    if (!validMessages.length) {
        toast("No messages to save");
        return null;
    }

    try {
        const verifiedData = getVerifiedDataPayload();
        voiceLog("Persisting conversation", {
            sessionId,
            messages: validMessages.length,
            interviewId: INTERVIEW_ID,
            hasVerifiedData: Boolean(verifiedData)
        });
        $("status") && ($("status").textContent = "Saving conversation...");
        const savePayload = {
            session_id: sessionId,
            messages: validMessages,
            interview_id: INTERVIEW_ID
        };
        if (verifiedData) {
            savePayload.verified_data = verifiedData;
        }
        // -- [API CALL]: Save conversation messages to backend
        const saveResp = await fetch("/api/conversation/", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(savePayload)
        });

        if (!saveResp.ok) {
            console.error("Save failed:", await saveResp.text());
            toast("Save failed");
            return null;
        }

        const saveData = await saveResp.json();
        console.log("Conversation saved:", saveData);

        $("status") && ($("status").textContent = "Analyzing responses...");
        const analyzePayload = { session_id: sessionId };
        if (verifiedData) {
            analyzePayload.verified_data = verifiedData;
        }
        // -- [API CALL]: Request backend to analyze saved conversation
        const analyzeResp = await fetch("/api/conversation/analyze", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(analyzePayload)
        });

        if (!analyzeResp.ok) {
            console.error("Analysis failed:", await analyzeResp.text());
            toast("Conversation saved but analysis failed");
            return saveData;
        }

        const analyzeData = await analyzeResp.json();
        console.log("Analysis completed:", analyzeData);

        window._conversationSaved = true;
        toast("Conversation saved and analyzed");
        return { ...saveData, analysis: analyzeData };

    } catch (err) {
        console.error("Save/analyze error:", err);
        toast("Error: " + err.message);
        return null;
    }
}

(() => {
    const stopBtn = $("stop");
    if (!stopBtn) return;
    if (stopBtn._wired) return;
    stopBtn._wired = true;

    stopBtn.addEventListener("click", async () => {
        stopBtn.disabled = true;
        $("status") && ($("status").textContent = "Stopping...");

        try {
            if (window._dc && window._dc.readyState === "open") {
                // -- [API CALL]: Notify AI to disconnect the realtime session (WebRTC DataChannel)
                window._dc.send(JSON.stringify({ type: "session.disconnect" }));
            }
        } catch (e) {
            console.warn("dc notify failed", e);
        }

        try {
            const mic = window._micStream;
            if (mic && mic.getTracks) {
                mic.getTracks().forEach((t) => t.stop());
                window._micStream = null;
            }
        } catch (e) {
            console.warn("stop mic failed", e);
        }

        try {
            const remoteEl = window._remoteEl || $("remote");
            if (remoteEl) {
                remoteEl.pause?.();
                remoteEl.srcObject = null;
                remoteEl.removeAttribute?.("src");
                window._remoteEl = null;
            }
        } catch (e) {
            console.warn("clear remote failed", e);
        }

        try {
            if (window._dc) {
                window._dc.close?.();
                window._dc = null;
            }
        } catch (e) {
            console.warn("close dc failed", e);
        }

        try {
            if (window._pc) {
                window._pc.getSenders?.().forEach((s) => s.track?.stop?.());
                window._pc.close?.();
                window._pc = null;
            }
        } catch (e) {
            console.warn("close pc failed", e);
        }

        $("status") && ($("status").textContent = "Saving...");
        await saveConversationToServer(window.currentSessionId);
        await toast("Conversation saved", 1500);
        location.reload();
    });
})();

const startButton = document.getElementById("start");
startButton?.addEventListener("click", () => {
    if (!INTERVIEW_ID) {
        toast("Missing interview configuration");
        return;
    }
    startVoice();
});
