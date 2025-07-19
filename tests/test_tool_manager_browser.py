import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
import pytest
from tool_manager import ToolManager, BrowserHelper

class DummyBrowser(BrowserHelper):
    def __init__(self):
        super().__init__()
        self.content = "<button id='btn'>off</button>"
        self.page = type("P", (), {"content": lambda s: self.content})()

    async def start(self):
        pass

    async def navigate(self, url: str) -> str:
        return self.content

    async def click(self, selector: str) -> None:
        self.content = "<button id='btn'>on</button>"

    async def fill(self, selector: str, text: str) -> None:
        self.content = f"<input id='inp' value='{text}'/>"


@pytest.mark.asyncio
async def test_browser_navigation_and_click(monkeypatch):
    monkeypatch.setattr('tool_manager.BrowserHelper', DummyBrowser)
    tm = ToolManager(db_path=':memory:')
    await tm.browser_navigate('http://example.com')
    assert 'off' in tm.browser_content
    await tm.browser_click('#btn')
    assert 'on' in tm.browser_content



