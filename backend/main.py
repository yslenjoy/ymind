"""
YMind Backend - FastAPI Entry Point

Exposes endpoints for chat and mind map visualization.
"""
import os
import asyncio
from typing import Dict, Any, List, Optional, Set
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from backend.models.node import GraphNode
from backend.models.state import MindMapState
from backend.workflows.mindmap_workflow import compile_workflow, _generate_session_title
from backend.services.chat_generator import generate_chat_response, QuotaExceededError, ChatGenerationError
from backend.services.state_updater import create_root_node
from backend.services import session_storage
from backend.services.session_loader import (
    load_sessions_for_analysis,
    compute_session_hash,
    check_analysis_status,
    load_cached_analysis,
    save_analysis_cache,
)
from backend.services.audio_transcriber import transcribe_audio
from backend.agents.summary_agent import extract_session_summary
from backend.agents.cross_session_agent import analyze_cross_sessions

# Load .env.local
load_dotenv(".env.local")

API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))


# In-memory storage for active conversations
# Key: conversation_id, Value: MindMapState
conversations: Dict[str, MindMapState] = {}

# Track conversations currently extracting (for polling status)
extracting_conversations: Set[str] = set()

# Global workflow instance
workflow = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan manager: initialize workflow on startup."""
    global workflow
    workflow = compile_workflow()
    yield
    # Cleanup if needed


app = FastAPI(
    title="YMind API",
    description="Dynamic Mind Map Visualization for Multi-turn Conversations",
    lifespan=lifespan
)

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all for dev; restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request/Response Models
class ChatRequest(BaseModel):
    conversation_id: str = Field(default="default", description="Conversation identifier")
    user_input: str = Field(..., description="User message")
    ai_response: Optional[str] = Field(None, description="AI response (if available)")


class MindMapResponse(BaseModel):
    """Response format for mind map visualization."""
    nodes: List[Dict[str, Any]]
    links: List[Dict[str, Any]]
    active_node_id: str
    turn_count: int


class ChatResponse(BaseModel):
    mindmap: MindMapResponse
    routing_decision: Optional[Dict[str, Any]] = None


class LiveChatRequest(BaseModel):
    """Request for real-time AI chat."""
    conversation_id: str = Field(default="default", description="Conversation identifier")
    user_input: str = Field(..., description="User message")


class LiveChatResponse(BaseModel):
    """Response with AI reply and updated mindmap."""
    ai_response: str
    mindmap: MindMapResponse
    history: List[Dict[str, str]] = Field(default_factory=list)
    extracting: bool = Field(default=False, description="Whether graph extraction is in progress")


def state_to_mindmap(state: MindMapState) -> MindMapResponse:
    """Convert MindMapState to visualization format."""
    nodes = []
    links = []

    # Convert nodes to frontend format
    for node in state.nodes.values():
        nodes.append({
            "id": node.id,
            "label": node.label,
            "type": node.type,
            "rich_summary": node.rich_summary,
            "source": node.source,
            "status": node.status,
            "parent_id": node.parent_id,
            "turn_id": node.original_context.turn_id if node.original_context else None
        })

        # Create structural links (parent -> children)
        for child_id in node.children_ids:
            links.append({
                "source": node.id,
                "target": child_id,
                "relation_type": "parent"
            })

        # Create semantic links (relations: causes, resolves, leads_to, opposes)
        if node.relations:
            for rel in node.relations:
                links.append({
                    "source": node.id,
                    "target": rel.target_id,
                    "relation_type": rel.relation_type
                })

    return MindMapResponse(
        nodes=nodes,
        links=links,
        active_node_id=state.active_node_id,
        turn_count=state.turn_count
    )


# Endpoints
@app.get("/")
async def root():
    return {"message": "YMind API is running"}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, http_req: Request):
    """
    Process a chat message and update the mind map.

    Returns updated mind map structure.
    """
    global workflow

    if workflow is None:
        raise HTTPException(status_code=503, detail="Workflow not initialized")

    conv_id = request.conversation_id

    # Get or create conversation state
    if conv_id not in conversations:
        # Initialize with empty state (will create root node in workflow)
        initial_state: Dict[str, Any] = {
            "nodes": {},
            "root_id": "",
            "active_node_id": "",
            "current_input": request.user_input,
            "current_ai_response": request.ai_response,
            "history": [],
            "turn_count": 0,
            "temp_decision": None,
            "temp_new_node": None,
            "temp_parent_id": None
        }
    else:
        existing_state = conversations[conv_id]
        initial_state: Dict[str, Any] = {
            "nodes": {k: v.model_dump() for k, v in existing_state.nodes.items()},
            "root_id": existing_state.root_id,
            "active_node_id": existing_state.active_node_id,
            "current_input": request.user_input,
            "current_ai_response": request.ai_response,
            "history": existing_state.history,
            "turn_count": existing_state.turn_count,
            "temp_decision": None,
            "temp_new_node": None,
            "temp_parent_id": None
        }

    try:
        # Run workflow
        # Inject API key into state for agents
        result = workflow.invoke(initial_state)

        # Convert result back to MindMapState
        updated_nodes = {}
        for node_id, node_data in result.get("nodes", {}).items():
            if isinstance(node_data, dict):
                updated_nodes[node_id] = GraphNode(**node_data)
            else:
                updated_nodes[node_id] = node_data

        updated_state = MindMapState(
            nodes=updated_nodes,
            root_id=result.get("root_id", ""),
            active_node_id=result.get("active_node_id", ""),
            current_input=request.user_input,
            current_ai_response=request.ai_response,
            history=result.get("history", []),
            turn_count=result.get("turn_count", 0),
            temp_decision=result.get("temp_decision"),
            temp_new_node=result.get("temp_new_node")
        )

        # Store updated state
        conversations[conv_id] = updated_state

        # Prepare response
        mindmap = state_to_mindmap(updated_state)
        routing_decision = None
        if updated_state.temp_decision:
            routing_decision = updated_state.temp_decision.model_dump()

        return ChatResponse(
            mindmap=mindmap,
            routing_decision=routing_decision
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class MindMapStatusResponse(BaseModel):
    """Response with mindmap and extraction status."""
    mindmap: MindMapResponse
    extracting: bool = False


@app.get("/mindmap/{conversation_id}", response_model=MindMapStatusResponse)
async def get_mindmap(conversation_id: str):
    """Get current mind map state for a conversation."""
    is_extracting = conversation_id in extracting_conversations

    if conversation_id not in conversations:
        # Return empty mindmap if extracting, otherwise 404
        if is_extracting:
            return MindMapStatusResponse(
                mindmap=MindMapResponse(nodes=[], links=[], active_node_id="", turn_count=0),
                extracting=True
            )
        raise HTTPException(status_code=404, detail="Conversation not found")

    state = conversations[conversation_id]
    return MindMapStatusResponse(
        mindmap=state_to_mindmap(state),
        extracting=is_extracting
    )


def run_extraction_sync(
    conv_id: str,
    user_input: str,
    ai_response: str,
    initial_state: Dict[str, Any]
):
    """
    Run workflow extraction synchronously (called from background task).
    Updates conversations dict when complete.
    """
    import time
    global workflow, extracting_conversations

    # Delay to avoid rate limiting (chat API just finished)
    # Free tier needs longer delay to avoid 503 overload
    time.sleep(5)

    try:
        result = workflow.invoke(initial_state)

        # Convert result back to MindMapState
        updated_nodes = {}
        for node_id, node_data in result.get("nodes", {}).items():
            if isinstance(node_data, dict):
                updated_nodes[node_id] = GraphNode(**node_data)
            else:
                updated_nodes[node_id] = node_data

        updated_state = MindMapState(
            nodes=updated_nodes,
            root_id=result.get("root_id", ""),
            active_node_id=result.get("active_node_id", ""),
            current_input=user_input,
            current_ai_response=ai_response,
            history=result.get("history", []),
            turn_count=result.get("turn_count", 0),
            temp_decision=result.get("temp_decision"),
            temp_new_node=result.get("temp_new_node")
        )

        # Store updated state
        conversations[conv_id] = updated_state
        print(f"[Extraction] Completed for {conv_id}, nodes: {len(updated_nodes)}")

    except Exception as e:
        print(f"[Extraction Error] {conv_id}: {str(e)}")

    finally:
        # Mark extraction as complete
        extracting_conversations.discard(conv_id)


@app.post("/api/re-extract/{conversation_id}")
async def re_extract(conversation_id: str, background_tasks: BackgroundTasks):
    """Re-run extraction for the last turn of a conversation."""
    global workflow

    if workflow is None:
        raise HTTPException(status_code=503, detail="Workflow not initialized")

    if conversation_id not in conversations:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if conversation_id in extracting_conversations:
        raise HTTPException(status_code=409, detail="Extraction already in progress")

    state = conversations[conversation_id]

    if not state.history or len(state.history) < 2:
        raise HTTPException(status_code=400, detail="No conversation turns to extract")

    # Get last user + ai messages
    user_input = state.current_input
    ai_response = state.current_ai_response or ""

    # Rebuild initial_state for re-extraction (rewind turn_count by 1)
    initial_state = {
        "nodes": {k: v.model_dump() for k, v in state.nodes.items()},
        "root_id": state.root_id,
        "active_node_id": state.active_node_id,
        "current_input": user_input,
        "current_ai_response": ai_response,
        "history": state.history[:-2],  # exclude last turn (will be re-added by updater)
        "turn_count": max(0, state.turn_count - 1),
        "temp_decision": None,
        "temp_new_node": None,
        "temp_parent_id": None,
    }

    extracting_conversations.add(conversation_id)
    background_tasks.add_task(
        run_extraction_sync,
        conversation_id,
        user_input,
        ai_response,
        initial_state,
    )

    return {"status": "extracting", "conversation_id": conversation_id}


@app.post("/api/transcribe")
async def transcribe(file: UploadFile):
    """Transcribe audio using Gemini's native audio understanding."""
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file")

    mime_type = file.content_type or "audio/webm"
    text = transcribe_audio(audio_bytes, mime_type)
    return {"text": text}


