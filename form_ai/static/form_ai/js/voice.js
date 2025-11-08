// The ICE gathering is done so that offer SDP includes our best network
function waitForIceGathering(pc, timeoutMs = 3000) {
// An promise function declared
return new Promise((resolve) => {
    if (pc.iceGatheringState === "complete") {
    console.log("✅ ICE already complete");
    return resolve();
    }
    // Ice gathering process
    const onStateChange = () => {
    console.log("🧊 ICE gathering:", pc.iceGatheringState);
    if (pc.iceGatheringState === "complete") {
        pc.removeEventListener("icegatheringstatechange", onStateChange);
        clearTimeout(timer);
        resolve();
    }};

    const timer = setTimeout(() => {
    console.warn("⏱️ ICE gathering timeout");
    pc.removeEventListener("icegatheringstatechange", onStateChange);
    resolve();
    }, timeoutMs);

    pc.addEventListener("icegatheringstatechange", onStateChange);
    });
}

async function startVoice() {
    // Obtaining my frontend elements.
    const statusEl = document.getElementById("status");
    const remoteEl = document.getElementById("remote");
    const startBtn = document.getElementById("start");
    const stopBtn = document.getElementById("stop");
    const userTranscriptEl = document.getElementById("userTranscript");
    const aiTranscriptEl = document.getElementById("aiTranscript");

    // Helpers for appending transcript text
    const append = (el, text) => {
        if (!el) return;
        if (el.classList && el.classList.contains("empty")) el.classList.remove("empty");
        el.textContent += (el.textContent ? "\n" : "") + text;
        el.scrollTop = el.scrollHeight;
    };
    let aiStreaming = "";
    // Starting my voice assistant application.
    try {
    // Request microphone access
    statusEl.textContent = "Requesting microphone...";
    const mic = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
    });

    // Create RTCPeerConnection with STUN servers
    const pc = new RTCPeerConnection({
        iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
    });

    // Creating data channel BEFORE creating offer
    const dc = pc.createDataChannel("oai-events");
    let sessionCreated = false;

    // Set up data channel event handlers
    dc.addEventListener("open", () => {
        console.log("📨 Data channel opened");
        // Enable stop button when channel is ready
        if (stopBtn) stopBtn.disabled = false;
    });
    dc.addEventListener("error", (e) => {console.error("❌ Data channel error:", e);});

    dc.addEventListener("message", (e) => {
        try {
        const msg = JSON.parse(e.data);
        console.log("📩 Received event:", msg.type);

        // Wait for session.created event, THEN trigger response
        if (msg.type === "session.created" && !sessionCreated) {
        sessionCreated = true;
        console.log("✅ Session created..");

          // Now trigger the AI to speak first
        const responseCreate = {type: "response.create",};

        dc.send(JSON.stringify(responseCreate));
        console.log("📤 Sent response.create to trigger greeting");
        statusEl.textContent = "Connected";
        }

        // Append user transcript when OpenAI finalizes it
        if (msg.type === "conversation.item.input_audio_transcription.completed") {
            const t = msg.transcript || "";
            if (t) append(userTranscriptEl, `You: ${t}`);
        }

        // Stream assistant transcript deltas
        if (msg.type === "response.audio_transcript.delta") {
            aiStreaming += (msg.delta || "");
            if (aiStreaming) {
                const lines = (aiTranscriptEl?.textContent || "").split("\n").filter(Boolean);
                if (lines.length && lines[lines.length - 1].startsWith("Assistant: ")) {
                    lines[lines.length - 1] = "Assistant: " + aiStreaming;
                    aiTranscriptEl.textContent = lines.join("\n");
                    aiTranscriptEl.scrollTop = aiTranscriptEl.scrollHeight;
                } else {
                    append(aiTranscriptEl, "Assistant: " + aiStreaming);
                }
            }
        }

        // Finalize assistant transcript line
        if (msg.type === "response.audio_transcript.done") {
            const finalText = (msg.transcript || aiStreaming || "").trim();
            if (finalText) {
                const lines = (aiTranscriptEl?.textContent || "").split("\n").filter(Boolean);
                if (lines.length && lines[lines.length - 1].startsWith("Assistant: ")) {
                    lines[lines.length - 1] = "Assistant: " + finalText;
                    aiTranscriptEl.textContent = lines.join("\n");
                    aiTranscriptEl.scrollTop = aiTranscriptEl.scrollHeight;
                } else {
                    append(aiTranscriptEl, "Assistant: " + finalText);
                }
            }
            aiStreaming = "";
        }

        // Log other events for debugging (optional)
        if (msg.type && !msg.type.includes("audio")) {
        console.log("📋 Event details:", msg);
        }
    } catch (err) {
        console.warn("Non-JSON message:", e.data);
    }});

    // Attach remote audio when received
    // Playing my audio when track from ai is recieved successfully.
    pc.addEventListener("track", (ev) => {
    console.log("🎵 Remote track received:", ev.track.kind);
    if (!remoteEl.srcObject) {
        remoteEl.srcObject = ev.streams[0];

        // Ensure audio is ready to play
        remoteEl.volume = 1.0;
        remoteEl.muted = false;

        // Try to play (handle autoplay restrictions)
        remoteEl.play().catch((e) => {
        console.warn("⚠️ Autoplay blocked:", e);
        statusEl.textContent = "Connected! Click anywhere to hear Tyler.";

          // Handle autoplay blocking
        document.addEventListener(
            "click",
            () => {
            remoteEl.play();
            console.log("🔊 Audio playback started after user interaction");
            },
            { once: true },
        );
        });
    }});
    // # ----------- MY DATABASE PROCESS ----------- #
    // Log ICE/connection state changes
    pc.addEventListener("iceconnectionstatechange", () => {
    console.log("🧊 ICE connection state:", pc.iceConnectionState);
    });

    pc.addEventListener("connectionstatechange", () => {
    console.log("🔌 Connection state:", pc.connectionState);
    });

    // Add local microphone tracks to PeerConnection
    mic.getAudioTracks().forEach((t) => pc.addTrack(t, mic));

    // Create offer AFTER data channel is created
    statusEl.textContent = "Creating offer...";
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    await waitForIceGathering(pc, 3000);

    console.log("📤 Local SDP offer length:", pc.localDescription.sdp.length);

    // Fetch ephemeral session from your server
    statusEl.textContent = "Getting session...";
    // My session call
    const sessResp = await fetch("/api/session");
    if (!sessResp.ok) {
    const errText = await sessResp.text();
    console.error("❌ Session fetch failed:", errText);
    throw new Error("Session failed: " + errText);
    }

    const sess = await sessResp.json();

    // Extract ephemeral key
    const ephemeralKey = sess?.client_secret?.value;
    if (!ephemeralKey) {
    console.error("❌ Session response:", sess);
    throw new Error("No ephemeral key in session response");
    }

    // Send local SDP to OpenAI realtime endpoint
    statusEl.textContent = "Exchanging SDP...";
    const model = sess?.model;
    console.log("📡 Using model:", model)

    const oaResp = await fetch(
        `https://api.openai.com/v1/realtime?model=${encodeURIComponent(model)}`,
    {
        method: "POST",
        headers: {
        Authorization: `Bearer ${ephemeralKey}`,
        "Content-Type": "application/sdp",
        },
        body: pc.localDescription.sdp,
    },
    );

    if (!oaResp.ok) {
    const err = await oaResp.text();
    console.error("❌ OpenAI error:", oaResp.status, err);
    throw new Error(`OpenAI SDP failed: ${oaResp.status}`);
    }

    // Apply answer SDP
    const answerSdp = await oaResp.text();
    console.log("📥 Answer SDP length:", answerSdp.length);
    await pc.setRemoteDescription({ type: "answer", sdp: answerSdp });

    console.log("✅ Remote description set successfully");
    statusEl.textContent = "Connected";
    } catch (err) {
    console.error("💥 Error:", err);
    statusEl.textContent = "Error: " + err.message;
    }
}

document.getElementById("start")?.addEventListener("click", startVoice);

// Optional: stop/cleanup handler
(() => {
    const stopBtn = document.getElementById("stop");
    if (!stopBtn) return;
    if (stopBtn._wired) return;
    stopBtn._wired = true;
    stopBtn.addEventListener("click", () => {
        // Rely on page reload or future stateful cleanup as needed
        try { window.location.reload(); } catch {}
    });
})();
