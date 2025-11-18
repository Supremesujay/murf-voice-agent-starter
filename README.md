# Murf Voice Agent Starter

Build a **streaming, low‑latency voice agent** powered by:

- **Murf** – real‑time streaming text‑to‑speech (TTS)
- **AssemblyAI** – real‑time speech‑to‑text (STT) with turn detection
- **Gemini (Google genai)** – LLM for generating responses
- **FastAPI + WebSockets** – backend and bi‑directional streaming
- **Browser Audio APIs** – microphone capture and seamless playback

This repo is a **starter project** for developers who want to build conversational voice agents using the **Murf streaming TTS API**.

---

## Project Overview

One conversation turn works like this:

1. You click **Start Recording** in the browser.
2. The browser captures microphone audio, converts it to 16‑bit PCM, and streams it to the backend over a WebSocket (`/ws`).
3. The FastAPI backend forwards the audio stream to **AssemblyAI**, which returns partial and final transcripts and detects when you stop speaking.
4. When a final transcript is received, the backend:
   - Sends the transcript back to the browser for display.
   - Sends the transcript to **Gemini**, streaming back text chunks.
   - Streams those text chunks to **Murf** over a WebSocket.
5. Murf generates audio **as text arrives**, sending back audio chunks.
6. The backend forwards audio chunks to the browser, which plays them in real time.

Everything is **streaming end‑to‑end**, so you see partial transcripts and hear audio responses with minimal latency.

---

## Architecture

- **FastAPI app (`app/main.py`)**

  - Loads environment variables via `dotenv`.
  - Creates the FastAPI application.
  - Serves static assets from `/assets`.
  - Includes:
    - `ui` router → serves the simple HTML UI.
    - `ws_chat` router → provides the main `/ws` WebSocket.

- **Frontend (browser)**

  - HTML is served from the `ui` router.
  - JavaScript:
    - `recorder.js`: client logic for recording, WebSocket connection, transcript display, and audio playback.
    - `pcm-processor.js`: an `AudioWorklet` that converts microphone audio into 16‑bit PCM chunks.

- **Backend services**

  - `AssemblyClient` (`assembly_transcribe.py`): streams raw audio to AssemblyAI and handles transcription events (partial + final).
  - `GeminiLLM` (`gemini_llm.py`): integrates with Gemini via `google-genai` and supports streaming text responses.
  - WebSocket orchestrator (`ws_chat.py`): accepts the browser WebSocket, connects to Murf via WebSocket, and orchestrates the full flow.

- **External APIs**
  - **AssemblyAI** – real‑time streaming STT with built‑in turn detection.
  - **Gemini** – LLM used to generate responses from user transcripts.
  - **Murf** – streaming TTS that accepts text chunks and returns audio chunks.

---

## Key Features

- **End‑to‑end streaming**

  - Browser → backend: 16‑bit PCM audio over WebSocket.
  - Backend → AssemblyAI: streaming audio via Assembly’s client.
  - Backend → Murf: streaming text via WebSocket.
  - Murf → backend → browser: streaming audio chunks for playback.

- **Low latency**

  - Partial transcripts appear as the user speaks.
  - Turn detection (via AssemblyAI) avoids manual silence timers.
  - Gemini streams text chunks instead of a single large response.
  - Murf starts generating audio as soon as it sees text.
  - Browser plays audio chunks as they arrive, not after the full response.

- **Full‑duplex behavior**
  - The backend can simultaneously:
    - Receive audio from the browser.
    - Stream it to AssemblyAI.
    - Process transcripts and stream text to Murf.
    - Stream Murf audio back to the browser.

---

## Requirements

- **Python**: 3.11+
- **Browser**: modern browser with:
  - `AudioContext`
  - `AudioWorklet`
  - `WebSocket`

You’ll also need valid API keys for:

- `ASSEMBLYAI_API_KEY`
- `GEMINI_API_KEY`
- `MURF_API_KEY`

---

## Getting Started

### 1. Clone the repository

```bash
git clone <this-repo-url>
cd murf-voice-agent-starter
```

### 2. Configure environment variables

Create a `.env` file in the project root (you can copy from `.env.example` if present) and set:

```bash
ASSEMBLYAI_API_KEY=your_assemblyai_api_key
GEMINI_API_KEY=your_gemini_api_key
MURF_API_KEY=your_murf_api_key
```

These are used by `AssemblyClient`, `GeminiLLM`, and the Murf WebSocket connection in `ws_chat.py`.

### 3. Install dependencies (with `uv`)

This project uses `pyproject.toml` and `uv.lock`:

```bash
uv sync
```

This will create a virtual environment and install:

- `fastapi[standard]`
- `assemblyai`
- `google-genai`
- `murf`
- `websockets`

(If you prefer `pip`, you can create a venv and install equivalent dependencies manually.)

### 4. Run the FastAPI app

Using `uv`:

```bash
uv run fastapi dev app/main.py
```

Or with `uvicorn` (if installed):

```bash
uv run uvicorn app.main:app --reload
```

The app exposes:

- `GET /ui/` – minimal HTML UI with Start/Stop buttons.
- `GET /assets/recorder.js` – JS client for recording and playback.
- `WebSocket /ws` – main streaming audio/text endpoint.

### 5. Open the UI

In your browser, navigate to:

```text
http://localhost:8000/ui/
```

