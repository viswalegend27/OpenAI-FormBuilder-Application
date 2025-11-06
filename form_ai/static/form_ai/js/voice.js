// --- Main voice connection logic
async function startVoice() {
    const statusEl = document.getElementById("status");
    const remoteEl = document.getElementById("remote");

    try {
        // --- Request mic access
        statusEl.textContent = "Requesting microphone...";
        const mic = await navigator.mediaDevices.getUserMedia({
            audio: { echoCancellation: true, noiseSuppression: true }
        });

        // --- Create WebRTC peer connection
        const pc = new RTCPeerConnection({
            iceServers: [{ urls: "stun:stun.l.google.com:19302" }]
        });

        // --- Handle remote audio track
        pc.addEventListener("track", (ev) => {
            if (!remoteEl.srcObject) remoteEl.srcObject = ev.streams[0];
        });

        mic.getAudioTracks().forEach(t => pc.addTrack(t, mic));

        // --- Create and set local SDP offer
        statusEl.textContent = "Creating offer...";
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        await waitForIceGathering(pc);

        // --- Get ephemeral session from Django backend
        statusEl.textContent = "Getting session...";
        const sessResp = await fetch("/api/session");
        if (!sessResp.ok) throw new Error("Session fetch failed");
        const sess = await sessResp.json();

        const ephemeralKey = sess?.client_secret?.value;
        if (!ephemeralKey) throw new Error("Missing ephemeral key in session response");

        // --- Send SDP to OpenAI and set remote description
        statusEl.textContent = "Connecting...";
        const model = sess?.model || "gpt-4o-realtime-preview-2024-10-01";

        const oaResp = await fetch(`https://api.openai.com/v1/realtime?model=${encodeURIComponent(model)}`, {
            method: "POST",
            headers: {
                "Authorization": `Bearer ${ephemeralKey}`,
                "Content-Type": "application/sdp"
            },
            body: pc.localDescription.sdp
        });

        if (!oaResp.ok) throw new Error(`OpenAI SDP failed: ${oaResp.status}`);

        const answerSdp = await oaResp.text();
        await pc.setRemoteDescription({ type: "answer", sdp: answerSdp });

        // --- Connected successfully
        statusEl.textContent = "Connected! Speak now.";

    } catch (err) {
        console.error("💥 Error:", err);
        statusEl.textContent = "Error: " + err.message;
    }
}

// --- Bind UI button
document.getElementById("start")?.addEventListener("click", startVoice);