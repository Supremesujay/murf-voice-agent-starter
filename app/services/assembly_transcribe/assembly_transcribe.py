import assemblyai as aai
import os
from fastapi import UploadFile, WebSocket
from assemblyai.streaming.v3 import (
    BeginEvent,
    StreamingClient,
    StreamingClientOptions,
    StreamingError,
    StreamingEvents,
    StreamingParameters,
    TerminationEvent,
    TurnEvent,
)
import logging
from typing import Optional, Callable, Awaitable
import asyncio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ASSEMBLYAI_API_KEY = os.getenv("ASSEMBLYAI_API_KEY")

class AssemblyClient:
    def __init__(self):
        aai.settings.api_key = ASSEMBLYAI_API_KEY
        self.transcriber = aai.Transcriber()

        self._streaming_client: Optional[StreamingClient] = None
        self._websocket: Optional[WebSocket] = None

        # Event loop captured when ``start`` is awaited.  We need this because
        # AssemblyAI will invoke our callbacks from a background thread that is
        # NOT running inside the FastAPI / asyncio event loop.  To interact with
        # async code from that thread we enqueue work back onto the main loop
        # using ``asyncio.run_coroutine_threadsafe``.
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Callbacks set on ``start``
        self._send_to_client: Optional[Callable[[dict], Awaitable[None]]] = None
        self._on_final_transcript: Optional[Callable[[str], Awaitable[None]]] = None

    def transcribe_file(self, file: UploadFile) -> aai.Transcript:
        transcript = self.transcriber.transcribe(file.file)
        return transcript
    
    async def start(
        self,
        websocket: WebSocket,
        *,
        send_to_client: Callable[[dict], Awaitable[None]],
        on_final_transcript: Callable[[str], Awaitable[None]],
    ) -> None:
        """Initialize AssemblyAI streaming session.

        Parameters
        ----------
        websocket
            The FastAPI WebSocket connected to the end-user.  We keep this
            reference so that AssemblyAI callbacks can push data back to the
            user (e.g., partial transcripts).
        send_to_client
            Coroutine used to forward arbitrary JSON payloads to the websocket
            client.
        on_final_transcript
            Coroutine invoked whenever AssemblyAI finishes a user turn.
        """
        logger.info("Initializing transcription service with AssemblyAI.")

        # Capture the currently running event loop so that background callbacks
        # invoked by AssemblyAI can safely schedule coroutines back onto it.
        self._loop = asyncio.get_running_loop()

        if not ASSEMBLYAI_API_KEY:
            msg = "ASSEMBLYAI_API_KEY environment variable not set."
            # logger.error(msg)
            await send_to_client({"type": "error", "message": msg})
            return

        self._send_to_client = send_to_client
        self._on_final_transcript = on_final_transcript
        self._websocket = websocket

        try:
            self._streaming_client = StreamingClient(
                StreamingClientOptions(api_key=ASSEMBLYAI_API_KEY)
            )

            # ------------------------------------------------------------------
            # Register event callbacks following AssemblyAI's expected signature.
            # Each callback receives the StreamingClient instance as the first
            # argument, *not* the AssemblyService instance. We therefore define
            # small wrapper functions that capture `self` via closure so we can
            # still access our callbacks and state when needed.
            # ------------------------------------------------------------------

            def _on_begin_cb(client: StreamingClient, event: BeginEvent):  # noqa: D401
                """Handle the `Begin` event for a streaming session."""
                self._on_begin(event)

            def _on_turn_cb(client: StreamingClient, event: TurnEvent):  # noqa: D401
                """Handle the `Turn` event and forward transcripts."""
                logger.info("Received turn event: %s", event)
                self._on_turn(event)

            def _on_error_cb(client: StreamingClient, error: StreamingError):  # noqa: D401
                """Handle errors raised by AssemblyAI during streaming."""
                self._on_error(error)

            def _on_terminated_cb(client: StreamingClient, event: TerminationEvent):  # noqa: D401
                """Handle graceful termination of the streaming session."""
                self._on_terminated(event)

            self._streaming_client.on(StreamingEvents.Begin, _on_begin_cb)
            self._streaming_client.on(StreamingEvents.Turn, _on_turn_cb)
            self._streaming_client.on(StreamingEvents.Error, _on_error_cb)
            self._streaming_client.on(StreamingEvents.Termination, _on_terminated_cb)

            # Establish websocket connection to AssemblyAI with turn detection enabled
            streaming_params = StreamingParameters(
                sample_rate=16000, 
                format_turns=False,  
                format_text=False,  # Enable text formatting (enabled by default)
            )
            self._streaming_client.connect(streaming_params)
            logger.info("Connected to AssemblyAI transcription service with turn detection enabled")
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Error starting transcription: %s", exc, exc_info=True)
            await send_to_client({"type": "error", "message": str(exc)})

    async def process_audio(self, audio_data: bytes) -> None:
        """Forward raw PCM audio bytes to AssemblyAI for transcription."""
        if self._streaming_client:
            logger.info("Forwarding %d bytes of audio data to AssemblyAI", len(audio_data))
            self._streaming_client.stream(audio_data)

    async def close(self) -> None:
        """Disconnect the streaming client and clean up resources."""
        logger.info("Closing AssemblyService resources.")
        if self._streaming_client:
            self._streaming_client.disconnect(terminate=True)
            logger.info("AssemblyAI streaming client disconnected.")

    # ------------------------------------------------------------------
    # AssemblyAI event handlers – internal
    # ------------------------------------------------------------------
    def _on_begin(self, event: BeginEvent):  # noqa: D401  (simple docstring)
        logger.info("Transcription session opened: %s", event.id)

    def _on_turn(self, event: TurnEvent):  # noqa: D401  (simple docstring)
        if not event.transcript:
            logger.info("Received empty transcript event – ignoring.")
            return

        if event.end_of_turn:
            logger.info("🎯 TURN DETECTED - Final transcript: %s", event.transcript)
            logger.info("Turn details - Audio duration: %s, Words: %s", 
                       getattr(event, 'audio_duration_seconds', 'Unknown'),
                       len(event.transcript.split()) if event.transcript else 0)
            # Schedule downstream processing via callback
            if self._on_final_transcript:
                if self._loop and self._loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        self._on_final_transcript(event.transcript), self._loop
                    )
                else:
                    asyncio.create_task(self._on_final_transcript(event.transcript))
        else:
            logger.debug("Partial transcript: %s", event.transcript)
            # Forward partial transcript to websocket client
            if self._send_to_client:
                if self._loop and self._loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        self._send_to_client(
                            {"type": "partial_transcript", "text": event.transcript}
                        ),
                        self._loop,
                    )
                else:
                    asyncio.create_task(
                        self._send_to_client(
                            {"type": "partial_transcript", "text": event.transcript}
                        )
                    )

    def _on_error(self, error: StreamingError):  # noqa: D401  (simple docstring)
        logger.error("Transcription error: %s", error)
        if self._send_to_client:
            if self._loop and self._loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self._send_to_client({"type": "error", "message": str(error)}),
                    self._loop,
                )
            else:
                asyncio.create_task(
                    self._send_to_client({"type": "error", "message": str(error)})
                )

    def _on_terminated(self, event: TerminationEvent):  # noqa: D401  (simple docstring)
        logger.info(
            "Transcription session closed: %s seconds of audio processed",
            event.audio_duration_seconds,
        )
