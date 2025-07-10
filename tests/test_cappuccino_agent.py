
import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

import pytest
import pytest_asyncio

from cappuccino_agent import CappuccinoAgent
from tool_manager import ToolManager


@pytest.mark.asyncio
async def test_agent_runs_tool():
    async def fake_llm(messages):
        return {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {"name": "media_generate_speech", "arguments": "{\"text\": \"hi\", \"output_path\": \"out.wav\"}"}
                            }
                        ]
                    }
                }
            ]
        }

    tm = ToolManager(db_path=":memory:")
    agent = CappuccinoAgent(llm=fake_llm, tool_manager=tm)
    result = await agent.run("hi")
    assert result[0]["error"] == "speech generation not implemented"


@pytest.mark.asyncio
async def test_agent_text_response():
    async def fake_llm(messages):
        return {"choices": [{"message": {"content": "ok"}}]}

    agent = CappuccinoAgent(llm=fake_llm, tool_manager=ToolManager(db_path=":memory:"))
    result = await agent.run("hi")
    assert result == "ok"
