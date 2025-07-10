import sys, pathlib; sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
import asyncio
import os
import pytest
from tool_manager import ToolManager

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
async def test_media_generation(tmp_path):
    tm = ToolManager(db_path=os.path.join(tmp_path, "db.sqlite"))
    img = tmp_path / "img.png"
    speech = tmp_path / "speech.wav"
    await tm.media_generate_image("hi", str(img))
    await tm.media_generate_speech("hi", str(speech))
    assert img.exists() and speech.exists()


@pytest.mark.asyncio
async def test_browser_navigate_and_view():
    tm = ToolManager(db_path=":memory:")
    tmpdir = pathlib.Path.cwd()
    index = tmpdir / "index.html"
    await asyncio.to_thread(index.write_text, "<html><body>Example</body></html>")
    server = await tm.service_expose_port(0, directory=str(tmpdir))
    url = f"http://127.0.0.1:{server['port']}/index.html"
    result = await tm.browser_navigate(url)
    assert result.get("status") == "success"
    view = await tm.browser_view()
    assert "Example" in view.get("preview", "")
    tm.service_processes[server['port']].shutdown()


@pytest.mark.asyncio
async def test_service_expose_port():
    tm = ToolManager(db_path=":memory:")
    tmpdir = pathlib.Path.cwd() / "svc"
    tmpdir.mkdir(exist_ok=True)
    await asyncio.to_thread((tmpdir / "index.html").write_text, "ok")
    res = await tm.service_expose_port(0, directory=str(tmpdir))
    port = res["port"]
    assert res["status"] == "running"
    assert port in tm.service_processes
    tm.service_processes[port].shutdown()

