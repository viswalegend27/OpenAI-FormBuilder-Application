// wait for ICE to finish or timeout
async function waitForIceGathering(pc, timeout = 3000) {
    if (pc.iceGatheringState === "complete") return;
    return new Promise((res) => {
    const done = () => { pc.removeEventListener("icegatheringstatechange", done); clearTimeout(timer); res(); };
    const timer = setTimeout(() => { pc.removeEventListener("icegatheringstatechange", done); res(); }, timeout);
    pc.addEventListener("icegatheringstatechange", done);
});}

window.currentSessionId = null;
window._conversationSaved = false; 
/*-------------------------
Minimal conversation memory
------------------------- */
const conversationMessages = []; 
const pushMessage = (role, text) => conversationMessages.push({ role, content: text, ts: new Date().toISOString() });
const updateLastAssistant = (text) => {
    for (let i = conversationMessages.length - 1; i >= 0; i--) {
    if (conversationMessages[i].role === "assistant") { conversationMessages[i].content = text; conversationMessages[i].ts = new Date().toISOString(); return; }
    }
pushMessage("assistant", text);};

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
});}

const appendMessageToDom = (role, text = "") => {
    const conv = $("conversation"); if (!conv) return null;
    if (conv.classList.contains("empty")) conv.classList.remove("empty");
        const msg = document.createElement("div"); msg.className = "message " + (role === "user" ? "user" : "assistant");
        const bubble = document.createElement("div"); bubble.className = "bubble"; bubble.textContent = text;
        const meta = document.createElement("div"); meta.className = "meta"; meta.textContent = role === "user" ? "You" : "Assistant";
    msg.append(bubble, meta); conv.appendChild(msg); conv.scrollTop = conv.scrollHeight;
    // Fixing roles
    role === "assistant" ? pushMessage("assistant", text) : pushMessage("user", text);
    return { msgEl: msg, bubbleEl: bubble };
};

// Streaming my transcript
const updateStreaming = (el, text) => 
    { if (!el) return; el.bubbleEl.textContent = text; 
    el.msgEl.classList.add("streaming"); updateLastAssistant(text); 
    el.msgEl.scrollIntoView({ block: "end", behavior: "smooth" }); };

// Finalizing the transcript
const finalize = (el, text) => { if (!el) return; el.bubbleEl.textContent = text; 
    el.msgEl.classList.remove("streaming"); updateLastAssistant(text); 
    el.msgEl.scrollIntoView({ block: "end", behavior: "smooth" }); };

/*-------------------------
    Main flow: startVoice
------------------------- */
async function startVoice() {
    const status = $("status"), remote = $("remote"), stopBtn = $("stop");
    let currentAssistant = null, aiStreaming = "", sessionCreated = false;

    try {
    status && (status.textContent = "Requesting mic...");
    const mic = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });

    const pc = new RTCPeerConnection({ iceServers: [{ urls: "stun:stun.l.google.com:19302" }] });
    const dc = pc.createDataChannel("oai-events");

    dc.addEventListener("open", () => { stopBtn && (stopBtn.disabled = false); });
    dc.addEventListener("error", (e) => console.error("DataChannel err:", e));
    dc.addEventListener("message", (e) => {
        try {
        const msg = JSON.parse(e.data);
        // non-audio events (debug)
        if (msg?.type && !String(msg.type).includes("audio")) console.log("Event:", msg.type);

        if (msg.type === "session.created" && !sessionCreated) {
            sessionCreated = true;
          dc.send(JSON.stringify({ type: "response.create" })); // Here's where greeting is triggered
            status && (status.textContent = "Connected");
        }

        if (msg.type === "conversation.item.input_audio_transcription.completed") {
            const t = msg.transcript || ""; if (t) appendMessageToDom("user", t);
        }

        if (msg.type === "response.created") { aiStreaming = ""; currentAssistant = appendMessageToDom("assistant", ""); return; }
        if (msg.type === "response.audio_transcript.delta") { aiStreaming += msg.delta || ""; if (aiStreaming) updateStreaming(currentAssistant, aiStreaming); return; }
        if (msg.type === "response.audio_transcript.done") {
            const finalText = (msg.transcript || aiStreaming || "").trim();
            if (finalText) currentAssistant ? finalize(currentAssistant, finalText) : appendMessageToDom("assistant", finalText);
            aiStreaming = ""; currentAssistant = null; return;
        }
    } catch (err) { console.warn("Non-JSON message:", e?.data || err); }
    });

    pc.addEventListener("track", (ev) => {
    if (!remote.srcObject) { 
        remote.srcObject = ev.streams[0]; 
        remote.volume = 1; 
        remote.muted = false; 
        remote.play().catch(() => 
            {   status && (status.textContent = "Connected — click to allow audio"); 
                document.addEventListener("click", () => remote.play(), 
                { once: true }); }); }});

    pc.addEventListener("iceconnectionstatechange", () => console.log("ICE:", pc.iceConnectionState));
    pc.addEventListener("connectionstatechange", () => console.log("Conn:", pc.connectionState));

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
    const oaResp = await fetch(`https://api.openai.com/v1/realtime?model=${encodeURIComponent(sess.model)}`, {
        method: "POST",
        headers: { Authorization: `Bearer ${ephemeralKey}`, "Content-Type": "application/sdp" },
        body: pc.localDescription.sdp
    });
    if (!oaResp.ok) throw new Error(await oaResp.text());
    const answerSdp = await oaResp.text();
    await pc.setRemoteDescription({ type: "answer", sdp: answerSdp });

    status && (status.textContent = "Connected");
    } catch (err) {
    console.error("startVoice err:", err);
    $("status") && ($("status").textContent = "Error: " + (err?.message || err));
    toast("Error: " + (err?.message || "Unknown"));
    }}

/* -----------------------------
    Save conversation (simple)
------------------------------ */
async function saveConversationToServer(sessionId = null) {
    if (!conversationMessages.length) return null;
    try {
    const r = await fetch("/api/conversation/", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionId, messages: conversationMessages }) });
    if (!r.ok) { console.error("Save failed:", await r.text()); return null; }
    window._conversationSaved = true;
    toast("Conversation saved");
    return await r.json();
    } catch (err) { console.error("Save err:", err); toast("Save failed"); return null; }
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
    $("status") && ($("status").textContent = "Saving...");
    await saveConversationToServer(window.currentSessionId);          // wait until server responds
    await toast("Conversation saved", 1500);    // wait until toast finishes
    location.reload();                         // now safe to reload
});})();


/* -------------------------
Hook start button
------------------------- */
document.getElementById("start")?.addEventListener("click", startVoice);