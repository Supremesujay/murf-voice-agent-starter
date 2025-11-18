from google import genai
from google.genai import types
import os
from typing import AsyncGenerator
import asyncio

class GeminiLLM:
    def __init__(self):
        self.genai_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    def generate_response(self, prompt: str) -> str:
        response = self.genai_client.models.generate_content(model="gemini-2.5-flash-lite", contents=prompt)
        return response.text
    
    async def generate_streaming_response(self, prompt: str) -> AsyncGenerator[str, None]:
        """Generate a streaming response from Gemini LLM."""
        try:
            # Use the streaming version of generate_content
            config = types.GenerateContentConfig()
            response = self.genai_client.models.generate_content_stream(
                model="gemini-2.5-flash-lite", 
                contents=prompt,
                config=config
            )
            
            # Iterate through streaming chunks
            for chunk in response:
                if chunk.text:
                    yield chunk.text
                    # Small delay to make streaming visible
                    await asyncio.sleep(0.01)
                    
        except Exception as e:
            print(f"Error in streaming response: {e}")
            yield f"Error generating response: {str(e)}"