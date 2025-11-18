from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect
from pathlib import Path
from datetime import datetime
from services.assembly_transcribe.assembly_transcribe import AssemblyClient
from services.gemini_llm.gemini_llm import GeminiLLM
import os
import websockets
import logging
import json
import asyncio
from typing import Optional

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WS Chat"])

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    assembly_client = AssemblyClient()
    gemini_llm = GeminiLLM()

    MURF_API_KEY = os.getenv("MURF_API_KEY")

    murf_ws_url = (
        "wss://global.api.murf.ai/v1/speech/stream-input?api-key="
        f"{MURF_API_KEY}&format=WAV&model=FALCON"
    )

    MURF_CONTEXT_ID = "1234567890"

    try:
        async with websockets.connect(murf_ws_url) as murf_ws:
            logger.info("Successfully connected to Murf WebSocket")
            
            async def send_to_client(data: dict):
                print(f"Sending data to client: {data}")
                await websocket.send_json(data)

            async def on_final_transcript(transcript: str):
                print(f"Final transcript: {transcript}")
                await send_to_client({"type": "final_transcript", "text": transcript})
                
                # Generate streaming LLM response
                print(f"\n🤖 Generating LLM response for: {transcript}")
                
                # Send voice config once at the start of the conversation turn
                voice_config_msg = {
                    "voice_config": {
                        "voiceId": "en-US-amara",
                    },
                    "context_id": MURF_CONTEXT_ID
                }
                logger.info("Sending voice config: %s", voice_config_msg)
                await murf_ws.send(json.dumps(voice_config_msg))
                
                # Stream all LLM chunks without blocking
                chunk_count = 0
                async for chunk in gemini_llm.generate_streaming_response(transcript):
                    chunk_count += 1
                    text_message = {"text": chunk, "end": False, "context_id": MURF_CONTEXT_ID}
                    logger.info("Sending text chunk %d: %s", chunk_count, text_message)
                    await murf_ws.send(json.dumps(text_message))
                
                # Add a small delay to ensure Murf has time to process short responses
                # This prevents the final message from being sent before TTS generation starts
                if chunk_count <= 2:  # For very short responses (1-2 chunks)
                    logger.info("Short response detected, adding buffer delay before final message")
                    await asyncio.sleep(0.5)  # 500ms delay
                
                # Send final message to indicate end of text stream
                final_message = {"text": "", "end": True, "context_id": MURF_CONTEXT_ID}
                logger.info("Sending final message: %s", final_message)
                await murf_ws.send(json.dumps(final_message))

            async def handle_murf_audio_stream():
                """Handle incoming audio chunks from Murf WebSocket"""
                audio_chunk_count = 0
                while True:
                    try:
                        response = await murf_ws.recv()
                        data = json.loads(response)
                        logger.info(
                            "Received from Murf: %s", data.keys() if isinstance(data, dict) else "Invalid data"
                        )

                        if "audio" in data:
                            audio_chunk_count += 1
                            logger.info(f"Sending audio chunk #{audio_chunk_count} to client")
                            await send_to_client({"type": "audio_chunk", "audio_data": data["audio"]})
                        else:
                            logger.info("Murf response (no audio): %s", data)

                        if data.get("final"):
                            logger.info("Murf audio stream completed, clearing context")
                            await murf_ws.send(json.dumps({"clear": True, "context_id": MURF_CONTEXT_ID}))
                            await send_to_client({"type": "speech_complete"})
                            
                    except websockets.exceptions.ConnectionClosed:
                        logger.info("Murf WebSocket connection closed")
                        await send_to_client({"type": "speech_complete"})
                        break
                    except json.JSONDecodeError as e:
                        logger.error("Failed to parse Murf response: %s", e)
                    except Exception as e:
                        logger.error("Error handling Murf audio stream: %s", e)
                        break

            await assembly_client.start(websocket, send_to_client=send_to_client, on_final_transcript=on_final_transcript)
            print("WebSocket connected")
            
            # Start audio handler task
            audio_handler_task = asyncio.create_task(handle_murf_audio_stream())
            
            try:
                while True:
                    data = await websocket.receive_bytes()
                    if data:
                        await assembly_client.process_audio(data)
            except WebSocketDisconnect:
                print("WebSocket disconnected")
            finally:
                # Clean up tasks
                audio_handler_task.cancel()
                try:
                    await audio_handler_task
                except asyncio.CancelledError:
                    pass
                await assembly_client.close()
    except websockets.exceptions.WebSocketException as e:
        logger.error(f"Murf WebSocket error: {e}")
        await websocket.send_json({"type": "error", "message": f"Murf connection error: {str(e)}"})
    except Exception as e:
        logger.error(f"Error in websocket_endpoint: {e}", exc_info=True)
        await websocket.send_json({"type": "error", "message": str(e)})

