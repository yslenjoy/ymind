"""
Session Loader for Cross-Session Analysis

Loads all sessions for a user, builds analysis payloads with key nodes
and raw conversation context, computes session hash for cache validation.
"""
import hashlib
import json
from typing import List, Dict, Any, Optional
from pathlib import Path

from backend.services.session_storage import (
    list_sessions,
    load_session,
    _get_user_dir,
)

# Node types to include in analysis (filter out fact/root/topic/detail)
KEY_NODE_TYPES = {"friction", "spark", "action"}

# Max key nodes per session for analysis — keeps prompt size manageable
# Priority: action > friction > spark (same as main.py save logic)
MAX_KEY_NODES_PER_SESSION = 10


def compute_session_hash(sessions_meta: List[Dict[str, Any]]) -> str:
    """Compute a fingerprint hash of all sessions for cache validation.

    Hash factors: session_id + updated_at + node_count (sorted by session_id).
    Any change (add/delete/modify session) will produce a different hash.
    """
    fingerprints = []
    for meta in sorted(sessions_meta, key=lambda m: m["session_id"]):
        fp = f"{meta['session_id']}|{meta.get('updated_at', '')}|{meta.get('node_count', 0)}"
        fingerprints.append(fp)

    combined = ",".join(fingerprints)
    return hashlib.sha256(combined.encode()).hexdigest()


def _extract_raw_context(
    history: List[Dict[str, str]],
    turn_id: int,
    is_zero_based: bool,
) -> Dict[str, Optional[str]]:
    """Map a node's turn_id to the raw conversation from history.

    History is a flat list: [user_msg, ai_msg, user_msg, ai_msg, ...]
    turn_id N maps to history[(N - offset) * 2] (user) and +1 (ai).
    """
    offset = 0 if is_zero_based else 1
    idx = (turn_id - offset) * 2

    user_text = None
    ai_text = None

    if 0 <= idx < len(history):
        user_text = history[idx].get("content")
    if 0 <= idx + 1 < len(history):
        ai_text = history[idx + 1].get("content")

    return {"user": user_text, "ai": ai_text}


def _detect_zero_based(nodes_dict: Dict[str, Any]) -> bool:
    """Detect if a session's nodes use 0-based or 1-based turn_id."""
    turn_ids = []
    for node in nodes_dict.values():
        node_type = node.type if hasattr(node, "type") else node.get("type", "")
        if node_type == "root":
            continue
        ctx = node.original_context if hasattr(node, "original_context") else node.get("original_context", {})
        tid = ctx.turn_id if hasattr(ctx, "turn_id") else ctx.get("turn_id", 1)
        turn_ids.append(tid)

    if not turn_ids:
        return False
    return min(turn_ids) == 0


def _build_session_payload(
    session_id: str,
    meta: Dict[str, Any],
    state,  # MindMapState
) -> Dict[str, Any]:
    """Build a single session's analysis payload.

    Extracts key nodes (friction/spark/action) and maps each node's
    turn_id to the raw conversation from state.history.
    """
    nodes = state.nodes
    history = state.history
    is_zero_based = _detect_zero_based(nodes)

    # Collect candidate nodes, then cap per session
    type_priority = {"action": 0, "friction": 1, "spark": 2}
    candidates = [n for n in nodes.values() if n.type in KEY_NODE_TYPES]
    candidates.sort(key=lambda n: type_priority.get(n.type, 99))
    candidates = candidates[:MAX_KEY_NODES_PER_SESSION]

    key_nodes = []
    for node in candidates:
        turn_id = node.original_context.turn_id
        raw_context = _extract_raw_context(history, turn_id, is_zero_based)

        key_nodes.append({
            "id": node.id,
            "type": node.type,
            "label": node.label,
            "rich_summary": node.rich_summary,
            "raw_context": raw_context,
        })

    return {
        "session_id": session_id,
        "meta": {
            "title": meta.get("title", "Untitled"),
            "created_at": meta.get("created_at", ""),
            "themes": meta.get("themes", []),
            "emotions": meta.get("emotions", []),
            "summary": meta.get("summary", ""),
        },
        "key_nodes": key_nodes,
    }


def load_sessions_for_analysis(user_id: str) -> List[Dict[str, Any]]:
    """Load all sessions for a user and build analysis payloads.

    Returns a list of session payloads sorted by created_at (ascending).
    Temporal order is critical for causal/evolution pattern detection.
    """
    sessions_meta = list_sessions(user_id)
    if not sessions_meta:
        return []

    # Sort by created_at ascending (oldest first)
    sessions_meta.sort(key=lambda m: m.get("created_at", ""))

    payloads = []
    for meta in sessions_meta:
        sid = meta["session_id"]
        session_data = load_session(user_id, sid)
        if not session_data:
            print(f"[session_loader] Warning: could not load session {sid}, skipping")
            continue

        payload = _build_session_payload(
            session_id=sid,
            meta=session_data["meta"],
            state=session_data["state"],
        )

        # Skip sessions with no key nodes
        if not payload["key_nodes"]:
            continue

        payloads.append(payload)

    print(f"[session_loader] Loaded {len(payloads)} sessions with key nodes for user '{user_id}'")
    return payloads


def load_cached_analysis(user_id: str) -> Optional[Dict[str, Any]]:
    """Load cached analysis result if it exists."""
    analysis_file = _get_user_dir(user_id) / "analysis.json"
    if not analysis_file.exists():
        return None
    with open(analysis_file, "r", encoding="utf-8") as f:
        return json.load(f)


def save_analysis_cache(
    user_id: str,
    session_hash: str,
    session_count: int,
    result: Dict[str, Any],
) -> None:
    """Save analysis result to cache file."""
    from datetime import datetime

    analysis_file = _get_user_dir(user_id) / "analysis.json"
    cache_data = {
        "analyzed_at": datetime.now().isoformat(),
        "session_hash": session_hash,
        "session_count": session_count,
        "result": result,
    }
    with open(analysis_file, "w", encoding="utf-8") as f:
        json.dump(cache_data, f, ensure_ascii=False, indent=2)

    print(f"[session_loader] Analysis cached for user '{user_id}' ({session_count} sessions)")


def check_analysis_status(user_id: str) -> Dict[str, Any]:
    """Check if cached analysis is up-to-date.

    Returns: {status: "synced"|"stale"|"none", analyzed_at, session_count}
    """
    sessions_meta = list_sessions(user_id)
    current_hash = compute_session_hash(sessions_meta)

    cached = load_cached_analysis(user_id)
    if cached is None:
        return {
            "status": "none",
            "analyzed_at": None,
            "session_count": len(sessions_meta),
            "current_hash": current_hash,
        }

    if cached.get("session_hash") == current_hash:
        return {
            "status": "synced",
            "analyzed_at": cached.get("analyzed_at"),
            "session_count": len(sessions_meta),
            "current_hash": current_hash,
        }

    return {
        "status": "stale",
        "analyzed_at": cached.get("analyzed_at"),
        "session_count": len(sessions_meta),
        "current_hash": current_hash,
    }
