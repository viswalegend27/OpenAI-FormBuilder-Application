// The ICE gathering is done so that offer SDP includes our best network
function waitForIceGathering(pc, timeoutMs = 3000) {
    // Resolve when ICE gathering completes or times out
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

        // Timeout fallback to avoid waiting forever
        const timer = setTimeout(() => {
            console.warn("⏱️ ICE gathering timeout");
            pc.removeEventListener("icegatheringstatechange", onStateChange);
            resolve();
        }, timeoutMs);

        // Listen for ICE gathering state changes
        pc.addEventListener("icegatheringstatechange", onStateChange);
    });
}

async function startVoice() {
    const statusEl = document.getElementById("status");
    const remoteEl = document.getElementById("remote");

    try {
        // Request microphone access
        statusEl.textContent = "Requesting microphone...";
        const mic = await navigator.mediaDevices.getUserMedia({
            audio: { echoCancellation: true, noiseSuppression: true }
        });

        // Create RTCPeerConnection with STUN servers
        const pc = new RTCPeerConnection({
            iceServers: [{ urls: "stun:stun.l.google.com:19302" }]
        });

        // Attach remote audio when received
        pc.addEventListener("track", (ev) => {
            console.log("🎵 Remote track received:", ev.track.kind);
            if (!remoteEl.srcObject) {
                remoteEl.srcObject = ev.streams[0];
            }
        });

        // Log ICE/connection state changes (diagnostics)
        pc.addEventListener("iceconnectionstatechange", () => {
            console.log("🧊 ICE connection state:", pc.iceConnectionState);
        });
        pc.addEventListener("connectionstatechange", () => {
            console.log("🔌 Connection state:", pc.connectionState);
        });

        // Add local microphone tracks to PeerConnection
        mic.getAudioTracks().forEach(t => pc.addTrack(t, mic));

        // Create offer and wait for local ICE gathering
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

        // Extract ephemeral key, fail if missing
        const ephemeralKey = sess?.client_secret?.value;
        if (!ephemeralKey) {
            console.error("❌ Session response:", sess);
            throw new Error("No ephemeral key in session response");
        }

        // Send local SDP to OpenAI realtime endpoint using ephemeral key
        statusEl.textContent = "Exchanging SDP...";
        const model = sess?.model;
        console.log("📡 Using model:", model);

        const oaResp = await fetch(`https://api.openai.com/v1/realtime?model=${encodeURIComponent(model)}`, {
            method: "POST",
            headers: {
                "Authorization": `Bearer ${ephemeralKey}`,
                "Content-Type": "application/sdp"
            },
            body: pc.localDescription.sdp
        });

        // Handle OpenAI SDP exchange failure
        if (!oaResp.ok) {
            const err = await oaResp.text();
            console.error("❌ OpenAI error:", oaResp.status, err);
            throw new Error(`OpenAI SDP failed: ${oaResp.status}`);
        }

        // Apply answer SDP from OpenAI to establish media path
        const answerSdp = await oaResp.text();
        console.log("📥 Answer SDP length:", answerSdp.length);
        await pc.setRemoteDescription({ type: "answer", sdp: answerSdp });

        // Connection established — update UI
        console.log("✅ Remote description set successfully");
        statusEl.textContent = "Connected! Speak now.";

    } catch (err) {
        // Show error and log
        console.error("💥 Error:", err);
        statusEl.textContent = "Error: " + err.message;
    }
}

// Wire UI start button to startVoice
document.getElementById("start")?.addEventListener("click", startVoice);
