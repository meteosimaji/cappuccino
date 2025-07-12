
"""FastAPI interface for Cappuccino agent."""

from typing import Any, AsyncGenerator, Dict
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from cappuccino_agent import CappuccinoAgent


agent = CappuccinoAgent()
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

