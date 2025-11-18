window.addEventListener("load", () => {
  new VoiceAgent();
});

class VoiceAgent {
  constructor() {
    const url = new URL(window.location.href);
    this.sessionId = url.searchParams.get("sessionId");
    this.startBtn = document.getElementById("startButton");
    this.stopBtn = document.getElementById("stopButton");
    this.audioPlayback = document.getElementById("recorder-audio-playback");
    this.status = document.getElementById("request-status");

    this.websocket = null;
    this.mediaRecorder = null;
    this.isRecording = false;
    this.audioChunks = [];

    // Track transcription state for turn detection
    this.currentPartialTranscript = "";
    this.transcriptionHistory = [];

    // Audio playback setup
    this.playbackAudioContext = null;
    this.playbackChunks = [];
    this.playheadTime = 0;
    this.isPlayingAudio = false;
    this.wavHeaderSet = true;
    this.SAMPLE_RATE = 24000;

    if (!this.sessionId) {
      this.sessionId = crypto.randomUUID();
      url.searchParams.set("sessionId", this.sessionId);
      window.history.replaceState({}, "", url.toString());
    }

    this.startBtn.addEventListener("click", () => {
      this.startListening();
    });
    this.stopBtn.addEventListener("click", () => this.stopRecording());

    // Create transcript display area
    this.createTranscriptDisplay();
  }

  async startListening() {
    try {
      // Connect WebSocket
      await this.connectWebSocket();

      // Start audio recording
      await this.startRecording();

      this.updateStatus("🎤 Ready to listen - start speaking!", "recording");
      this.startBtn.disabled = true;
      this.stopBtn.disabled = false;
      this.isRecording = true;

      // Initialize transcript display
      this.updateTranscriptDisplay("Listening...", false);
    } catch (error) {
      console.error("Error starting:", error);
      this.showError("Failed to start listening: " + error.message);
    }
  }

  async connectWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    this.websocket = new WebSocket(wsUrl);

    this.websocket.onopen = () => {
      console.log("WebSocket connected");
    };

