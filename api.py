from fastapi import FastAPI
from pydantic import BaseModel

from cappuccino_agent import CappuccinoAgent
from tool_manager import ToolManager

app = FastAPI()

class UserRequest(BaseModel):
    query: str

async def default_llm(messages):
    raise NotImplementedError("LLM not configured")

@app.post("/agent/run")
async def run_agent(request: UserRequest):
    agent = CappuccinoAgent(llm=default_llm, tool_manager=ToolManager())
    result = await agent.run(request.query)
    return {"result": result}
