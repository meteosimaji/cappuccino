
import aiosqlite
import json
from typing import Any, Dict, List, Optional

class StateManager:
    """Persist and restore Cappuccino agent state using SQLite."""
    def __init__(self, db_path: str = "agent_state.db") -> None:
        self.db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None

    async def _get_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            self._conn = await aiosqlite.connect(self.db_path)
            await self._conn.execute(
                """CREATE TABLE IF NOT EXISTS agent_state (
                        key TEXT PRIMARY KEY,
                        value TEXT
                )"""
            )
            await self._conn.commit()
        return self._conn

    async def load(self) -> Dict[str, Any]:
        conn = await self._get_conn()
        async with conn.execute("SELECT key, value FROM agent_state") as cur:
            rows = await cur.fetchall()
        data = {k: v for k, v in rows}
        task_plan = json.loads(data.get("task_plan", "[]"))
        history = json.loads(data.get("history", "[]"))
        phase = int(data.get("phase", "0"))
        return {"task_plan": task_plan, "history": history, "phase": phase}

    async def save(self, task_plan: List[Dict[str, Any]], history: List[Dict[str, Any]], phase: int) -> None:
        conn = await self._get_conn()
        await conn.execute(
            "REPLACE INTO agent_state (key, value) VALUES (?, ?)",
            ("task_plan", json.dumps(task_plan)),
        )
        await conn.execute(
            "REPLACE INTO agent_state (key, value) VALUES (?, ?)",
            ("history", json.dumps(history)),
        )
        await conn.execute(
            "REPLACE INTO agent_state (key, value) VALUES (?, ?)",
            ("phase", str(phase)),
        )
        await conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None


    # Planner convenience methods
    async def save_plan(self, task_plan: List[Dict[str, Any]], current_step: int = 0) -> None:
        """Persist a task plan and current step."""
        data = await self.load()
        history = data.get("history", [])
        await self.save(task_plan, history, current_step)

    async def load_plan(self) -> Dict[str, Any]:
        """Load just the task plan and current step."""
        data = await self.load()
        return {"task_plan": data.get("task_plan", []), "current_step": data.get("phase", 0)}

    async def update_step(self, step: int) -> None:
        """Update the current step while preserving plan and history."""
        data = await self.load()
        await self.save(data.get("task_plan", []), data.get("history", []), step)
