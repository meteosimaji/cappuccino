
import aiosqlite
import json
from typing import Any, Dict, List, Optional

class AgentStateManager:
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


class StateManager:
    """Persist planner state (task plan and current step)."""

    def __init__(self, db_path: str = "planner_state.db") -> None:
        self.db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None

    async def _get_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            self._conn = await aiosqlite.connect(self.db_path)
            await self._conn.execute(
                "CREATE TABLE IF NOT EXISTS planner_state (id INTEGER PRIMARY KEY, plan TEXT, step INTEGER)"
            )
            await self._conn.commit()
        return self._conn

    async def save_plan(self, plan: List[Dict[str, Any]], current_step: int = 0) -> None:
        conn = await self._get_conn()
        await conn.execute(
            "INSERT OR REPLACE INTO planner_state(id, plan, step) VALUES(1, ?, ?)",
            (json.dumps(plan), current_step),
        )
        await conn.commit()

    async def load_plan(self) -> Dict[str, Any]:
        conn = await self._get_conn()
        async with conn.execute("SELECT plan, step FROM planner_state WHERE id=1") as cur:
            row = await cur.fetchone()
        if not row:
            return {"task_plan": [], "current_step": 0}
        return {"task_plan": json.loads(row[0]), "current_step": row[1]}

    async def update_step(self, step: int) -> None:
        conn = await self._get_conn()
        await conn.execute("UPDATE planner_state SET step=? WHERE id=1", (step,))
        await conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
