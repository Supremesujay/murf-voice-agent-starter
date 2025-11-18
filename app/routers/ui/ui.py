from fastapi import status, APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/ui", tags=["UI"])

@router.get("/", status_code=status.HTTP_200_OK, response_class=HTMLResponse)
async def tts_ui():
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Text to Speech</title>
        <script src="/assets/recorder.js"></script>
    </head>
    <body>
        <h1>Conversational Agent</h1>
        <p>
            <button id="startButton">Start Recording</button>
            <button id="stopButton" disabled>Stop Recording</button>
        </p>

        <audio id="recorder-audio-playback" controls></audio>   
        <p id="request-status"></p>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)