@app.post("/api/chat", response_model=LiveChatResponse)
async def live_chat(request: LiveChatRequest, background_tasks: BackgroundTasks):
    """
    Real-time AI chat with async mind map extraction.

    1. Generates AI response using Gemini (blocking)
    2. Returns AI response immediately with current mindmap
    3. Runs workflow extraction in background
    4. Frontend can poll /mindmap/{conv_id} for updates
    """
    global workflow

    if workflow is None:
        raise HTTPException(status_code=503, detail="Workflow not initialized")

    conv_id = request.conversation_id

    # Get existing state
    existing_history = []
    existing_state = None
    if conv_id in conversations:
        existing_state = conversations[conv_id]
        existing_history = existing_state.history

    # Step 1: Generate AI response (this is blocking, but usually fast)
    try:
        ai_response = generate_chat_response(
            user_input=request.user_input,
            history=existing_history
        )
    except QuotaExceededError as e:
        raise HTTPException(status_code=429, detail=str(e))
    except ChatGenerationError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI generation failed: {str(e)}")

    # Step 2: Prepare state for workflow and save interim state
    # IMPORTANT: Save interim state BEFORE background task to handle rapid successive requests
    updated_history = existing_history.copy()
    updated_history.append({"role": "user", "content": request.user_input})
    updated_history.append({"role": "ai", "content": ai_response})

    if existing_state is None:
        # New conversation: create root node immediately
        title = _generate_session_title(request.user_input)
        root_node = create_root_node(label=title)

        initial_state: Dict[str, Any] = {
            "nodes": {root_node.id: root_node.model_dump()},
            "root_id": root_node.id,
            "active_node_id": root_node.id,
            "current_input": request.user_input,
            "current_ai_response": ai_response,
            "history": [],
            "turn_count": 0,
            "temp_decision": None,
            "temp_new_node": None,
            "temp_parent_id": None
        }

        # Save interim state with root node + updated history
        interim_state = MindMapState(
            nodes={root_node.id: root_node},
            root_id=root_node.id,
            active_node_id=root_node.id,
            current_input=request.user_input,
            current_ai_response=ai_response,
            history=updated_history,
            turn_count=0
        )
        conversations[conv_id] = interim_state
    else:
        initial_state: Dict[str, Any] = {
            "nodes": {k: v.model_dump() for k, v in existing_state.nodes.items()},
            "root_id": existing_state.root_id,
            "active_node_id": existing_state.active_node_id,
            "current_input": request.user_input,
            "current_ai_response": ai_response,
            "history": existing_state.history,
            "turn_count": existing_state.turn_count,
            "temp_decision": None,
            "temp_new_node": None,
            "temp_parent_id": None
        }

        # Update interim state with new history (nodes will be updated by background task)
        interim_state = existing_state.model_copy(
            update={
                "current_input": request.user_input,
                "current_ai_response": ai_response,
                "history": updated_history
            }
        )
        conversations[conv_id] = interim_state

    # Step 3: Mark as extracting and schedule background task
    extracting_conversations.add(conv_id)
    background_tasks.add_task(
        run_extraction_sync,
        conv_id,
        request.user_input,
        ai_response,
        initial_state
    )

    # Step 4: Return immediately with AI response + current mindmap
    mindmap = state_to_mindmap(interim_state)

    return LiveChatResponse(
        ai_response=ai_response,
        mindmap=mindmap,
        history=updated_history,
        extracting=True  # Frontend should poll for updates
    )


