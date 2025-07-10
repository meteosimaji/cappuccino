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
async def test_media_generate_speech(tmp_path, monkeypatch):
    tm = ToolManager(db_path=":memory:")
    out_file = tmp_path / "speech.mp3"

    class DummyTTS:
        def __init__(self, text):
            self.text = text

        def save(self, path):
            with open(path, "wb") as f:
                f.write(b"data")

    monkeypatch.setattr("gtts.gTTS", DummyTTS)
    result = await tm.media_generate_speech("hello", str(out_file))
    assert result["path"] == str(out_file)
    assert out_file.exists()


@pytest.mark.asyncio
async def test_info_search_image(monkeypatch):
    tm = ToolManager(db_path=":memory:")

    class MockResp:
        async def json(self):
            return {
                "results": [
                    {
                        "id": "1",
                        "alt_description": "cat",
                        "urls": {"small": "http://example.com/cat.jpg"},
                    }
                ]
            }

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

    class MockSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        def get(self, url):
            return MockResp()

    monkeypatch.setattr("aiohttp.ClientSession", lambda: MockSession())
    result = await tm.info_search_image("cat")
    assert result["results"][0]["url"] == "http://example.com/cat.jpg"


@pytest.mark.asyncio
async def test_media_analyze_video(monkeypatch):
    tm = ToolManager(db_path=":memory:")

    class DummyCap:
        def __init__(self, path):
            self.path = path

        def isOpened(self):
            return True

        def get(self, prop):
            import cv2

            if prop == cv2.CAP_PROP_FRAME_COUNT:
                return 10
            if prop == cv2.CAP_PROP_FPS:
                return 5.0
            if prop == cv2.CAP_PROP_FRAME_WIDTH:
                return 640
            if prop == cv2.CAP_PROP_FRAME_HEIGHT:
                return 480
            return 0

        def release(self):
            pass

    import cv2

    monkeypatch.setattr("cv2.VideoCapture", lambda path: DummyCap(path))
    result = await tm.media_analyze_video("dummy.mp4")
    assert result["frames"] == 10
    assert result["duration"] == 2.0

