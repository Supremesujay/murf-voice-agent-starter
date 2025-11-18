from pydantic import BaseModel
from typing import Any

class GenerateAudioRequest(BaseModel):
    text: str
    voice_id: str

class GenerateAudioResponse(BaseModel):
    audio_file: str
    audio_length_in_seconds: float
    consumed_character_count: int
    remaining_character_count: int
    warning: str
    word_durations: list[Any]