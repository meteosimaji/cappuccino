import asyncio
import json
from typing import Any, Dict, List, Optional

from tool_manager import ToolManager
from state_manager import AgentStateManager

class CappuccinoAgent:
    """Minimal Cappuccino agent with persistent state."""

    def __init__(self, state_manager: AgentStateManager) -> None:
        self.state_manager = state_manager
        self.tool_manager = ToolManager(db_path=state_manager.db_path)
        self.task_plan: List[Dict[str, Any]] = []
        self.history: List[Dict[str, Any]] = []
        self.phase: int = 0

    @classmethod
    async def create(cls, db_path: str = "agent_state.db") -> "CappuccinoAgent":
        sm = AgentStateManager(db_path)
        agent = cls(sm)
        state = await sm.load()
        agent.task_plan = state["task_plan"]
        agent.history = state["history"]
        agent.phase = state["phase"]
        return agent

    async def add_message(self, role: str, content: str) -> None:
        self.history.append({"role": role, "content": content})
        await self.state_manager.save(self.task_plan, self.history, self.phase)

    async def set_task_plan(self, plan: List[Dict[str, Any]]) -> None:
        self.task_plan = plan
        await self.state_manager.save(self.task_plan, self.history, self.phase)

    async def advance_phase(self) -> None:
        self.phase += 1
        await self.state_manager.save(self.task_plan, self.history, self.phase)

    async def close(self) -> None:
        await self.state_manager.close()
