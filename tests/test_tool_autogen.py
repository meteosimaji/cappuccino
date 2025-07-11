import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
import pytest
import openai
from tool_manager import ToolManager

class DummyMessage:
    def __init__(self, content):
        self.content = content

class DummyChoice:
    def __init__(self, content):
        self.message = DummyMessage(content)

class DummyResponse:
    def __init__(self, content):
        self.choices = [DummyChoice(content)]

class DummyClient:
    class chat:
        class completions:
            @staticmethod
            async def create(model, messages, temperature=0):
                return DummyResponse("async def auto_tool(x: int) -> dict:\n    return {'result': x + 1}")

@pytest.mark.asyncio
async def test_generate_tool_from_failure(monkeypatch):
    monkeypatch.setattr(openai, 'AsyncOpenAI', lambda api_key=None: DummyClient)
    tm = ToolManager(db_path=':memory:')
    res = await tm.generate_tool_from_failure('increment', 'tool missing', api_key='test')
    assert res['name'] == 'auto_tool'
    assert hasattr(tm, 'auto_tool')
    out = await getattr(tm, 'auto_tool')(1)
    assert out['result'] == 2
