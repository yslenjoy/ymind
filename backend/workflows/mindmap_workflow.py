"""
MindMap Workflow - LangGraph orchestration.

Unified flow: Input -> [Init Root?] -> Extractor -> Updater -> Output
(Replaces old: Router -> Generator -> Updater)
"""
from typing import Dict, Any
from typing_extensions import Literal
from langgraph.graph import StateGraph, END

from backend.models.state import MindMapState
from backend.agents.unified_agent import unified_extractor_step
from backend.services.state_updater import updater_step, create_root_node


def has_nodes(state: Dict[str, Any]) -> Literal["extractor", "init"]:
    """Conditional edge: Check if graph has nodes (root exists)."""
    if state.get("nodes") and state.get("root_id"):
        return "extractor"
    return "init"


def _generate_session_title(user_input: str, max_len: int = 30) -> str:
    """Generate a clean session title from user input."""
    if not user_input:
        return "Session"

    # Clean up whitespace and newlines
    text = " ".join(user_input.split())

    # If short enough, use as-is
    if len(text) <= max_len:
        return text

    # Try to find a good break point (punctuation or space)
    break_chars = ["。", "，", "？", "！", ".", ",", "?", "!", " ", "、", "：", ":", "\n"]

    # Look for break point within max_len (search from end to middle)
    best_break = max_len
    for i in range(min(max_len, len(text)) - 1, max(0, max_len // 2), -1):
        if text[i] in break_chars:
            best_break = i
            break

    # Truncate and clean up trailing punctuation
    title = text[:best_break].rstrip("，。、：,.: \n")
    if len(title) < len(text):
        title += "..."
    return title


def init_root_step(state: Dict[str, Any]) -> Dict[str, Any]:
    """Initialize root node for new conversation, or pass through if already initialized."""
    # If already has nodes, just pass through (preserve state)
    nodes = state.get("nodes")
    root_id = state.get("root_id")
    print(f"DEBUG init_root_step: nodes={bool(nodes)}, len={len(nodes) if nodes else 0}, root_id={root_id}")
    if nodes and root_id:
        print("DEBUG init_root_step: PASS THROUGH (keeping existing nodes)")
        return state
    print("DEBUG init_root_step: CREATING NEW ROOT (will lose existing nodes!)")

    # Generate session title from first user input
    user_input = state.get("current_input", "")
    title = _generate_session_title(user_input)

    root_node = create_root_node(label=title)
    return {
        **state,  # Preserve all input fields
        "nodes": {root_node.id: root_node},
        "root_id": root_node.id,
        "active_node_id": root_node.id,
        "turn_count": 0,
    }


def create_workflow() -> StateGraph:
    """
    Create and return the MindMap LangGraph workflow.

    Flow: Input -> [Init Root?] -> Extractor (unified) -> Updater -> Output
    """
    workflow = StateGraph(dict)

    # Add nodes (simplified: no separate router)
    workflow.add_node("init", init_root_step)
    workflow.add_node("extractor", unified_extractor_step)
    workflow.add_node("updater", updater_step)

    # Add edges
    workflow.set_entry_point("init")
    workflow.add_conditional_edges(
        "init",
        has_nodes,
        {
            "extractor": "extractor",
            "init": "extractor"  # After init, go to extractor
        }
    )
    workflow.add_edge("extractor", "updater")
    workflow.add_edge("updater", END)

    return workflow


def compile_workflow() -> StateGraph:
    """Compile the workflow into an executable graph."""
    workflow = create_workflow()
    return workflow.compile()


__all__ = ["create_workflow", "compile_workflow"]