@app.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    """Delete a conversation and its mind map."""
    if conversation_id in conversations:
        del conversations[conversation_id]
    return {"message": "Conversation deleted"}


# ============================================================
# Session Persistence Endpoints
# ============================================================

class SaveSessionRequest(BaseModel):
    """Request to save current session."""
    user_id: str = Field(default="default", description="User identifier")
    conversation_id: str = Field(..., description="Conversation to save")


class KeyNodeInfo(BaseModel):
    """Lightweight node info for Mind Universe satellites."""
    id: str
    type: str
    label: str
    summary: str = ""


class SessionMeta(BaseModel):
    """Session metadata for listing."""
    session_id: str
    title: str
    created_at: str
    updated_at: str
    turn_count: int
    node_count: int
    filename: str
    tags: List[str] = []
    summary: str = ""
    themes: List[str] = []
    emotions: List[str] = []
    key_labels: List[str] = []
    key_nodes: List[KeyNodeInfo] = []


@app.get("/sessions", response_model=List[SessionMeta])
async def list_sessions(user_id: str = "default"):
    """List all saved sessions for a user."""
    return session_storage.list_sessions(user_id)


@app.get("/sessions/{session_id}")
async def get_session(session_id: str, user_id: str = "default"):
    """Load a saved session."""
    result = session_storage.load_session(user_id, session_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Also load into memory for continued use
    conversations[session_id] = result["state"]

    return {
        "meta": result["meta"],
        "mindmap": state_to_mindmap(result["state"]),
        "history": result["state"].history
    }


@app.post("/sessions/save", response_model=SessionMeta)
async def save_session(request: SaveSessionRequest):
    """Save current conversation to persistent storage."""
    conv_id = request.conversation_id

    if conv_id not in conversations:
        raise HTTPException(status_code=404, detail="Conversation not found in memory")

    state = conversations[conv_id]

    # Extract title/themes/emotions/summary using Summary Agent
    nodes_list = [
        {
            "type": node.type,
            "label": node.label,
            "rich_summary": node.rich_summary,
        }
        for node in state.nodes.values()
    ]

    summary_result = extract_session_summary(
        history=state.history,
        nodes=nodes_list,
    )

    # Use LLM title if available, fall back to truncated first message
    title = summary_result.get("title")
    if not title and state.history:
        first_user_msg = next(
            (m["content"] for m in state.history if m["role"] == "user"),
            None
        )
        if first_user_msg:
            title = _generate_session_title(first_user_msg)

    # Extract key nodes (max 7, by type priority)
    # TODO: Replace with LLM-based extraction that picks the most
    #       important/representative nodes based on full conversation context.
    #       Current approach: simple type-priority sort (action > friction > spark > fact).
    type_priority = {"action": 0, "friction": 1, "spark": 2}
    candidate_nodes = [
        n for n in state.nodes.values()
        if n.type in type_priority
    ]
    candidate_nodes.sort(key=lambda n: type_priority.get(n.type, 99))
    top_nodes = candidate_nodes[:7]
    key_labels = [n.label for n in top_nodes]
    key_nodes = [{"id": n.id, "type": n.type, "label": n.label, "summary": n.rich_summary or ""} for n in top_nodes]

    meta = session_storage.save_session(
        user_id=request.user_id,
        session_id=conv_id,
        state=state,
        title=title,
        themes=summary_result.get("themes", []),
        emotions=summary_result.get("emotions", []),
        summary=summary_result.get("summary", ""),
        key_labels=key_labels,
        key_nodes=key_nodes,
    )

    return meta


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str, user_id: str = "default"):
    """Delete a saved session."""
    session_storage.delete_session(user_id, session_id)
    return {"message": "Session deleted"}


