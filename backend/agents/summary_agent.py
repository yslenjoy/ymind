"""
Summary Agent - Extract themes, emotions, and summary from a Session.

Used for Forest View cross-session semantic connections.
"""
import os
import json
import time
from typing import Dict, Any, List

from dotenv import load_dotenv
from google import genai
from google.genai import types

from backend.prompts.summary_extractor import (
    SUMMARY_EXTRACTOR_PROMPT,
    format_history_for_summary,
    format_nodes_for_summary,
)

load_dotenv(".env.local")


def extract_session_summary(
    history: List[Dict[str, str]],
    nodes: List[Dict[str, Any]],
    api_key: str = None,
    model: str = None,
    max_retries: int = 2,
) -> Dict[str, Any]:
    """
    Extract themes, emotions, and summary from a session.

    Args:
        history: Conversation history [{"role": "user/ai", "content": "..."}]
        nodes: List of node dicts with label, type, rich_summary

    Returns:
        {
            "themes": ["theme1", "theme2", "theme3"],
            "emotions": ["emotion1", ...],
            "summary": "..."
        }
    """
    api_key = api_key or os.getenv("GEMINI_API_KEY")
    model = model or os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

    if not api_key:
        raise ValueError("GEMINI_API_KEY not set in .env.local")

    # Format prompt
    prompt = SUMMARY_EXTRACTOR_PROMPT.format(
        history=format_history_for_summary(history),
        nodes=format_nodes_for_summary(nodes),
    )

    print(f"[Summary Agent] Extracting themes/emotions from {len(history)} messages, {len(nodes)} nodes")

    # Call Gemini
    client = genai.Client(api_key=api_key)

    generate_config = types.GenerateContentConfig(
        temperature=0.3,  # Lower for more consistent output
        response_mime_type="application/json",
        safety_settings=[
            types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
        ]
    )

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=generate_config
            )

            if not response.text:
                print(f"[Warning] Summary extraction returned empty response (attempt {attempt + 1})")
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                return _default_summary()

            result = json.loads(response.text.strip())

            # Validate and normalize
            summary_data = {
                "title": result.get("title", "")[:50],
                "themes": result.get("themes", [])[:3],
                "emotions": result.get("emotions", [])[:5],
                "summary": result.get("summary", "")[:200],
            }
            print(f"[Summary Agent] Result: {summary_data}")
            return summary_data

        except json.JSONDecodeError as e:
            print(f"[Error] Summary JSON parse failed: {e}")
            return _default_summary()

        except Exception as e:
            last_error = e
            print(f"[Error] Summary extraction failed (attempt {attempt + 1}/{max_retries + 1}): {e}")
            if attempt < max_retries:
                time.sleep(2 ** attempt)
                continue

    print(f"[Error] Summary extraction failed after {max_retries + 1} attempts: {last_error}")
    return _default_summary()


def _default_summary() -> Dict[str, Any]:
    """Return default empty summary on failure."""
    return {
        "title": "",
        "themes": [],
        "emotions": [],
        "summary": "",
    }


__all__ = ["extract_session_summary"]
