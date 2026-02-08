"""
Chat Generator Service - Generate conversational AI responses

Uses Gemini API to generate natural dialogue responses.
"""
import os
import time
from typing import List, Dict, Any

from dotenv import load_dotenv
from google import genai
from google.genai import types

from backend.prompts.chat_system import CHAT_SYSTEM_PROMPT

load_dotenv(".env.local")


def generate_chat_response(
    user_input: str,
    history: List[Dict[str, str]] = None,
    api_key: str = None,
    model: str = None,
    max_history_turns: int = 10
) -> str:
    """
    Generate AI response for user input.

    Args:
        user_input: Current user message
        history: List of previous messages [{"role": "user/ai", "content": "..."}]
        api_key: Gemini API key (defaults to env)
        model: Model name (defaults to env)
        max_history_turns: Maximum history turns to include (default 10)

    Returns:
        AI response text
    """
    api_key = api_key or os.getenv("GEMINI_API_KEY")
    model = model or os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

    if not api_key:
        raise ValueError("GEMINI_API_KEY not set in .env.local")

    # Build conversation prompt
    prompt = _build_chat_prompt(user_input, history or [], max_history_turns)

    # Call Gemini
    client = genai.Client(api_key=api_key)

    generate_config = types.GenerateContentConfig(
        temperature=0.7,  # More creative for conversation
        safety_settings=[
            types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
        ]
    )

    max_retries = 3
    last_error = None

    for attempt in range(max_retries + 1):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=generate_config
            )

            if not response.text:
                return "I'm having trouble generating a response. Could you try rephrasing?"

            return response.text.strip()

        except Exception as e:
            error_msg = str(e)
            last_error = error_msg
            print(f"[Chat Generator Error] (attempt {attempt + 1}/{max_retries + 1}) {error_msg}")

            # Check for quota exceeded error (don't retry)
            if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg or "quota" in error_msg.lower():
                raise QuotaExceededError("API quota exceeded. Please wait a moment and try again.")

            # Retry on 503 overload
            if "503" in error_msg or "overload" in error_msg.lower() or "UNAVAILABLE" in error_msg:
                if attempt < max_retries:
                    wait_time = 2 ** attempt  # 1, 2, 4 seconds
                    print(f"[Chat Generator] Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue

            # Other errors: don't retry
            break

    raise ChatGenerationError(f"Failed to generate response: {last_error}")


class ChatGenerationError(Exception):
    """Error during chat generation."""
    pass


class QuotaExceededError(ChatGenerationError):
    """API quota exceeded."""
    pass


def _build_chat_prompt(
    user_input: str,
    history: List[Dict[str, str]],
    max_turns: int
) -> str:
    """Build the full prompt with system message and conversation history."""
    parts = [CHAT_SYSTEM_PROMPT, "\n\n---\n\n"]

    # Add recent history (limit to max_turns)
    recent_history = history[-max_turns * 2:] if history else []

    if recent_history:
        parts.append("Previous conversation:\n")
        for msg in recent_history:
            role = "User" if msg.get("role") == "user" else "Assistant"
            content = msg.get("content", "")
            parts.append(f"{role}: {content}\n")
        parts.append("\n")

    # Add current input
    parts.append(f"User: {user_input}\n\nAssistant:")

    return "".join(parts)


__all__ = ["generate_chat_response", "ChatGenerationError", "QuotaExceededError"]
