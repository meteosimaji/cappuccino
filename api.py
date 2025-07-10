
"""FastAPI interface for Cappuccino agent."""

from typing import Any, AsyncGenerator, Dict
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel


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


class RunRequest(BaseModel):
    query: str


class ToolCallResult(BaseModel):
    data: Dict[str, Any]


@app.post("/agent/run")
async def run_agent(request: RunRequest) -> Dict[str, Any]:
    return await agent.run(request.query)


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

