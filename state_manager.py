import json
import logging
from typing import Any, Dict, List, Optional

import aiosqlite

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

class StateManager:
    """Persist and manage agent state asynchronously."""

    def __init__(self, db_path: str = "agent_state.db"):
        self.db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None

    async def _get_connection(self) -> aiosqlite.Connection:
        if self._conn is None:
            self._conn = await aiosqlite.connect(self.db_path)
            await self._initialize()
        return self._conn

    async def _initialize(self) -> None:
        conn = await self._get_connection()
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS agent_state (
                    key TEXT PRIMARY KEY,
                    value TEXT
            )"""
        )
        await conn.commit()

    async def save_plan(self, plan: List[Dict[str, Any]], current_step: int = 0) -> None:
        """Persist plan and current step."""
        conn = await self._get_connection()
        await conn.execute(
            "REPLACE INTO agent_state (key, value) VALUES (?, ?)",
            ("task_plan", json.dumps(plan)),
        )
        await conn.execute(
            "REPLACE INTO agent_state (key, value) VALUES (?, ?)",
            ("current_step", str(current_step)),
        )
        await conn.commit()
        logging.info("Agent state saved asynchronously.")

    async def load_plan(self) -> Dict[str, Any]:
        """Load plan and current step."""
        conn = await self._get_connection()
        cursor = await conn.execute("SELECT key, value FROM agent_state")
        rows = await cursor.fetchall()
        state = {row[0]: row[1] for row in rows}
        plan = json.loads(state.get("task_plan", "[]"))
        current_step = int(state.get("current_step", "0"))
        logging.info("Agent state loaded asynchronously.")
        return {"task_plan": plan, "current_step": current_step}

    async def update_step(self, step: int) -> None:
        """Update the current step."""
        conn = await self._get_connection()
        await conn.execute(
            "REPLACE INTO agent_state (key, value) VALUES (?, ?)",
            ("current_step", str(step)),
        )
        await conn.commit()
