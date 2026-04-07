document.addEventListener('DOMContentLoaded', () => {
    // UI Elements
    const pttBtn = document.getElementById('ptt-btn');
    const indicators = {
        mic: document.getElementById('indicator-mic'),
        brain: document.getElementById('indicator-brain'),
        mouth: document.getElementById('indicator-mouth')
    };
    const dot = document.getElementById('system-dot');
    const statusText = document.getElementById('system-status');
    const transcriptBox = document.getElementById('transcript-box');
    const placeholder = document.getElementById('placeholder-text');
    const sttStatus = document.getElementById('stt-status');
    
    // Telemetry Elements
    const hudPhase = document.getElementById('hud-phase');
    const hudAlt = document.getElementById('hud-alt');
    const hudHdg = document.getElementById('hud-hdg');
    const hudRunway = document.getElementById('hud-runway');
    const hudSquawk = document.getElementById('hud-squawk');

    // Setup WebSockets
    const loc = window.location;
    const wsUri = (loc.protocol === "https:" ? "wss:" : "ws:") + "//" + loc.host + "/ws";
    
    let ws;
    function connect() {
        ws = new WebSocket(wsUri);
        
        ws.onopen = function() {
            dot.classList.add('connected');
            statusText.textContent = "Connected";
        };
        
        ws.onclose = function() {
            dot.classList.remove('connected');
            statusText.textContent = "Disconnected";
            setTimeout(connect, 2000);
        };
        
        ws.onmessage = function(e) {
            const data = JSON.parse(e.data);
            
            if (data.type === "state_update") {
                hudPhase.textContent = data.phase || "UNKNOWN";
                hudAlt.textContent = data.altitude || "0";
                
                // Format heading
                let hdg = data.heading || 0;
                hudHdg.textContent = hdg.toString().padStart(3, '0');
                
                hudRunway.textContent = data.runway || "---";
                hudSquawk.textContent = data.squawk || "1200";
            }
            
            else if (data.type === "stt_status") {
                sttStatus.textContent = data.status.toUpperCase();
            }
            
            else if (data.type === "voice_status") {
                updateVoiceIndicator(data.component, data.status);
            }
            
            else if (data.type === "transcript") {
                if (placeholder) placeholder.style.display = "none";
                appendMessage(data.speaker, data.text, data.time);
            }
        };
    }
    
    connect();

    // Latest instruction tracking
    let latestBlock = null;

    function appendMessage(speaker, text, timestamp) {
        if (!timestamp) {
            const now = new Date();
            timestamp = now.getHours().toString().padStart(2, '0') + ":" + 
                        now.getMinutes().toString().padStart(2, '0') + ":" + 
                        now.getSeconds().toString().padStart(2, '0');
        }

        const block = document.createElement("div");
        block.className = `msg-block ${speaker.toLowerCase()}`;
        
        block.innerHTML = `
            <div class="msg-header">
                <span class="msg-speaker">${speaker}</span>
                <span class="msg-time">${timestamp}</span>
            </div>
            <div class="msg-content">${text}</div>
        `;
        
        // Remove 'latest' from previous block
        if (latestBlock) {
            latestBlock.classList.remove('latest');
        }
        
        block.classList.add('latest');
        latestBlock = block;
        
        transcriptBox.appendChild(block);
        
        // Auto scroll to bottom
        transcriptBox.scrollTop = transcriptBox.scrollHeight;
    }

    function updateVoiceIndicator(component, status) {
        const el = indicators[component];
        if (!el) return;

        if (status !== 'idle') {
            el.classList.add('active');
        } else {
            el.classList.remove('active');
        }
    }


    // PTT Input Handling (Mouse/Touch)
    let isRecording = false;

    function startPTT() {
        if (isRecording) return;
        isRecording = true;
        
        pttBtn.classList.add("active");
        pttBtn.textContent = "🔴 RECORDING...";
        
        if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ action: "start_ptt" }));
        }
    }

    function stopPTT() {
        if (!isRecording) return;
        isRecording = false;
        
        pttBtn.classList.remove("active");
        pttBtn.textContent = "🎙️ PUSH TO TALK";
        
        if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ action: "stop_ptt" }));
        }
    }

    // Bind PTT events
    pttBtn.addEventListener("mousedown", startPTT);
    pttBtn.addEventListener("mouseup", stopPTT);
    pttBtn.addEventListener("mouseleave", stopPTT);
    
    pttBtn.addEventListener("touchstart", (e) => { e.preventDefault(); startPTT(); });
    pttBtn.addEventListener("touchend", (e) => { e.preventDefault(); stopPTT(); });
    pttBtn.addEventListener("touchcancel", (e) => { e.preventDefault(); stopPTT(); });

    // Global Spacebar PTT fallback
    document.addEventListener("keydown", (e) => {
        if (e.code === "Space" && e.target.tagName !== "INPUT") {
            e.preventDefault();
            startPTT();
        }
    });
    
    document.addEventListener("keyup", (e) => {
        if (e.code === "Space" && e.target.tagName !== "INPUT") {
            e.preventDefault();
            stopPTT();
        }
    });

});
