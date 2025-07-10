import sys, pathlib; sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
import asyncio
import os
import logging
import pytest
from tool_manager import ToolManager, ToolExecutionError

@pytest.mark.asyncio
async def test_file_read_and_append(tmp_path):
    tm = ToolManager(db_path=os.path.join(tmp_path, "db.sqlite"))
    file_path = tmp_path / "sample.txt"
    await asyncio.to_thread(file_path.write_text, "hello\n")
    result = await tm.file_read(str(file_path))
    assert "content" in result and result["content"] == "hello\n"
    await tm.file_append_text(str(file_path), "world\n")
    result = await tm.file_read(str(file_path))
    assert result["content"] == "hello\nworld\n"

@pytest.mark.asyncio
async def test_shell_exec_and_wait():
    tm = ToolManager(db_path=":memory:")
    session_id = "test"
    await tm.shell_exec("echo hello", session_id)
    result = await tm.shell_wait(session_id)
    assert result["returncode"] == 0
    assert "hello" in result["stdout"]


@pytest.mark.asyncio
async def test_file_read_not_found(tmp_path):
    tm = ToolManager(db_path=os.path.join(tmp_path, "db.sqlite"))
    with pytest.raises(FileNotFoundError):
        await tm.file_read(str(tmp_path / "missing.txt"))


@pytest.mark.asyncio
async def test_shell_wait_no_session(caplog):
    tm = ToolManager(db_path=":memory:")
    with caplog.at_level(logging.ERROR):
        with pytest.raises(ToolExecutionError):
            await tm.shell_wait("bad")
    assert any("shell_wait" in r.getMessage() for r in caplog.records)

