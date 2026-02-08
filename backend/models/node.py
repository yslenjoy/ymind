"""
节点相关数据模型

扩展支持微观节点类型 (FACT/FRICTION/SPARK/ACTION) 和关系类型
"""
import uuid
from typing import List, Optional, Literal
from pydantic import BaseModel, Field


# Node type hierarchy:
# - Macro level: root, topic
# - Micro level: fact, friction, spark, action
# - Legacy: detail (backward compatible)
NodeType = Literal['root', 'topic', 'detail', 'fact', 'friction', 'spark', 'action']

# Source of the node extraction
NodeSource = Literal['user', 'ai', 'inferred']

# Lifecycle status
NodeStatus = Literal['active', 'resolved', 'discarded']

# Relation types between nodes
RelationType = Literal['parent', 'causes', 'opposes', 'resolves', 'leads_to']


class ContextSnapshot(BaseModel):
    """语境快照：自包含的原始数据 (The "Payload")"""
    raw_text: str = Field(description="触发该节点的当前核心文本")
    pre_text: Optional[str] = Field(None, description="前文铺垫 (上一句)")
    post_text: Optional[str] = Field(None, description="后文补充 (下一句)")
    speaker_role: str = Field(description="发言者角色 (user/ai)")
    turn_id: int = Field(description="对话轮次ID")


class NodeRelation(BaseModel):
    """节点间关系"""
    target_id: str = Field(description="目标节点 ID")
    relation_type: RelationType = Field(default='parent', description="关系类型")


class GraphNode(BaseModel):
    """图节点：三层信息架构 (Display, Semantic, Source)

    支持两种粒度:
    - 宏观: root, topic (多轮对话主题)
    - 微观: fact, friction, spark, action (单轮洞察提取)
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # 展示层
    label: str = Field(description="节点短标题 (e.g., Transformer优势)")
    type: NodeType = 'detail'

    # 语义层 (用于向量检索和鼠标悬停)
    rich_summary: str = Field(description="完整语义摘要")

    # 溯源层 (包含预留的原始语境)
    original_context: ContextSnapshot

    # 元数据 (微观节点扩展)
    source: NodeSource = Field(default='user', description="提取来源: user/ai/inferred")
    status: NodeStatus = Field(default='active', description="生命周期: active/resolved/discarded")

    # 拓扑结构
    children_ids: List[str] = []
    parent_id: Optional[str] = None

    # 关系 (除了父子关系外的语义关系)
    relations: List[NodeRelation] = Field(default_factory=list, description="与其他节点的语义关系")
