from typing import Dict, List, Literal, TypedDict


class ChatMessage(TypedDict):
    role: Literal["user", "assistant"]
    content: str


# Global in-memory chat history store keyed by session_id
_GLOBAL_CHAT_HISTORY: Dict[str, List[ChatMessage]] = {}


class ChatManager:
    """Manages chat history for sessions using a global in-memory store.

    This is intentionally simple for a single-process FastAPI server.
    """

    def get_history(self, session_id: str) -> List[ChatMessage]:
        if session_id not in _GLOBAL_CHAT_HISTORY:
            _GLOBAL_CHAT_HISTORY[session_id] = []
        return _GLOBAL_CHAT_HISTORY[session_id]

    def append_user_message(self, session_id: str, message: str) -> None:
        history = self.get_history(session_id)
        history.append({"role": "user", "content": message})

    def append_assistant_message(self, session_id: str, message: str) -> None:
        history = self.get_history(session_id)
        history.append({"role": "assistant", "content": message})

    def clear(self, session_id: str) -> None:
        _GLOBAL_CHAT_HISTORY.pop(session_id, None)

    def compile_prompt_from_history(self, session_id: str) -> str:
        """Return a plain-text prompt compiled from history suitable for LLMs
        that accept a single string input.
        """
        compiled_lines: List[str] = []
        for message in self.get_history(session_id):
            if message["role"] == "user":
                compiled_lines.append(f"User: {message['content']}")
            else:
                compiled_lines.append(f"Assistant: {message['content']}")
        compiled_lines.append("Assistant:")
        return "\n".join(compiled_lines)


# Singleton-like instance to be used across the app
chat_manager = ChatManager()


