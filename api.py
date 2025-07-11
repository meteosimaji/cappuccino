
"""FastAPI interface for Cappuccino agent."""

from typing import Any, AsyncGenerator, Dict, List
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from planner import Planner
from state_manager import StateManager
from goal_manager import GoalManager


class CappuccinoAgent:
    """Minimal asynchronous CappuccinoAgent stub."""

    def __init__(self) -> None:
        self._status = "idle"

    async def run(self, query: str) -> Dict[str, Any]:
        self._status = "running"
        await asyncio.sleep(0.1)  # placeholder for real work
        self._status = "completed"
        return {"response": f"Processed query: {query}"}

    async def get_status(self) -> Dict[str, Any]:
        await asyncio.sleep(0)
        return {"status": self._status}

    async def handle_tool_call_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        await asyncio.sleep(0)
        return {"ack": True, "received": result}

    async def stream_responses(self, query: str) -> AsyncGenerator[str, None]:
        self._status = "streaming"
        for i in range(3):
            await asyncio.sleep(0.1)
            yield f"chunk {i} for {query}"
        self._status = "completed"


agent = CappuccinoAgent()
app = FastAPI()

state_manager = StateManager()
planner = Planner()
goal_manager = GoalManager(state_manager, {"interests": ["python"]})


class RunRequest(BaseModel):
    query: str


class ToolCallResult(BaseModel):
    data: Dict[str, Any]


class GoalList(BaseModel):
    goals: List[str]


class StepUpdate(BaseModel):
    step: int


@app.post("/agent/run")
async def run_agent(request: RunRequest) -> Dict[str, Any]:
    result = await agent.run(request.query)
    return {"result": result}


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


@app.post("/agent/tool_call_result")
async def agent_tool_call_result(result: ToolCallResult) -> Dict[str, Any]:
    return await agent.handle_tool_call_result(result.data)


@app.websocket("/agent/stream")
async def agent_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        query = await websocket.receive_text()
        async for chunk in agent.stream_responses(query):
            await websocket.send_text(chunk)
    except WebSocketDisconnect:
        pass

