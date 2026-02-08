"""
Session Storage Service

Handles persistence of session data to JSON files.
Organized by user: outputs/sessions/{user_id}/
"""
import json
from datetime import datetime
from typing import List, Optional, Dict, Any
from pathlib import Path

from backend.models.state import MindMapState
from backend.models.node import GraphNode


# Base storage directory
SESSIONS_BASE = Path("outputs/sessions")


def _get_user_dir(user_id: str) -> Path:
    """Get user-specific session directory."""
    return SESSIONS_BASE / user_id


def _get_index_file(user_id: str) -> Path:
    """Get user-specific index file."""
    return _get_user_dir(user_id) / "index.json"


def _ensure_user_dir(user_id: str):
    """Ensure user directory exists."""
    _get_user_dir(user_id).mkdir(parents=True, exist_ok=True)


def _load_index(user_id: str) -> List[Dict[str, Any]]:
    """Load user's session index."""
    index_file = _get_index_file(user_id)
    if not index_file.exists():
        return []
    with open(index_file, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_index(user_id: str, index: List[Dict[str, Any]]):
    """Save user's session index."""
    _ensure_user_dir(user_id)
    with open(_get_index_file(user_id), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def _state_to_dict(state: MindMapState) -> Dict[str, Any]:
    """Convert MindMapState to serializable dict."""
    return {
        "nodes": {k: v.model_dump() for k, v in state.nodes.items()},
        "root_id": state.root_id,
        "active_node_id": state.active_node_id,
        "current_input": state.current_input,
        "current_ai_response": state.current_ai_response,
        "history": state.history,
        "turn_count": state.turn_count
    }


def _dict_to_state(data: Dict[str, Any]) -> MindMapState:
    """Convert dict back to MindMapState."""
    nodes = {}
    for node_id, node_data in data.get("nodes", {}).items():
        nodes[node_id] = GraphNode(**node_data)

    return MindMapState(
        nodes=nodes,
        root_id=data.get("root_id", ""),
        active_node_id=data.get("active_node_id", ""),
        current_input=data.get("current_input", ""),
        current_ai_response=data.get("current_ai_response"),
        history=data.get("history", []),
        turn_count=data.get("turn_count", 0)
    )


def save_session(
    user_id: str,
    session_id: str,
    state: MindMapState,
    title: Optional[str] = None,
    themes: Optional[List[str]] = None,
    emotions: Optional[List[str]] = None,
    summary: Optional[str] = None,
    key_labels: Optional[List[str]] = None,
    key_nodes: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """
    Save session to user's directory and update index.

    Returns the session metadata.
    """
    _ensure_user_dir(user_id)

    now = datetime.now().isoformat()

    # Load existing index
    index = _load_index(user_id)

    # Find existing entry or create new
    existing_entry = None
    for entry in index:
        if entry["session_id"] == session_id:
            existing_entry = entry
            break

    # Build metadata
    filename = f"session_{session_id}.json"
    if existing_entry:
        meta = {
            "session_id": session_id,
            "title": title or existing_entry.get("title", "Untitled"),
            "created_at": existing_entry.get("created_at", now),
            "updated_at": now,
            "turn_count": state.turn_count,
            "node_count": len(state.nodes),
            "filename": filename,
            "tags": existing_entry.get("tags", []),
            "summary": summary if summary is not None else existing_entry.get("summary", ""),
            "themes": themes if themes is not None else existing_entry.get("themes", []),
            "emotions": emotions if emotions is not None else existing_entry.get("emotions", []),
            "key_labels": key_labels if key_labels is not None else existing_entry.get("key_labels", []),
            "key_nodes": key_nodes if key_nodes is not None else existing_entry.get("key_nodes", []),
        }
    else:
        meta = {
            "session_id": session_id,
            "title": title or "Untitled",
            "created_at": now,
            "updated_at": now,
            "turn_count": state.turn_count,
            "node_count": len(state.nodes),
            "filename": filename,
            "tags": [],
            "summary": summary or "",
            "themes": themes or [],
            "emotions": emotions or [],
            "key_labels": key_labels or [],
            "key_nodes": key_nodes or [],
        }

    # Save session file
    session_file = _get_user_dir(user_id) / filename
    session_data = {
        "meta": meta,
        "state": _state_to_dict(state)
    }
    with open(session_file, "w", encoding="utf-8") as f:
        json.dump(session_data, f, ensure_ascii=False, indent=2)

    # Update index
    if existing_entry:
        existing_entry.update(meta)
    else:
        index.append(meta)

    _save_index(user_id, index)

    return meta


def load_session(user_id: str, session_id: str) -> Optional[Dict[str, Any]]:
    """
    Load session by ID from user's directory.

    Returns dict with 'meta' and 'state' (as MindMapState).
    """
    session_file = _get_user_dir(user_id) / f"session_{session_id}.json"

    if not session_file.exists():
        return None

    with open(session_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    return {
        "meta": data["meta"],
        "state": _dict_to_state(data["state"])
    }


def list_sessions(user_id: str) -> List[Dict[str, Any]]:
    """List all sessions for a user (metadata only)."""
    return _load_index(user_id)


def delete_session(user_id: str, session_id: str) -> bool:
    """Delete session file and remove from user's index."""
    session_file = _get_user_dir(user_id) / f"session_{session_id}.json"

    # Remove file
    if session_file.exists():
        session_file.unlink()

    # Update index
    index = _load_index(user_id)
    index = [e for e in index if e["session_id"] != session_id]
    _save_index(user_id, index)

    return True
