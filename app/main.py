from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from routers import ws_chat, ui
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(openapi_url="/openai.json", docs_url="/docs", redoc_url="/redoc")

# Mount static files
app.mount("/assets", StaticFiles(directory="app/assets"), name="assets")

app.include_router(ui.router)
app.include_router(ws_chat.router)