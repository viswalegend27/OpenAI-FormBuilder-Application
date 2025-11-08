// The ICE gathering is done so that offer SDP includes our best network
function waitForIceGathering(pc, timeoutMs = 3000) {
return new Promise((resolve) => {
    if (pc.iceGatheringState === "complete") {
    console.log("✅ ICE already complete");
    return resolve();
    }

    const onStateChange = () => {
    console.log("🧊 ICE gathering:", pc.iceGatheringState);
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
    }
    );
}

async function startVoice() {
    const statusEl = document.getElementById("status");
    const remoteEl = document.getElementById("remote");

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

    // ⚡ CRITICAL: Create data channel BEFORE creating offer
    const dc = pc.createDataChannel("oai-events");
    let sessionCreated = false;

    // Set up data channel event handlers
    dc.addEventListener("open", () => {
        console.log("📨 Data channel opened");
    });

    dc.addEventListener("error", (e) => {
        console.error("❌ Data channel error:", e);
    });

    dc.addEventListener("message", (e) => {
        try {
        const msg = JSON.parse(e.data);
        console.log("📩 Received event:", msg.type);

        // ⚡ CRITICAL: Wait for session.created event, THEN trigger response
        if (msg.type === "session.created" && !sessionCreated) {
        sessionCreated = true;
        console.log("✅ Session created, triggering initial response...");

          // Now trigger the AI to speak first
        const responseCreate = {
            type: "response.create",
        };

        dc.send(JSON.stringify(responseCreate));
        console.log("📤 Sent response.create to trigger greeting");
        statusEl.textContent = "Connected! Tyler should greet you now...";
        }

        // Log other events for debugging (optional)
        if (msg.type && !msg.type.includes("audio")) {
        console.log("📋 Event details:", msg);
        }
    } catch (err) {
        console.warn("Non-JSON message:", e.data);
    }
    });

    // Attach remote audio when received
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
    }
    });

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
    statusEl.textContent = "Connecting...";
    } catch (err) {
    console.error("💥 Error:", err);
    statusEl.textContent = "Error: " + err.message;
    }
}

document.getElementById("start")?.addEventListener("click", startVoice);
