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
    });
}

async function startVoice() {
    const statusEl = document.getElementById("status");
    const remoteEl = document.getElementById("remote");
    
    try {
        statusEl.textContent = "Requesting microphone...";
        const mic = await navigator.mediaDevices.getUserMedia({
            audio: { echoCancellation: true, noiseSuppression: true }
        });

        const pc = new RTCPeerConnection({
            iceServers: [{ urls: "stun:stun.l.google.com:19302" }]
        });

        pc.addEventListener("track", (ev) => {
            console.log("🎵 Remote track received:", ev.track.kind);
            if (!remoteEl.srcObject) {
                remoteEl.srcObject = ev.streams[0];
            }
        });

        pc.addEventListener("iceconnectionstatechange", () => {
            console.log("🧊 ICE connection state:", pc.iceConnectionState);
        });

        pc.addEventListener("connectionstatechange", () => {
            console.log("🔌 Connection state:", pc.connectionState);
        });

        mic.getAudioTracks().forEach(t => pc.addTrack(t, mic));

        statusEl.textContent = "Creating offer...";
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        await waitForIceGathering(pc, 3000);
        
        console.log("📤 Local SDP offer length:", pc.localDescription.sdp.length);

        statusEl.textContent = "Getting session...";
        const sessResp = await fetch("/api/session");
        if (!sessResp.ok) {
            const errText = await sessResp.text();
            console.error("❌ Session fetch failed:", errText);
            throw new Error("Session failed: " + errText);
        }
        
        const sess = await sessResp.json();
        console.log("🔑 Session ID:", sess?.id);
        
        const ephemeralKey = sess?.client_secret?.value;
        if (!ephemeralKey) {
            console.error("❌ Session response:", sess);
            throw new Error("No ephemeral key in session response");
        }

        statusEl.textContent = "Exchanging SDP...";
        
        const model = sess?.model || "gpt-4o-realtime-preview-2024-10-01";
        console.log("📡 Using model:", model);
        
        const oaResp = await fetch(`https://api.openai.com/v1/realtime?model=${encodeURIComponent(model)}`, {
            method: "POST",
            headers: {
                "Authorization": `Bearer ${ephemeralKey}`,
                "Content-Type": "application/sdp"
            },
            body: pc.localDescription.sdp
        });

        if (!oaResp.ok) {
            const err = await oaResp.text();
            console.error("❌ OpenAI error:", oaResp.status, err);
            throw new Error(`OpenAI SDP failed: ${oaResp.status}`);
        }

        const answerSdp = await oaResp.text();
        console.log("📥 Answer SDP length:", answerSdp.length);
        
        // Use OpenAI's SDP directly without sanitization (like the working example)
        await pc.setRemoteDescription({ type: "answer", sdp: answerSdp });
        
        console.log("✅ Remote description set successfully");
        statusEl.textContent = "Connected! Speak now.";
        
    } catch (err) {
        console.error("💥 Error:", err);
        statusEl.textContent = "Error: " + err.message;
    }
}

document.getElementById("start")?.addEventListener("click", startVoice);