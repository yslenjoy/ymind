"""
状态相关数据模型
"""
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

from .node import GraphNode


class AnalysisResult(BaseModel):
    """Unified extractor analysis output."""
    user_intent: str = Field(
        default="exploring",
        description="exploring | deepening | switching | returning"
    )
    emotional_tone: str = Field(
        default="calm",
        description="curious | confused | excited | frustrated | calm"
    )
    key_tension: Optional[str] = Field(
        None,
        description="Main tension or gap identified"
    )
    reasoning_trace: str = Field(
        default="",
        description="AI's thinking process (for display)"
    )


class MindMapState(BaseModel):
    """全局状态：LangGraph 流转的数据"""
    # 扁平化图存储 {node_id: GraphNode}
    nodes: Dict[str, GraphNode] = {}
    root_id: str

    # 核心指针
    active_node_id: str  # 当前对话聚焦的节点

    # 输入流
    current_input: str   # 当前用户输入
    current_ai_response: Optional[str] = None  # 当前 AI 回复
    history: List[Dict[str, str]] = []  # [{"role": "user", "content": "..."}, ...]
    turn_count: int = 0

    # 临时存储 (用于节点间传递数据)
    temp_analysis: Optional[Dict[str, Any]] = None  # Unified extractor analysis
    temp_new_node: Optional[GraphNode] = None       # Single node (legacy)
    temp_new_nodes: Optional[List[GraphNode]] = None  # Multiple nodes
    temp_parent_id: Optional[str] = None
    temp_reasoning: Optional[str] = None