# --- Cross-Session Analysis ---

@app.get("/sessions/analyze/status")
async def get_analysis_status(user_id: str = "default"):
    """Lightweight staleness check — no LLM call, returns instantly."""
    status = check_analysis_status(user_id)
    return status


@app.post("/sessions/analyze")
async def run_cross_session_analysis(user_id: str = "default"):
    """Trigger cross-session analysis. Returns cached result if up-to-date."""
    # Check cache first
    sessions_meta = session_storage.list_sessions(user_id)
    if len(sessions_meta) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 sessions for analysis")

    current_hash = compute_session_hash(sessions_meta)
    cached = load_cached_analysis(user_id)

    if cached and cached.get("session_hash") == current_hash:
        print(f"[Analyze] Cache hit for user '{user_id}'")
        return cached["result"]

    # Cache miss — run analysis
    print(f"[Analyze] Cache miss for user '{user_id}', running LLM analysis...")
    payloads = load_sessions_for_analysis(user_id)

    if len(payloads) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 sessions with key nodes")

    result = await asyncio.to_thread(analyze_cross_sessions, payloads)

    # Only cache if result has actual content (not empty default from failures)
    has_content = any(
        len(result.get(k, [])) > 0
        for k in ("session_links", "node_resonances", "recurring_patterns", "insights")
    )
    if has_content:
        save_analysis_cache(user_id, current_hash, len(sessions_meta), result)
    else:
        print(f"[Analyze] Skipping cache — analysis returned empty result (LLM may have failed)")

    return result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=API_HOST,
        port=API_PORT,
        reload=True,
        access_log=False  # Hide GET/POST logs, keep app logs (API calls, errors)
    )
