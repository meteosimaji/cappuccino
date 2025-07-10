from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class UserRequest(BaseModel):
    query: str

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/agent/run")
async def run_agent(request: UserRequest):
    # Placeholder for Cappuccino agent logic
    return {"response": f"Processing query: {request.query}"}