    this.websocket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        this.handleWebSocketMessage(data);
      } catch (error) {
        console.error("Error parsing WebSocket message:", error);
      }
    };

    this.websocket.onerror = (error) => {
      console.error("WebSocket error:", error);
      this.showError("Connection error");
    };

    this.websocket.onclose = () => {
      console.log("WebSocket closed");
    };

    // Wait for connection
    await new Promise((resolve, reject) => {
      this.websocket.onopen = resolve;
      this.websocket.onerror = reject;
      setTimeout(reject, 5000); // 5 second timeout
    });
  }

  async startRecording() {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

    // Create AudioContext for raw PCM audio processing
    this.audioContext = new AudioContext({ sampleRate: 16000 });
    const source = this.audioContext.createMediaStreamSource(stream);

    // Create AudioWorkletProcessor for PCM audio capture
    await this.audioContext.audioWorklet.addModule("/assets/pcm-processor.js");
    this.pcmProcessor = new AudioWorkletNode(
      this.audioContext,
      "pcm-processor"
    );

    // Handle PCM audio data from the processor
    this.pcmProcessor.port.onmessage = (event) => {
      if (this.websocket?.readyState === WebSocket.OPEN) {
        const pcmData = event.data;
        this.websocket.send(pcmData.buffer);
        console.log("Sent PCM audio chunk:", pcmData.byteLength);
      }
    };

    // Connect the audio graph (no output to speakers for silent processing)
    source.connect(this.pcmProcessor);

    console.log("Recording started with PCM audio");
    this.isRecording = true;
    this.stream = stream;
  }

  stopRecording() {
    // Clean up audio resources
    if (this.pcmProcessor) {
      this.pcmProcessor.disconnect();
      this.pcmProcessor = null;
    }
    if (this.audioContext) {
      this.audioContext.close();
      this.audioContext = null;
    }
    if (this.stream) {
      this.stream.getTracks().forEach((track) => track.stop());
      this.stream = null;
    }
    if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
      this.websocket.close();
    }

    // Clean up playback audio resources
    if (
      this.playbackAudioContext &&
      this.playbackAudioContext.state !== "closed"
    ) {
      this.playbackAudioContext.close();
      this.playbackAudioContext = null;
    }
    this.playbackChunks = [];
    this.isPlayingAudio = false;

    this.updateStatus("⏹️ Recording stopped", "");
    this.startBtn.disabled = false;
    this.stopBtn.disabled = true;
    this.isRecording = false;

    // Clear partial transcript on stop
    const partialElement = document.getElementById("partial-text");
    if (partialElement) {
      partialElement.textContent = "";
    }
  }

  handleWebSocketMessage(data) {
    switch (data.type) {
      case "partial_transcript":
        this.currentPartialTranscript = data.text;
        this.updateStatus(`🎤 Listening: ${data.text}`, "transcribing");
        this.updateTranscriptDisplay(data.text, false);
        break;
      case "final_transcript":
        // Add the final transcript to history and clear partial
        this.transcriptionHistory.push({
          text: data.text,
          timestamp: new Date().toLocaleTimeString(),
          type: "final",
        });
        this.currentPartialTranscript = "";
        this.updateStatus(`✅ Turn completed: ${data.text}`, "completed");
        this.updateTranscriptDisplay(data.text, true);

        // Reset audio playback for new LLM response
        this.resetAudioPlayback();
        this.updateStatus(`🎵 Generating response...`, "generating");

        // Brief visual indication of turn completion
        setTimeout(() => {
          if (this.isRecording) {
            this.updateStatus("🎤 Listening for next turn...", "recording");
          }
        }, 2000);
        break;
      case "audio_chunk":
        console.log("Received audio chunk, playing...");
        this.updateStatus(`🎵 Playing response...`, "playing");
        this.playAudioChunk(data.audio_data);
        break;
      case "speech_complete":
        console.log("Speech complete");
        this.updateStatus(`✅ Response complete`, "completed");
        // Brief pause before indicating ready for next turn
        setTimeout(() => {
          if (this.isRecording) {
            this.updateStatus("🎤 Ready for next turn...", "recording");
          }
        }, 1000);
        break;
      case "error":
        this.showError(data.message);
        break;
      default:
        console.log("Unknown message type:", data.type);
    }
  }

  updateStatus(message, className) {
    this.status.textContent = message;
    this.status.className = `status ${className}`;
  }

  showError(message) {
    console.error("Transcription error:", message);
    this.updateStatus(`Error: ${message}`, "error");
  }

  createTranscriptDisplay() {
    // Create transcript display container if it doesn't exist
    let transcriptContainer = document.getElementById("transcript-container");
    if (!transcriptContainer) {
      transcriptContainer = document.createElement("div");
      transcriptContainer.id = "transcript-container";
      transcriptContainer.innerHTML = `
        <h3>Live Transcription</h3>
        <div id="current-transcript" style="border: 1px solid #ccc; padding: 10px; min-height: 60px; margin: 10px 0; background: #f9f9f9; border-radius: 5px;">
          <div id="partial-text" style="color: #666; font-style: italic;"></div>
        </div>
        <div id="transcript-history" style="max-height: 300px; overflow-y: auto; border: 1px solid #ddd; padding: 10px; background: white; border-radius: 5px;">
          <div style="color: #888; text-align: center;">Previous turns will appear here...</div>
        </div>
      `;

      // Insert after the status element
      this.status.parentNode.insertBefore(
        transcriptContainer,
        this.status.nextSibling
      );
    }
  }

  updateTranscriptDisplay(text, isFinal) {
    const partialElement = document.getElementById("partial-text");
    const historyElement = document.getElementById("transcript-history");

    if (!partialElement || !historyElement) return;

    if (isFinal) {
      // Add to history and clear partial
      if (text.trim()) {
        const turnElement = document.createElement("div");
        turnElement.style.cssText =
          "margin: 5px 0; padding: 8px; background: #e8f5e8; border-left: 3px solid #4caf50; border-radius: 3px;";
        turnElement.innerHTML = `
          <div style="font-size: 0.8em; color: #666; margin-bottom: 3px;">
            Turn completed at ${new Date().toLocaleTimeString()}
          </div>
          <div style="font-weight: 500;">${text}</div>
        `;

        // Remove placeholder text if present
        if (
          historyElement.children.length === 1 &&
          historyElement.textContent.includes("Previous turns")
        ) {
          historyElement.innerHTML = "";
        }

        historyElement.appendChild(turnElement);
        historyElement.scrollTop = historyElement.scrollHeight;
      }

      // Clear partial text
      partialElement.textContent = "";
    } else {
      // Update partial text
      partialElement.textContent = text || "Listening...";
    }
  }

  // Audio playback functions adapted from sample.js
  initializePlaybackAudioContext() {
    if (!this.playbackAudioContext) {
      this.playbackAudioContext = new (window.AudioContext ||
        window.webkitAudioContext)();
      this.playheadTime = this.playbackAudioContext.currentTime;
    }
  }

  base64ToPCMFloat32(base64) {
    let binary = atob(base64);
    const offset = this.wavHeaderSet ? 44 : 0; // Skip WAV header if present
    if (this.wavHeaderSet) {
      console.log("WAV Header detected, skipping first 44 bytes");
    }
    this.wavHeaderSet = false;
    const length = binary.length - offset;

    const buffer = new ArrayBuffer(length);
    const byteArray = new Uint8Array(buffer);
    for (let i = 0; i < byteArray.length; i++) {
      byteArray[i] = binary.charCodeAt(i + offset);
    }

    const view = new DataView(byteArray.buffer);
    const sampleCount = byteArray.length / 2;
    const float32Array = new Float32Array(sampleCount);

    for (let i = 0; i < sampleCount; i++) {
      const int16 = view.getInt16(i * 2, true);
      float32Array[i] = int16 / 32768;
    }

    return float32Array;
  }

  chunkPlay() {
    if (this.playbackChunks.length > 0) {
      const chunk = this.playbackChunks.shift();
      console.log(
        `Playing chunk of ${chunk.length} samples, ${this.playbackChunks.length} chunks remaining`
      );

      if (this.playbackAudioContext.state === "suspended") {
        console.log("Resuming suspended audio context");
        this.playbackAudioContext.resume();
      }

      const buffer = this.playbackAudioContext.createBuffer(
        1,
        chunk.length,
        this.SAMPLE_RATE
      );
      buffer.copyToChannel(chunk, 0);
      const source = this.playbackAudioContext.createBufferSource();
      source.buffer = buffer;
      source.connect(this.playbackAudioContext.destination);
      const now = this.playbackAudioContext.currentTime;
      if (this.playheadTime < now) {
        this.playheadTime = now + 0.05; // Add a small delay
      }
      console.log(
        `Scheduling audio at ${this.playheadTime}, duration: ${buffer.duration}s`
      );
      source.start(this.playheadTime);
      this.playheadTime += buffer.duration;

      if (this.playbackChunks.length > 0) {
        this.chunkPlay();
      } else {
        console.log("All audio chunks played");
        this.isPlayingAudio = false;
      }
    }
  }

  playAudioChunk(base64Audio) {
    try {
      console.log(
        "playAudioChunk called with audio data length:",
        base64Audio?.length
      );
      this.initializePlaybackAudioContext();

      const float32Array = this.base64ToPCMFloat32(base64Audio);
      if (!float32Array) {
        console.error("Failed to convert audio data to PCM");
        return;
      }

      this.playbackChunks.push(float32Array);
      console.log(
        `Queued audio chunk: ${float32Array.length} samples, total chunks: ${this.playbackChunks.length}`
      );

      // Start playback immediately if not already playing
      if (!this.isPlayingAudio && this.playbackChunks.length > 0) {
        console.log("Starting audio playback");
        this.isPlayingAudio = true;
        this.playbackAudioContext.resume(); // Resume audio context if suspended
        this.chunkPlay();
      } else {
        console.log(
          `Already playing (${this.isPlayingAudio}) or no chunks (${this.playbackChunks.length})`
        );
      }
    } catch (error) {
      console.error("Error playing audio chunk:", error, error.stack);
    }
  }

  resetAudioPlayback() {
    // Reset playback state for new audio stream
    this.playheadTime = this.playbackAudioContext
      ? this.playbackAudioContext.currentTime
      : 0;
    this.playbackChunks = [];
    this.isPlayingAudio = false;
    this.wavHeaderSet = true;
    console.log("Audio playback reset for new stream");
  }
}
