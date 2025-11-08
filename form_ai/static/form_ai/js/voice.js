function waitForIceGathering(pc, timeoutMs = 3000) {
    // ---- Creating promise to resolve ICE Gathering ----
    return new Promise((resolve) => {
    if (pc.iceGatheringState === "complete") {
    console.log("✅ ICE already complete");
    return resolve();
    }
    // --- Initiating an on-state Change ---
    const onStateChange = () => {
    if (pc.iceGatheringState === "complete") {
        pc.removeEventListener("icegatheringstatechange", onStateChange);
        clearTimeout(timer);
        resolve();
    }
    };

    const timer = setTimeout(() => {
    console.warn("⏱️ ICE gathering timeout");
    pc.removeEventListener("icegatheringstatechange", onStateChange);
    resolve();
    }, timeoutMs);

    pc.addEventListener("icegatheringstatechange", onStateChange);
});
}

async function startVoice() {
    const statusEl = document.getElementById("status");
    const remoteEl = document.getElementById("remote");
    const stopBtn = document.getElementById("stop");
    const convEl = document.getElementById("conversation");

// Helpers to show toast
    function toast(msg, ms = 3000) {
    const t = document.getElementById("toast-message");
    if (!t) return;
    t.textContent = msg;
    t.classList.add("show");
    setTimeout(() => t.classList.remove("show"), ms);
    }

// Create and append message element; returns the message element
    function appendMessage(role, text = "", opts = {}) {
    if (!convEl) return null;
    if (convEl.classList.contains("empty")) convEl.classList.remove("empty");

    const msg = document.createElement("div");
    msg.className = "message " + (role === "user" ? "user" : "assistant");
    if (opts.id) msg.dataset.msgId = opts.id;

    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = text || "";

    // small meta (role + optional time)
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = `${role === "user" ? "You" : "Assistant"}`;

    msg.appendChild(bubble);
    msg.appendChild(meta);

    convEl.appendChild(msg);
    convEl.scrollTop = convEl.scrollHeight;

    return { msgEl: msg, bubbleEl: bubble, metaEl: meta };
    }

// Utility to update last assistant message (for streaming)
    function updateStreamingAssistant(elObj, streamingText) {
    if (!elObj) return;
    elObj.bubbleEl.textContent = streamingText;
    if (!elObj.msgEl.classList.contains("streaming")) {
        elObj.msgEl.classList.add("streaming");
    }
    elObj.msgEl.scrollIntoView({ behavior: "smooth", block: "end" });
    }

// finalize message (remove streaming class)
    function finalizeMessage(elObj, finalText) {
    if (!elObj) return;
    elObj.bubbleEl.textContent = finalText;
    elObj.msgEl.classList.remove("streaming");
    elObj.msgEl.scrollIntoView({ behavior: "smooth", block: "end" });
    }

    let currentAssistant = null; // holds object returned by appendMessage for streaming assistant
    let aiStreaming = "";

try {
    statusEl.textContent = "Requesting microphone...";
    // --- Microphone access ---
    const mic = await navigator.mediaDevices.getUserMedia({audio: { echoCancellation: true, noiseSuppression:true },});
    
    // --- Setting up my WebRTC connection ---
    const pc = new RTCPeerConnection({iceServers: [{ urls: "stun:stun.l.google.com:19302" }],});

    // --- Data-channel connectivity ---
    const dc = pc.createDataChannel("oai-events");
    let sessionCreated = false;

    dc.addEventListener("open", () => {
    console.log("📨 Data channel opened");
    if (stopBtn) stopBtn.disabled = false;
    });
    
    dc.addEventListener("error", (e) => console.error("❌ Data channel error:", e));

    dc.addEventListener("message", (e) => {
    try {
        const msg = JSON.parse(e.data);
        if (msg?.type && !String(msg.type).includes("audio")) {
        console.log("📩 Event:", msg.type);
        }

        // session.created -> trigger assistant greeting
        if (msg.type === "session.created" && !sessionCreated) {
        sessionCreated = true;
        console.log("✅ Session created..");
        // trigger a response if desired (your original behavior)
        const responseCreate = { type: "response.create" };
        dc.send(JSON.stringify(responseCreate));
        console.log("📤 Sent response.create to trigger greeting");
        statusEl.textContent = "Connected";
        }

        // user final transcript.
        if (msg.type === "conversation.item.input_audio_transcription.completed") {
        const t = msg.transcript || "";
        if (t) {appendMessage("user", t);}
        }

        // assistant response start 
        if (msg.type === "response.created") {
        // initialize streaming assistant message
        aiStreaming = "";
        currentAssistant = appendMessage("assistant", ""); // Initial bubble
        return;
        }

        // assistant transcript deltas (stream) <-- My beta transcript.
    if (msg.type === "response.audio_transcript.delta") {
    aiStreaming += (msg.delta || "");
    if (!aiStreaming) return;
    updateStreamingAssistant(currentAssistant, aiStreaming);
    return;
    }

    // assistant transcript done (final)
    if (msg.type === "response.audio_transcript.done") {
    const finalText = (msg.transcript || aiStreaming || "").trim();
    if (finalText) {
        if (currentAssistant) {
        finalizeMessage(currentAssistant, finalText);
        } else {
        appendMessage("assistant", finalText);
        }
    }
    aiStreaming = "";
    currentAssistant = null;
    return;
    }
    } catch (err) {
        console.warn("Non-JSON message:", e.data);
    }
    });

    pc.addEventListener("track", (ev) => {
    console.log("🎵 Remote track received:", ev.track.kind);
    if (!remoteEl.srcObject) {
        remoteEl.srcObject = ev.streams[0];
        remoteEl.volume = 1.0;
        remoteEl.muted = false;
        remoteEl.play().catch((e) => {
        console.warn("⚠️ Autoplay blocked:", e);
        statusEl.textContent = "Connected! Click anywhere to hear audio.";
        document.addEventListener("click", () => remoteEl.play(), { once: true });
        });}
    });

    pc.addEventListener("iceconnectionstatechange", () => {
    console.log("🧊 ICE:", pc.iceConnectionState);
    });
    pc.addEventListener("connectionstatechange", () => {
    console.log("🔌 State:", pc.connectionState);
    });

    // add local mic tracks
    mic.getAudioTracks().forEach((t) => pc.addTrack(t, mic));

    statusEl.textContent = "Creating offer...";
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    await waitForIceGathering(pc, 3000);

    // fetch ephemeral session
    statusEl.textContent = "Getting session...";
    const sessResp = await fetch("/api/session");
    if (!sessResp.ok) {
    const errText = await sessResp.text();
    console.error("❌ Session fetch failed:", errText);
    throw new Error("Session failed: " + errText);
    }
    const sess = await sessResp.json();
    const ephemeralKey = sess?.client_secret?.value;
    if (!ephemeralKey) {
    console.error("❌ Session response:", sess);
    throw new Error("No ephemeral key in session response");
    }

    statusEl.textContent = "Exchanging SDP...";
    const model = sess?.model;
console.log("📡 Using model:", model);

    const oaResp = await fetch(
    `https://api.openai.com/v1/realtime?model=${encodeURIComponent(model)}`,
    {
        method: "POST",
        headers: {
        Authorization: `Bearer ${ephemeralKey}`,
        "Content-Type": "application/sdp",
        },
        body: pc.localDescription.sdp,
    }
    );

    if (!oaResp.ok) {
    const err = await oaResp.text();
    console.error("❌ OpenAI error:", oaResp.status, err);
    throw new Error(`OpenAI SDP failed: ${oaResp.status}`);
    }

    const answerSdp = await oaResp.text();
    console.log("📥 Answer SDP length:", answerSdp.length);
    await pc.setRemoteDescription({ type: "answer", sdp: answerSdp });

    console.log("✅ Remote description set successfully");
    statusEl.textContent = "Connected";
} catch (err) {
    console.error("💥 Error:", err);
    statusEl.textContent = "Error: " + (err?.message || err);
    toast("Error: " + (err?.message || "Unknown"));
}
}

document.getElementById("start")?.addEventListener("click", startVoice);

// stop button: reload (simple cleanup)
(() => {
    const stopBtn = document.getElementById("stop");
        if (!stopBtn) return;
        if (stopBtn._wired) return;
    stopBtn._wired = true;
    stopBtn.addEventListener("click", () => {try { window.location.reload(); } catch {}});
})();
