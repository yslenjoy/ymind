"""
Unified Agent - One-Shot Analysis + Node Extraction
(Replaces separate Router + Generator calls)
"""
import os
import json
import time
from typing import Dict, Any, List

from dotenv import load_dotenv
from google import genai
from google.genai import types

from backend.models.node import GraphNode, ContextSnapshot, NodeRelation
from backend.models.state import MindMapState
from backend.prompts.unified_extractor import (
    UNIFIED_EXTRACTOR_PROMPT,
    format_existing_nodes,
    format_history_context,
)

load_dotenv(".env.local")


def call_gemini_unified(
    prompt: str,
    api_key: str = None,
    model: str = None,
    max_retries: int = 3
) -> Dict[str, Any]:
    """Call Gemini API with unified extractor prompt.

    Returns:
        {
            "analysis": { "user_intent", "emotional_tone", "key_tension", "reasoning_trace" },
            "nodes": [ { "label", "type", "rich_summary", "source", "relations" } ]
        }
    """
    api_key = api_key or os.getenv("GEMINI_API_KEY")
    model = model or os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

    if not api_key:
        raise ValueError("GEMINI_API_KEY not set in .env.local")

    client = genai.Client(api_key=api_key)

    generate_config = types.GenerateContentConfig(
        temperature=0.4,  # Slightly higher for more natural labels
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
                finish_reason = getattr(response, 'finish_reason', 'unknown')
                print(f"\n[Warning] Empty response (attempt {attempt + 1}/{max_retries + 1})")

                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue

                return {
                    "_error": f"Empty response after {max_retries + 1} attempts",
                    "analysis": {"reasoning_trace": "API returned empty response"},
                    "nodes": []
                }

            return json.loads(response.text.strip())

        except json.JSONDecodeError as e:
            print(f"\n[Error] JSON parse failed: {e}")
            return {
                "_error": f"JSON parse error: {str(e)}",
                "analysis": {"reasoning_trace": f"Failed to parse: {response.text[:200]}"},
                "nodes": []
            }

        except Exception as e:
            last_error = e
            print(f"\n[Error] API call failed (attempt {attempt + 1}): {e}")
            if attempt < max_retries:
                time.sleep(2 ** attempt)
                continue

    return {
        "_error": f"System error: {str(last_error)}",
        "analysis": {"reasoning_trace": str(last_error)},
        "nodes": []
    }


def format_unified_prompt(
    user_input: str,
    ai_response: str,
    turn_id: int,
    existing_nodes: List[Dict] = None,
    history: List[Dict[str, str]] = None,
) -> str:
    """Format the unified extractor prompt."""
    return UNIFIED_EXTRACTOR_PROMPT.format(
        user_input=user_input,
        ai_response=ai_response,
        turn_id=turn_id,
        existing_nodes=format_existing_nodes(existing_nodes or []),
        history_context=format_history_context(history or []),
    )


def unified_extractor_step(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    LangGraph node: One-shot analysis + node extraction.

    Replaces: router_step + generator_step

    Returns:
        - temp_analysis: { user_intent, emotional_tone, key_tension, reasoning_trace }
        - temp_new_nodes: List of GraphNodes
        - temp_parent_id: Parent node ID (root for now, can be enhanced)
    """
    # Convert nodes dict if needed (dict of dict -> dict of GraphNode)
    nodes_dict = state.get("nodes", {})
    converted_nodes = {}
    for node_id, node_data in nodes_dict.items():
        if isinstance(node_data, dict):
            converted_nodes[node_id] = GraphNode(**node_data)
        else:
            converted_nodes[node_id] = node_data

    state_with_nodes = {**state, "nodes": converted_nodes}
    mindmap_state = MindMapState(**state_with_nodes)

    # Build existing nodes list for context (include turn_id for cross-turn referencing)
    existing_nodes = [
        {
            "label": n.label,
            "type": n.type,
            "turn_id": n.original_context.turn_id if n.original_context else "?",
        }
        for n in mindmap_state.nodes.values()
        if n.type != "root"
    ]

    # Format prompt (turn_id is 1-based: first turn = 1)
    current_turn_id = mindmap_state.turn_count + 1
    prompt = format_unified_prompt(
        user_input=mindmap_state.current_input,
        ai_response=mindmap_state.current_ai_response or "",
        turn_id=current_turn_id,
        existing_nodes=existing_nodes,
        history=mindmap_state.history,
    )

    # Call LLM (single call!)
    result = call_gemini_unified(prompt)

    # Extract analysis
    analysis = result.get("analysis", {})

    # Always mount to root - use semantic relations for connections between nodes
    # This keeps the tree flat and avoids confusing parent-child relationships
    parent_id = mindmap_state.root_id

    # Build GraphNodes from result
    raw_nodes = result.get("nodes", [])
    new_nodes = _build_nodes_from_result(
        raw_nodes=raw_nodes,
        parent_id=parent_id,
        mindmap_state=mindmap_state
    )

    # Return updated state
    return {
        **state,
        "temp_analysis": analysis,
        "temp_new_nodes": new_nodes,
        "temp_new_node": new_nodes[0] if new_nodes else None,
        "temp_parent_id": parent_id,
        "temp_reasoning": analysis.get("reasoning_trace", ""),
    }


def _build_nodes_from_result(
    raw_nodes: List[Dict],
    parent_id: str,
    mindmap_state: MindMapState
) -> List[GraphNode]:
    """Build GraphNode objects from LLM result."""
    if not raw_nodes:
        return []

    # Build label->id mapping from existing nodes (for cross-turn relations)
    label_to_id: Dict[str, str] = {}
    for node in mindmap_state.nodes.values():
        if node.type != "root":
            label_to_id[node.label] = node.id

    # First pass: create nodes and add to label->id mapping
    nodes: List[GraphNode] = []

    for raw in raw_nodes:
        context = ContextSnapshot(
            raw_text=raw.get("rich_summary", raw.get("label", "")),
            pre_text=mindmap_state.history[-1].get("content") if mindmap_state.history else None,
            post_text=None,
            speaker_role=raw.get("source", "user"),
            turn_id=mindmap_state.turn_count + 1
        )

        node = GraphNode(
            label=raw.get("label", "Node"),
            type=raw.get("type", "fact"),
            rich_summary=raw.get("rich_summary", ""),
            original_context=context,
            source=raw.get("source", "user"),
            status="active",
            parent_id=parent_id,
            children_ids=[],
            relations=[]
        )

        nodes.append(node)
        label_to_id[node.label] = node.id

    # Second pass: resolve relations
    for i, raw in enumerate(raw_nodes):
        for rel in raw.get("relations", []):
            target_label = rel.get("target_label", "")
            relation_type = rel.get("relation_type", "causes")

            target_id = label_to_id.get(target_label)
            if target_id:
                nodes[i].relations.append(NodeRelation(
                    target_id=target_id,
                    relation_type=relation_type
                ))

    return nodes


__all__ = [
    "unified_extractor_step",
    "call_gemini_unified",
    "format_unified_prompt",
]
