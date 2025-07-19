import sys
from pathlib import Path

import asyncio
import os
import aiohttp
import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))
from tool_manager import ToolManager

@pytest.mark.asyncio
async def test_service_expose_port(tmp_path):
    (tmp_path / "index.txt").write_text("hello")
    async with ToolManager(db_path=os.path.join(tmp_path, "db.sqlite")) as tm:
        result = await tm.service_expose_port(0, str(tmp_path))
        port = result["port"]
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://localhost:{port}/index.txt") as resp:
                text = await resp.text()
        assert text == "hello"
    assert tm.service_processes == {}
