"""
Audio Transcriber Service - Transcribe audio using Gemini's native audio understanding.

Uses Gemini API to convert speech audio into text.
"""
import os
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv(".env.local")


def transcribe_audio(
    audio_bytes: bytes,
    mime_type: str = "audio/webm",
    api_key: str = None,
    model: str = None,
    max_retries: int = 2,
) -> str:
    """
    Transcribe audio using Gemini's native audio understanding.

    Args:
        audio_bytes: Raw audio data
        mime_type: Audio MIME type (e.g. "audio/webm", "audio/mp4", "audio/wav")
        api_key: Gemini API key (defaults to env)
        model: Model name (defaults to env TRANSCRIBE_MODEL)
        max_retries: Number of retries on failure

    Returns:
        Transcribed text, or empty string on failure.
    """
    api_key = api_key or os.getenv("GEMINI_API_KEY")
    model = model or os.getenv("TRANSCRIBE_MODEL", "gemini-2.0-flash")

    if not api_key:
        raise ValueError("GEMINI_API_KEY not set in .env.local")

    if not audio_bytes:
        print("[Transcriber] Empty audio data")
        return ""

    print(f"[Transcriber] Transcribing {len(audio_bytes)} bytes ({mime_type}) with {model}")

    client = genai.Client(api_key=api_key, http_options={"timeout": 120_000})

    generate_config = types.GenerateContentConfig(
        temperature=0.1,
        safety_settings=[
            types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
        ],
    )

    audio_part = types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)

    prompt = (
        "Transcribe this audio verbatim. "
        "Return ONLY the transcript text, no extra commentary or formatting."
    )

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            response = client.models.generate_content(
                model=model,
                contents=[prompt, audio_part],
                config=generate_config,
            )

            if not response.text:
                print(f"[Transcriber] Empty response (attempt {attempt + 1}/{max_retries + 1})")
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                return ""

            text = response.text.strip()
            print(f"[Transcriber] Result: {text[:100]}...")
            return text

        except Exception as e:
            last_error = str(e)
            print(f"[Transcriber] Error (attempt {attempt + 1}/{max_retries + 1}): {last_error}")

            if "429" in last_error or "RESOURCE_EXHAUSTED" in last_error:
                print("[Transcriber] Quota exceeded, not retrying")
                return ""

            if attempt < max_retries:
                time.sleep(2 ** attempt)
                continue

    print(f"[Transcriber] Failed after {max_retries + 1} attempts: {last_error}")
    return ""


__all__ = ["transcribe_audio"]
