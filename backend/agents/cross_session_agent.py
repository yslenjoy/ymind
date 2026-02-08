"""
Cross-Session Analyzer Agent

Analyzes multiple sessions to discover deep cross-session patterns:
session-level links, node-level resonances, recurring patterns, and insights.

Uses Gemini long-context to reason across all sessions at once.
"""
import os
import json
import time
from typing import Dict, Any, List

from dotenv import load_dotenv
from google import genai
from google.genai import types

from backend.prompts.cross_session_analyzer import (
    CROSS_SESSION_ANALYZER_PROMPT,
    format_sessions_for_analysis,
)

load_dotenv(".env.local")

# Model for cross-session analysis — separate from other agents
# Use a strong model (e.g. gemini-2.5-pro) for deep psychological reasoning
CROSS_SESSION_MODEL = os.getenv(
    "CROSS_SESSION_MODEL",
    "gemini-3-pro-preview",
)
print(f"[Cross-Session] Model resolved to: {CROSS_SESSION_MODEL}")


def analyze_cross_sessions(
    session_payloads: List[Dict[str, Any]],
    api_key: str = None,
    model: str = None,
    max_retries: int = 2,
) -> Dict[str, Any]:
    """
    Analyze multiple sessions for cross-session patterns.

    Args:
        session_payloads: List of session dicts (sorted by created_at),
            each with: session_id, meta, key_nodes
        api_key: Gemini API key (falls back to env)
        model: Model to use (falls back to CROSS_SESSION_MODEL)
        max_retries: Number of retry attempts on failure

    Returns:
        {
            "session_links": [...],
            "node_resonances": [...],
            "recurring_patterns": [...],
            "insights": [...]
        }
    """
    api_key = api_key or os.getenv("GEMINI_API_KEY")
    model = model or CROSS_SESSION_MODEL

    if not api_key:
        raise ValueError("GEMINI_API_KEY not set in .env.local")

    if not session_payloads:
        print("[Cross-Session] No sessions to analyze")
        return _default_result()

    if len(session_payloads) < 2:
        print("[Cross-Session] Need at least 2 sessions for cross-session analysis")
        return _default_result()

    # Build prompt with dynamic output volume targets
    sessions_text = format_sessions_for_analysis(session_payloads)
    n_sessions = len(session_payloads)
    total_nodes = sum(len(sp.get("key_nodes", [])) for sp in session_payloads)

    # Links scale with session count (aim for a connected graph)
    link_min = max(3, n_sessions - 1)
    link_max = min(n_sessions * 2, n_sessions * (n_sessions - 1) // 2)

    # Resonances scale with key_nodes count (more nodes = more potential connections)
    resonance_min = max(8, total_nodes // 4)
    resonance_max = min(50, total_nodes // 2)

    # Insights scale with sessions
    insight_min = max(3, n_sessions)
    insight_max = min(10, n_sessions * 2)

    prompt = CROSS_SESSION_ANALYZER_PROMPT.format(
        sessions_data=sessions_text,
        link_min=link_min,
        link_max=link_max,
        resonance_min=resonance_min,
        resonance_max=resonance_max,
        insight_min=insight_min,
        insight_max=insight_max,
    )

    print(
        f"[Cross-Session] Analyzing {n_sessions} sessions, "
        f"{total_nodes} key nodes with model={model} "
        f"(targets: {link_min}-{link_max} links, {resonance_min}-{resonance_max} resonances, "
        f"{insight_min}-{insight_max} insights)"
    )

    # Call Gemini (3-min timeout — cross-session prompts are large)
    client = genai.Client(api_key=api_key, http_options={"timeout": 180_000})

    generate_config = types.GenerateContentConfig(
        temperature=0.4,  # Slightly higher than summary for creative insight
        response_mime_type="application/json",
        safety_settings=[
            types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
        ],
    )

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=generate_config,
            )

            if not response.text:
                print(f"[Cross-Session] Empty response (attempt {attempt + 1})")
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                return _default_result()

            result = json.loads(response.text.strip())
            result = _validate_result(result)

            print(
                f"[Cross-Session] Result: "
                f"{len(result['session_links'])} links, "
                f"{len(result['node_resonances'])} resonances, "
                f"{len(result['recurring_patterns'])} patterns, "
                f"{len(result['insights'])} insights"
            )
            return result

        except json.JSONDecodeError as e:
            print(f"[Cross-Session] JSON parse failed: {e}")
            if attempt < max_retries:
                time.sleep(2 ** attempt)
                continue
            return _default_result()

        except Exception as e:
            last_error = e
            print(
                f"[Cross-Session] Failed (attempt {attempt + 1}/{max_retries + 1}): {e}"
            )
            if attempt < max_retries:
                time.sleep(2 ** attempt)
                continue

    print(f"[Cross-Session] Failed after {max_retries + 1} attempts: {last_error}")
    return _default_result()


def _validate_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and normalize the LLM output structure."""
    # Normalize insights: handle both old string format and new object format
    raw_insights = result.get("insights", [])
    insights = []
    for item in raw_insights:
        if isinstance(item, str):
            # Legacy string format — no session association
            insights.append({"content": item, "related_session_ids": []})
        elif isinstance(item, dict):
            insights.append({
                "content": item.get("content", ""),
                "related_session_ids": item.get("related_session_ids", []),
            })

    return {
        "session_links": result.get("session_links", []),
        "node_resonances": result.get("node_resonances", []),
        "recurring_patterns": result.get("recurring_patterns", []),
        "insights": insights,
    }


def _default_result() -> Dict[str, Any]:
    """Return empty result on failure — never block the main flow."""
    return {
        "session_links": [],
        "node_resonances": [],
        "recurring_patterns": [],
        "insights": [],
    }


__all__ = ["analyze_cross_sessions", "CROSS_SESSION_MODEL"]
