"""
State Updater - Update MindMapState with new node and edges.

Handles node mounting, edge updates, and active_node_id tracking.
Supports both single node (default) and multi-node (reflection) mounting.
"""
from typing import Dict, Any, Optional, List

from backend.models.node import GraphNode, ContextSnapshot
from backend.models.state import MindMapState


def create_root_node(label: str = "Root") -> GraphNode:
    """Create initial root node for new conversation."""
    return GraphNode(
        label=label,
        type="root",
        rich_summary="Conversation root node",
        original_context=ContextSnapshot(
            raw_text="",
            pre_text=None,
            post_text=None,
            speaker_role="system",
            turn_id=0
        ),
        parent_id=None,
        children_ids=[]
    )


def mount_new_node(state: MindMapState, new_node: GraphNode, parent_id: str) -> MindMapState:
    """
    Mount new node to parent and update state.

    Returns updated MindMapState copy.
    """
    # Add new node to nodes dict
    updated_nodes = state.nodes.copy()
    updated_nodes[new_node.id] = new_node

    # Update parent's children_ids
    if parent_id in updated_nodes:
        parent = updated_nodes[parent_id]
        updated_children = parent.children_ids.copy()
        updated_children.append(new_node.id)
        updated_nodes[parent_id] = parent.model_copy(
            update={"children_ids": updated_children}
        )

    # Update history and turn count
    updated_history = state.history.copy()
    updated_history.append({"role": "user", "content": state.current_input})
    if state.current_ai_response:
        updated_history.append({"role": "ai", "content": state.current_ai_response})

    # Return updated state
    print(f"DEBUG: mount_new_node new history len: {len(updated_history)}")
    return state.model_copy(
        update={
            "nodes": updated_nodes,
            "active_node_id": new_node.id,
            "history": updated_history,
            "turn_count": state.turn_count + 1
        }
    )


def mount_multiple_nodes(
    state: MindMapState,
    new_nodes: List[GraphNode],
    parent_id: str
) -> MindMapState:
    """
    Mount multiple nodes (from reflection prompt) to parent.

    All nodes share the same parent, but may have internal relations.
    The last node becomes the active_node_id.
    """
    if not new_nodes:
        return state

    updated_nodes = state.nodes.copy()
    updated_children = []

    # Get current parent's children
    if parent_id in updated_nodes:
        parent = updated_nodes[parent_id]
        updated_children = parent.children_ids.copy()

    # Add all new nodes
    for node in new_nodes:
        updated_nodes[node.id] = node
        updated_children.append(node.id)

    # Update parent's children_ids
    if parent_id in updated_nodes:
        updated_nodes[parent_id] = updated_nodes[parent_id].model_copy(
            update={"children_ids": updated_children}
        )

    # Update history and turn count
    updated_history = state.history.copy()
    updated_history.append({"role": "user", "content": state.current_input})
    if state.current_ai_response:
        updated_history.append({"role": "ai", "content": state.current_ai_response})

    # Last node becomes active
    last_node = new_nodes[-1]

    return state.model_copy(
        update={
            "nodes": updated_nodes,
            "active_node_id": last_node.id,
            "history": updated_history,
            "turn_count": state.turn_count + 1
        }
    )


def updater_step(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    LangGraph node: Update state with new node(s).

    Supports both:
    - temp_new_node (single node from default prompt)
    - temp_new_nodes (multiple nodes from reflection prompt)

    Input: state dict with temp_new_node/temp_new_nodes and temp_parent_id
    Output: updated state dict (full MindMapState fields)
    """
    print(f"DEBUG: updater_step input history len: {len(state.get('history', []))}")
    print(f"DEBUG: updater_step input nodes count: {len(state.get('nodes', {}))}")

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
    new_nodes: Optional[List[GraphNode]] = state.get("temp_new_nodes")
    new_node: Optional[GraphNode] = state.get("temp_new_node")
    parent_id: Optional[str] = state.get("temp_parent_id")

    if not parent_id:
        raise ValueError("temp_parent_id must be set before updater_step")

    # Handle multi-node case (reflection prompt)
    if new_nodes:
        updated_state = mount_multiple_nodes(mindmap_state, new_nodes, parent_id)
        return updated_state.model_dump()

    # Handle single-node case (default prompt)
    if new_node:
        updated_state = mount_new_node(mindmap_state, new_node, parent_id)
        return updated_state.model_dump()

    # No nodes extracted (API error or empty response) - still update history
    print("[Warning] No nodes extracted, updating history only")
    updated_history = mindmap_state.history.copy()
    updated_history.append({"role": "user", "content": mindmap_state.current_input})
    if mindmap_state.current_ai_response:
        updated_history.append({"role": "ai", "content": mindmap_state.current_ai_response})

    return mindmap_state.model_copy(
        update={
            "history": updated_history,
            "turn_count": mindmap_state.turn_count + 1
        }
    ).model_dump()


__all__ = ["updater_step", "create_root_node", "mount_new_node", "mount_multiple_nodes"]
