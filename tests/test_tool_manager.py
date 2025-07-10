import sys, pathlib; sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
import asyncio
import os
import pytest
from tool_manager import ToolManager

@pytest.mark.asyncio
async def test_file_read_and_append(tmp_path):
    tm = ToolManager(db_path=os.path.join(tmp_path, "db.sqlite"), root_dir=str(tmp_path))
    file_path = tmp_path / "sample.txt"
    await asyncio.to_thread(file_path.write_text, "hello\n")
    result = await tm.file_read(str(file_path))
    assert "content" in result and result["content"] == "hello\n"
    await tm.file_append_text(str(file_path), "world\n")
    result = await tm.file_read(str(file_path))
    assert result["content"] == "hello\nworld\n"

@pytest.mark.asyncio
async def test_shell_exec_and_wait(tmp_path):
    tm = ToolManager(db_path=":memory:", root_dir=str(tmp_path))
    session_id = "test"
    await tm.shell_exec("echo hello", session_id)
    result = await tm.shell_wait(session_id)
    assert result["returncode"] == 0
    assert "hello" in result["stdout"]


@pytest.mark.asyncio
async def test_disallowed_path(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    tm = ToolManager(db_path=os.path.join(root, "db.sqlite"), root_dir=str(root))
    outside = tmp_path / "outside.txt"
    await asyncio.to_thread(outside.write_text, "secret")
    result = await tm.file_read(str(outside))
    assert "error" in result

