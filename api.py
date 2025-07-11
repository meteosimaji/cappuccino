
"""FastAPI interface for Cappuccino agent."""

from typing import Any, AsyncGenerator, Dict
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from tool_manager import ToolManager


class CappuccinoAgent:
    """Minimal asynchronous CappuccinoAgent stub."""

    def __init__(self, tool_manager: ToolManager) -> None:
        self._status = "idle"
        self.tool_manager = tool_manager

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

    async def stream_events(self, query: str) -> AsyncGenerator[str, None]:
        """Yield thoughts and tool outputs as discrete text chunks."""
        self._status = "streaming"
        for i in range(2):
            await asyncio.sleep(0.05)
            yield f"thought {i}: {query}"
        tool_result = await self.tool_manager.message_notify_user("ws", query)
        yield f"tool_output: {tool_result['message']}"
        self._status = "completed"


tool_manager = ToolManager(db_path=":memory:")
agent = CappuccinoAgent(tool_manager)
app = FastAPI()


class RunRequest(BaseModel):
    query: str


class ToolCallResult(BaseModel):
    data: Dict[str, Any]


@app.post("/agent/run")
async def run_agent(request: RunRequest) -> Dict[str, Any]:
    result = await agent.run(request.query)
    return {"result": result}


@app.get("/agent/status")
async def agent_status() -> Dict[str, Any]:
    return await agent.get_status()


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

