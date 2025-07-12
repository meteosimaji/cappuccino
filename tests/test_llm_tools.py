import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[1]))

import pytest

from cappuccino_agent import CappuccinoAgent
from tool_manager import ToolManager, log_tool

class DummyToolManager(ToolManager):
    def __init__(self):
        super().__init__(db_path=":memory:")
        self.called = False

    @log_tool
    async def dummy_tool(self, x: int) -> dict:
        self.called = True
        return {"x": x + 1}

class DummyClient:
    def __init__(self):
        self.calls = 0
        self.chat = self.Chat(self)

    class Chat:
        def __init__(self, outer):
            self.completions = outer.Completions(outer)

    class Completions:
        def __init__(self, outer):
            self.outer = outer
        async def create(self, model, messages, tools=None):
            self.outer.calls += 1
            if self.outer.calls == 1:
                class F:
                    name = "dummy_tool"
                    arguments = "{\"x\": 3}"
                class TC:
                    id = "1"
                    function = F()
                class M:
                    content = None
                    tool_calls = [TC()]
                class R:
                    choices = [type("C", (), {"message": M()})]
                return R()
            else:
                class M:
                    content = "done"
                    tool_calls = None
                class R:
                    choices = [type("C", (), {"message": M()})]
                return R()

@pytest.mark.asyncio
async def test_call_llm_with_tools(monkeypatch):
    tm = DummyToolManager()
    agent = CappuccinoAgent(tool_manager=tm, llm=None)
    agent.client = DummyClient()
    schema = [{
        "type": "function",
        "function": {
            "name": "dummy_tool",
            "description": "dummy",
            "parameters": {
                "type": "object",
                "properties": {"x": {"type": "integer"}},
                "required": ["x"],
            },
        },
    }]
    out = await agent.call_llm_with_tools("hi", schema)
    assert out == "done"
    assert tm.called