Then:

1. Click **Start Recording**.
2. Grant microphone permissions.
3. Speak and watch the live transcript appear.
4. After you stop speaking, hear a Murf‑generated response based on Gemini’s output.

---

## How the Voice Pipeline Works

### 1. Browser: capture and stream audio

In `recorder.js`:

- Requests microphone access using `navigator.mediaDevices.getUserMedia({ audio: true })`.
- Creates an `AudioContext` at 16 kHz (matching AssemblyAI).
- Loads `pcm-processor.js` as an `AudioWorklet` and connects it to the microphone stream.
- `pcm-processor.js`:
  - Receives float samples.
  - Buffers and converts them to 16‑bit PCM (`Int16Array`).
  - Posts chunks back to the main thread.
- For each PCM chunk, if the WebSocket is open, it sends `pcmData.buffer` directly to `/ws` as binary data.

### 2. Backend: forward audio to AssemblyAI

In `websocket_endpoint` (`ws_chat.py`):

- Accepts the WebSocket from the browser.
- Creates `AssemblyClient()` and `GeminiLLM()`.
- Reads `MURF_API_KEY` and opens a WebSocket to Murf:
  - `wss://global.api.murf.ai/v1/speech/stream-input?...`
- Calls:

```python
await assembly_client.start(
    websocket,
    send_to_client=send_to_client,
    on_final_transcript=on_final_transcript,
)
```

- Enters a loop:

```python
while True:
    data = await websocket.receive_bytes()
    if data:
        await assembly_client.process_audio(data)
```

In `AssemblyClient`:

- Uses `StreamingClient` from `assemblyai`.
- Registers event callbacks for `Begin`, `Turn`, `Error`, and `Termination`.
- Streams bytes to AssemblyAI with `self._streaming_client.stream(audio_data)` for real‑time transcription and turn detection.

### 3. Transcription: partial and final text

When AssemblyAI emits a `TurnEvent`:

- If `event.transcript` is empty → ignored.
- If `event.end_of_turn` is **false**:
  - Treat as partial transcript.
  - Sends to browser via `send_to_client({"type": "partial_transcript", "text": event.transcript})`.
- If `event.end_of_turn` is **true**:
  - Treat as final transcript for the user turn.
  - Schedules `on_final_transcript(event.transcript)` on the FastAPI event loop.

This provides:

- Live partial text while the user speaks.
- A final, stable transcript when the user’s turn ends.

### 4. LLM + Murf: from transcript to audio

Inside `on_final_transcript` in `ws_chat.py`:

1. Sends the final transcript to the browser:

```python
await send_to_client({"type": "final_transcript", "text": transcript})
```

2. Logs that it’s generating an LLM response.
3. Sends a Murf voice configuration message once per turn:

```python
voice_config_msg = {
    "voice_config": {
        "voiceId": "en-US-amara",
    },
    "context_id": MURF_CONTEXT_ID,
}
await murf_ws.send(json.dumps(voice_config_msg))
```

4. Streams LLM text chunks from `GeminiLLM.generate_streaming_response(transcript)`:
   - For each chunk:

```python
text_message = {"text": chunk, "end": False, "context_id": MURF_CONTEXT_ID}
await murf_ws.send(json.dumps(text_message))
```

5. After all chunks:
   - If the response is very short, waits briefly so Murf has time to start TTS.
   - Sends a final message to signal the end of the text stream:

```python
final_message = {"text": "", "end": True, "context_id": MURF_CONTEXT_ID}
await murf_ws.send(json.dumps(final_message))
```

Murf now has everything it needs to synthesize the response.

### 5. Murf audio back to the browser

In `handle_murf_audio_stream` (background task in `ws_chat.py`):

- Waits on `murf_ws.recv()` in a loop.
- For each message:
  - Parses JSON.
  - If `"audio"` is present:
    - Increments a chunk counter.
    - Sends:

```python
await send_to_client({"type": "audio_chunk", "audio_data": data["audio"]})
```

- If `data.get("final")` is true:
  - Sends `{"clear": True, "context_id": MURF_CONTEXT_ID}` to Murf to clear context.
  - Sends `{"type": "speech_complete"}` to the browser.

In the browser (`recorder.js`):

- On `"audio_chunk"`:

  - Decodes base64 WAV audio.
  - Skips the 44‑byte WAV header on the first chunk.
  - Converts 16‑bit PCM into float samples.
  - Enqueues buffers into an `AudioContext` and schedules them back‑to‑back using a `playheadTime` so they play seamlessly.

- On `"speech_complete"`:
  - Updates the UI to show the response is done.
  - Returns to a “ready for next turn” state.

---

## Customizing the Starter

- **Change the Murf voice**

  - In `ws_chat.py`, update the `"voiceId"` field in `voice_config_msg` to any Murf voice ID available to your account.

- **Adjust LLM behavior**

  - In `gemini_llm.py`, modify:
    - The `model` name (e.g., use a different Gemini model).
    - How you construct prompts (e.g., include persona, instructions, or conversation history).

- **Extend the UI**
  - Edit `recorder.js` and the HTML in the `ui` router to add:
    - Conversation history panes.
    - Voice or language selectors.
    - Visualizations of audio or latency.

Use this starter as the base for your own **Murf‑powered voice agents**, adapting the pipeline, prompts, and UI for your specific product or demo.
