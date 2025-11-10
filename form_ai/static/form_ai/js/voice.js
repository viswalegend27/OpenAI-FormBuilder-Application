// wait for ICE to finish or timeout
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

/*-------------------------
Minimal conversation memory
------------------------- */
const conversationMessages = []; 

const pushMessage = (role, text) => {
    if (!text || !text.trim()) return; // Prevent empty messages from being pushed into my code.
    conversationMessages.push({ 
        role, 
        content: text.trim(), 
        ts: new Date().toISOString() 
    });
};

// Logic to look out for uploading updates if only text.
const updateLastAssistant = (text) => {
    if (!text || !text.trim()) return; //ADDED: Prevent empty updates
    
    for (let i = conversationMessages.length - 1; i >= 0; i--) {
        if (conversationMessages[i].role === "assistant") { 
            conversationMessages[i].content = text.trim(); 
            conversationMessages[i].ts = new Date().toISOString(); 
            return; 
        }
    }
    pushMessage("assistant", text);
};

/*-------------------------
    Compact UI helpers
------------------------- */
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

// Add a flag to control whether to save to conversationMessages
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
    meta.textContent = role === "user" ? "You" : "Assistant";
    
    msg.append(bubble, meta); 
    conv.appendChild(msg); 
    conv.scrollTop = conv.scrollHeight;
    
    // Only save to memory if flag is true AND text is not empty
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

// Only finalize if there's actual text
const finalize = (el, text) => { 
    if (!el) return;
    
    const trimmedText = (text || "").trim();
    
    // If no text, remove the element from DOM
    if (!trimmedText) {
        el.msgEl.remove();
        return;
    }
    
    el.bubbleEl.textContent = trimmedText; 
    el.msgEl.classList.remove("streaming"); 
    updateLastAssistant(trimmedText); 
    el.msgEl.scrollIntoView({ block: "end", behavior: "smooth" }); 
};

/*-------------------------
    Main flow: startVoice
------------------------- */
async function startVoice() {
    const status = $("status"), remote = $("remote"), stopBtn = $("stop");
    let currentAssistant = null, aiStreaming = "", sessionCreated = false;

    try {
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
                    console.log("Event:", msg.type);
                }

                if (msg.type === "session.created" && !sessionCreated) {
                    sessionCreated = true;
                    dc.send(JSON.stringify({ type: "response.create" }));
                    status && (status.textContent = "Connected");
                }

                // Save user transcripts only if non-empty
                if (msg.type === "conversation.item.input_audio_transcription.completed") {
                    const t = (msg.transcript || "").trim();
                    if (t) {
                        appendMessageToDom("user", t, true); // Save to memory
                    }
                }

                // Create placeholder without saving to memory
                if (msg.type === "response.created") { 
                    aiStreaming = ""; 
                    currentAssistant = appendMessageToDom("assistant", "", false); // Don't save yet
                    return; 
                }
                
                // Update streaming (still don't save)
                if (msg.type === "response.audio_transcript.delta") { 
                    aiStreaming += msg.delta || ""; 
                    if (aiStreaming) {
                        updateStreaming(currentAssistant, aiStreaming); 
                    }
                    return; 
                }
                
                // ✅ FIX: Only finalize and save if there's actual content
                if (msg.type === "response.audio_transcript.done") {
                    const finalText = (msg.transcript || aiStreaming || "").trim();
                    
                    if (finalText) {
                    if (currentAssistant) {
                        finalize(currentAssistant, finalText);
                    } else {
                    appendMessageToDom("assistant", finalText, true); // Save to memory
                    }}
                    else if (currentAssistant && currentAssistant.msgEl) {
                            currentAssistant.msgEl.remove();}
                    aiStreaming = ""; 
                    currentAssistant = null; 
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
                    status && (status.textContent = "Connected — click to allow audio"); 
                    document.addEventListener("click", () => remote.play(), { once: true });
                });
            }
        });

        pc.addEventListener("iceconnectionstatechange", () => 
            console.log("ICE:", pc.iceConnectionState)
        );
        pc.addEventListener("connectionstatechange", () => 
            console.log("Conn:", pc.connectionState)
        );

        mic.getAudioTracks().forEach(t => pc.addTrack(t, mic));

        status && (status.textContent = "Creating offer...");
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        await waitForIceGathering(pc, 3000);

        status && (status.textContent = "Getting session...");
        const sessResp = await fetch("/api/session");
        if (!sessResp.ok) throw new Error(await sessResp.text());
        const sess = await sessResp.json();
        window.currentSessionId = sess?.id || null;
        const ephemeralKey = sess?.client_secret?.value;
        if (!ephemeralKey) throw new Error("No ephemeral key");

        status && (status.textContent = "Exchanging SDP...");
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

/* -----------------------------
    Save conversation (simple)
------------------------------ */
async function saveConversationToServer(sessionId = null) {
    // Filter out any empty messages before saving
    const validMessages = conversationMessages.filter(m => 
        m.content && m.content.trim().length > 0
    );
    
    if (!validMessages.length) {
        toast("No messages to save");
        return null;
    }
    
    try {
        // Step 1: Save conversation
        $("status") && ($("status").textContent = "Saving conversation...");
        const saveResp = await fetch("/api/conversation/", { 
            method: "POST", 
            headers: { "Content-Type": "application/json" }, 
            body: JSON.stringify({ 
                session_id: sessionId, 
                messages: validMessages 
            }) 
        });
        
        if (!saveResp.ok) { 
            console.error("Save failed:", await saveResp.text()); 
            toast("Save failed");
            return null; 
        }
        
        const saveData = await saveResp.json();
        console.log("Conversation saved:", saveData);
        
        // Step 2: Analyze conversation to extract user_response
        $("status") && ($("status").textContent = "Analyzing responses...");
        const analyzeResp = await fetch("/api/conversation/analyze", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ 
                session_id: sessionId 
            })
        });
        
        if (!analyzeResp.ok) {
            console.error("Analysis failed:", await analyzeResp.text());
            toast("Conversation saved but analysis failed");
            return saveData;
        }
        
        const analyzeData = await analyzeResp.json();
        console.log("Analysis completed:", analyzeData);
        
        window._conversationSaved = true;
        toast("Conversation saved & analyzed ✓");
        return { ...saveData, analysis: analyzeData };
        
    } catch (err) { 
        console.error("Save/analyze error:", err); 
        toast("Error: " + err.message); 
        return null; 
    }
}

/* ---------------------------
    Stop wiring & unload save
---------------------------- */
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

/* -------------------------
    Hook start button
------------------------- */
document.getElementById("start")?.addEventListener("click", startVoice);