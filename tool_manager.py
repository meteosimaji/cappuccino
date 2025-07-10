import asyncio
import os
import json
import logging
from typing import Any, Dict, Optional

import aiosqlite
from PIL import Image, ImageDraw, ImageFont
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
class ToolManager:
    """Collection of asynchronous tools for the Cappuccino agent."""

    def __init__(self, db_path: str = "agent_state.db"):
        self.db_path = db_path
        self.db_connection: Optional[aiosqlite.Connection] = None
        self.shell_sessions: Dict[str, asyncio.subprocess.Process] = {}

    async def __aenter__(self) -> "ToolManager":
        """Open the database connection when entering the context."""
        await self._get_db_connection()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        """Close the database connection on context exit."""
        await self.close()

    async def close(self) -> None:
        """Explicitly close the database connection."""
        if self.db_connection is not None:
            await self.db_connection.close()
            self.db_connection = None

    async def _get_db_connection(self) -> aiosqlite.Connection:
        if self.db_connection is None:
            self.db_connection = await aiosqlite.connect(self.db_path)
            await self._initialize_db()
        return self.db_connection

    async def _initialize_db(self) -> None:
        conn = await self._get_db_connection()
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    plan TEXT,
                    phase INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'pending',
                    schedule TEXT
            )"""
        )
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    type TEXT,
                    content TEXT
            )"""
        )
        await conn.commit()

    # ------------------------------------------------------------------
    # Agent management
    # ------------------------------------------------------------------
    async def agent_update_plan(self, task_id: str, plan: str) -> Dict[str, Any]:
        """Create or update a task plan."""
        conn = await self._get_db_connection()
        await conn.execute(
            "INSERT INTO tasks(id, plan) VALUES(?, ?) ON CONFLICT(id) DO UPDATE SET plan=excluded.plan",
            (task_id, plan),
        )
        await conn.commit()
        return {"task_id": task_id, "plan": plan}

    async def agent_advance_phase(self, task_id: str) -> Dict[str, Any]:
        """Advance task to the next phase."""
        conn = await self._get_db_connection()
        await conn.execute(
            "UPDATE tasks SET phase = phase + 1 WHERE id = ?",
            (task_id,),
        )
        await conn.commit()
        cur = await conn.execute("SELECT phase FROM tasks WHERE id = ?", (task_id,))
        row = await cur.fetchone()
        return {"task_id": task_id, "phase": row[0] if row else None}

    async def agent_end_task(self, task_id: str) -> Dict[str, Any]:
        """Mark task as completed."""
        conn = await self._get_db_connection()
        await conn.execute(
            "UPDATE tasks SET status='completed' WHERE id = ?",
            (task_id,),
        )
        await conn.commit()
        return {"task_id": task_id, "status": "completed"}

    async def agent_schedule_task(self, task_id: str, schedule: str) -> Dict[str, Any]:
        """Set schedule information for a task."""
        conn = await self._get_db_connection()
        await conn.execute(
            "UPDATE tasks SET schedule=? WHERE id = ?",
            (schedule, task_id),
        )
        await conn.commit()
        return {"task_id": task_id, "schedule": schedule}

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------
    async def message_notify_user(self, user_id: str, message: str) -> Dict[str, Any]:
        """Store a notification for the user."""
        conn = await self._get_db_connection()
        await conn.execute(
            "INSERT INTO messages(user_id, type, content) VALUES(?, 'notify', ?)",
            (user_id, message),
        )
        await conn.commit()
        return {"user_id": user_id, "message": message}

    async def message_ask_user(self, user_id: str, question: str) -> Dict[str, Any]:
        """Store a question for the user and return placeholder for response."""
        conn = await self._get_db_connection()
        await conn.execute(
            "INSERT INTO messages(user_id, type, content) VALUES(?, 'ask', ?)",
            (user_id, question),
        )
        await conn.commit()
        return {"user_id": user_id, "question": question, "status": "awaiting"}

    # ------------------------------------------------------------------
    # Shell management
    # ------------------------------------------------------------------
    async def shell_exec(self, command: str, session_id: str, working_dir: str = ".") -> Dict[str, Any]:
        """Execute a shell command asynchronously and store the session."""
        process = await asyncio.create_subprocess_shell(
            command,
            cwd=working_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE,
        )
        self.shell_sessions[session_id] = process
        return {"session_id": session_id, "status": "running"}

    async def shell_view(self, session_id: str) -> Dict[str, Any]:
        """Return current stdout and stderr for the session."""
        process = self.shell_sessions.get(session_id)
        if not process:
            return {"error": "session not found"}
        stdout = await process.stdout.read() if not process.stdout.at_eof() else b""
        stderr = await process.stderr.read() if not process.stderr.at_eof() else b""
        return {"stdout": stdout.decode(), "stderr": stderr.decode()}

    async def shell_wait(self, session_id: str) -> Dict[str, Any]:
        """Wait for the process to complete and return outputs."""
        process = self.shell_sessions.get(session_id)
        if not process:
            return {"error": "session not found"}
        stdout, stderr = await process.communicate()
        return {
            "returncode": process.returncode,
            "stdout": stdout.decode(),
            "stderr": stderr.decode(),
        }

    async def shell_input(self, session_id: str, text: str) -> Dict[str, Any]:
        """Send input to the running shell session."""
        process = self.shell_sessions.get(session_id)
        if not process or process.stdin is None:
            return {"error": "session not found"}
        process.stdin.write(text.encode())
        await process.stdin.drain()
        return {"status": "sent"}

    async def shell_kill(self, session_id: str) -> Dict[str, Any]:
        """Terminate the shell session."""
        process = self.shell_sessions.get(session_id)
        if not process:
            return {"error": "session not found"}
        process.kill()
        await process.wait()
        return {"status": "killed"}

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------
    async def file_read(self, abs_path: str, start_line: Optional[int] = None, end_line: Optional[int] = None) -> Dict[str, Any]:
        """Read a text file and optionally limit lines."""
        if not os.path.exists(abs_path):
            return {"error": "File not found"}
        content = await asyncio.to_thread(lambda: open(abs_path, "r").read())
        lines = content.splitlines(True)
        if start_line is not None or end_line is not None:
            lines = lines[start_line:end_line]
        return {"content": "".join(lines)}

    async def file_append_text(self, abs_path: str, text: str) -> Dict[str, Any]:
        """Append text to a file."""
        await asyncio.to_thread(self._append_text, abs_path, text)
        return {"status": "appended"}

    def _append_text(self, abs_path: str, text: str) -> None:
        with open(abs_path, "a") as f:
            f.write(text)

    async def file_replace_text(self, abs_path: str, old: str, new: str) -> Dict[str, Any]:
        """Replace text in a file."""
        if not os.path.exists(abs_path):
            return {"error": "File not found"}
        await asyncio.to_thread(self._replace_text, abs_path, old, new)
        return {"status": "replaced"}

    def _replace_text(self, abs_path: str, old: str, new: str) -> None:
        with open(abs_path, "r+") as f:
            content = f.read()
            content = content.replace(old, new)
            f.seek(0)
            f.write(content)
            f.truncate()
    # ------------------------------------------------------------------
    # Media generation
    # ------------------------------------------------------------------
    async def media_generate_image(self, text: str, output_path: str) -> Dict[str, Any]:
        """Generate a simple image with text."""
        def _generate() -> None:
            img = Image.new("RGB", (400, 200), color="white")
            draw = ImageDraw.Draw(img)
            draw.text((10, 90), text, fill="black")
            img.save(output_path)
        await asyncio.to_thread(_generate)
        return {"path": output_path}

    async def media_generate_speech(self, text: str, output_path: str) -> Dict[str, Any]:
        """Placeholder for speech generation."""
        return {"error": "speech generation not implemented"}

    # ------------------------------------------------------------------
    # Information search
    # ------------------------------------------------------------------
    async def info_search_web(self, query: str) -> Dict[str, Any]:
        """Search the web using DuckDuckGo and return titles and links."""
        import aiohttp
        from bs4 import BeautifulSoup

        url = "https://duckduckgo.com/html/?q=" + query
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                text = await resp.text()
        soup = BeautifulSoup(text, "html.parser")
        results = []
        for a in soup.select("a.result__a"):
            results.append({"title": a.text, "href": a.get("href")})
        return {"results": results}

    async def info_search_image(self, query: str) -> Dict[str, Any]:
        """Placeholder for image search."""
        return {"error": "image search not implemented"}

    async def info_search_api(self, url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Perform a generic API GET request."""
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                data = await resp.text()
        return {"response": data}

    # ------------------------------------------------------------------
    # Browser automation (placeholders)
    # ------------------------------------------------------------------
    async def browser_navigate(self, url: str) -> Dict[str, Any]:
        return {"error": "browser automation not implemented"}

    async def browser_view(self) -> Dict[str, Any]:
        return {"error": "browser automation not implemented"}

    async def browser_click(self, selector: str) -> Dict[str, Any]:
        return {"error": "browser automation not implemented"}

    async def browser_input(self, selector: str, text: str) -> Dict[str, Any]:
        return {"error": "browser automation not implemented"}

    async def browser_move_mouse(self, x: int, y: int) -> Dict[str, Any]:
        return {"error": "browser automation not implemented"}

    async def browser_press_key(self, key: str) -> Dict[str, Any]:
        return {"error": "browser automation not implemented"}

    async def browser_select_option(self, selector: str, option: str) -> Dict[str, Any]:
        return {"error": "browser automation not implemented"}

    async def browser_save_image(self, selector: str, output_path: str) -> Dict[str, Any]:
        return {"error": "browser automation not implemented"}

    async def browser_scroll_up(self, amount: int) -> Dict[str, Any]:
        return {"error": "browser automation not implemented"}

    async def browser_scroll_down(self, amount: int) -> Dict[str, Any]:
        return {"error": "browser automation not implemented"}

    async def browser_console_exec(self, script: str) -> Dict[str, Any]:
        return {"error": "browser automation not implemented"}

    async def browser_console_view(self) -> Dict[str, Any]:
        return {"error": "browser automation not implemented"}

    # ------------------------------------------------------------------
    # Service deployment (placeholders)
    # ------------------------------------------------------------------
    async def service_expose_port(self, port: int) -> Dict[str, Any]:
        return {"error": "service management not implemented"}

    async def service_deploy_frontend(self, source_dir: str) -> Dict[str, Any]:
        return {"error": "service management not implemented"}

    async def service_deploy_backend(self, source_dir: str) -> Dict[str, Any]:
        return {"error": "service management not implemented"}

    # ------------------------------------------------------------------
    # Slide presentation (placeholders)
    # ------------------------------------------------------------------
    async def slide_initialize(self, project_name: str) -> Dict[str, Any]:
        os.makedirs(project_name, exist_ok=True)
        return {"project": project_name}

    async def slide_present(self, project_name: str) -> Dict[str, Any]:
        return {"project": project_name, "status": "presenting"}

