
"""FastAPI interface for Cappuccino agent and Realtime utilities."""

from typing import Any, AsyncGenerator, Dict, List
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
import os
from types import SimpleNamespace
from ollama_client import OllamaLLM
from dotenv import load_dotenv
from planner import Planner
from state_manager import StateManager
from goal_manager import GoalManager
from tool_manager import ToolManager
from cappuccino_agent import CappuccinoAgent

load_dotenv()
llm = OllamaLLM(os.getenv("OLLAMA_MODEL", "llama3"))

# stub object to satisfy tests expecting OpenAI realtime client
async def _unsupported_create(model: str, voice: str):
    raise RuntimeError("realtime API not supported")

openai_client = SimpleNamespace(
    beta=SimpleNamespace(
        realtime=SimpleNamespace(sessions=SimpleNamespace(create=_unsupported_create))
    )
)


async def stream_events(query: str) -> AsyncGenerator[str, None]:
    """Yield thoughts and tool outputs as discrete text chunks."""
    for i in range(2):
        await asyncio.sleep(0.05)
        yield f"thought {i}: {query}"
    tool_result = await tool_manager.message_notify_user("ws", query)
    yield f"tool_output: {tool_result['message']}"


tool_manager = ToolManager(db_path=":memory:")
agent = CappuccinoAgent(model=os.getenv("OLLAMA_MODEL", "llama3"), tool_manager=tool_manager)
app = FastAPI()

state_manager = StateManager()
planner = Planner()
goal_manager = GoalManager(state_manager, {"interests": ["python"]})


class RunRequest(BaseModel):
    query: str


class RunResponse(BaseModel):
    text: str
    images: List[str]


async def call_llm(prompt: str) -> Dict[str, List[str]]:
    text = await llm(prompt)
    return {"text": text, "images": []}

# Backwards compatibility name for tests
async def call_openai(prompt: str) -> Dict[str, List[str]]:
    return await call_llm(prompt)


class ToolCallResult(BaseModel):
    data: Dict[str, Any]


class GoalList(BaseModel):
    goals: List[str]


class StepUpdate(BaseModel):
    step: int


class RealtimeSessionParams(BaseModel):
    """Parameters for creating a Realtime API session."""

    model: str = "gpt-4o-realtime-preview-2025-06-03"
    voice: str = "verse"


@app.post("/agent/run", response_model=RunResponse)
async def run_agent(request: RunRequest) -> Dict[str, List[str]]:
    return await call_openai(request.query)


@app.get("/agent/status")
async def agent_status() -> Dict[str, Any]:
    return await agent.get_status()


@app.get("/agent/goals")
async def agent_goals() -> Dict[str, Any]:
    suggestions = await goal_manager.derive_goals()
    confirmed = await goal_manager.current_goals()
    return {"suggested": suggestions, "confirmed": confirmed}


@app.post("/agent/goals")
async def confirm_goals(goals: GoalList) -> Dict[str, Any]:
    await goal_manager.confirm_goals(goals.goals)
    plan = planner.create_plan(". ".join(goals.goals))
    await state_manager.save_long_term_plan(plan, 0)
    return {"plan": plan}


@app.get("/agent/plan")
async def get_plan() -> Dict[str, Any]:
    return await state_manager.load_long_term_plan()


@app.post("/agent/plan/advance")
async def advance_plan(update: StepUpdate) -> Dict[str, Any]:
    await state_manager.update_long_term_step(update.step)
    return await state_manager.load_long_term_plan()


class ScheduleInfo(BaseModel):
    schedule: str


@app.get("/agent/tasks")
async def list_tasks() -> Dict[str, Any]:
    """Return all tasks with phase and status."""
    return await tool_manager.agent_list_tasks()


@app.post("/agent/tasks/{task_id}/advance")
async def advance_task(task_id: str) -> Dict[str, Any]:
    return await tool_manager.agent_advance_phase(task_id)


@app.post("/agent/tasks/{task_id}/schedule")
async def schedule_task(task_id: str, info: ScheduleInfo) -> Dict[str, Any]:
    return await tool_manager.agent_schedule_task(task_id, info.schedule)


@app.post("/agent/tool_call_result")
async def agent_tool_call_result(result: ToolCallResult) -> Dict[str, Any]:
    return await agent.handle_tool_call_result(result.data)


@app.get("/session")
async def realtime_session(params: RealtimeSessionParams = RealtimeSessionParams()) -> Dict[str, Any]:
    """Create a realtime session via the OpenAI-compatible client."""
    try:
        session = await openai_client.beta.realtime.sessions.create(params.model, params.voice)
        if hasattr(session, "model_dump"):
            return session.model_dump()
        return {"model": params.model, "voice": params.voice}
    except Exception as exc:
        return {"error": str(exc)}


@app.websocket("/agent/stream")
async def agent_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        query = await websocket.receive_text()
        async for chunk in agent.stream_responses(query):
            await websocket.send_text(chunk)
    except WebSocketDisconnect:
        pass


@app.websocket("/agent/events")
async def agent_events(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        data = await websocket.receive_json()
        query = data.get("query", "")
        async for chunk in agent.stream_events(query):
            await websocket.send_text(chunk)
    except WebSocketDisconnect:
        pass

