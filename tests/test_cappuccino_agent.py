import sys, pathlib; sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
import asyncio
import pytest

from cappuccino_agent import CappuccinoAgent

@pytest.mark.asyncio
async def test_detect_sentiment():
    agent = CappuccinoAgent()
    pos = await agent.detect_sentiment("I love this!")
    neg = await agent.detect_sentiment("This is awful.")
    assert pos == "positive"
    assert neg == "negative"

@pytest.mark.asyncio
async def test_generate_response():
    agent = CappuccinoAgent()
    response_pos = await agent.generate_response("Great work!")
    assert "That's great!" in response_pos
    response_neg = await agent.generate_response("I hate everything")
    assert "I'm sorry" in response_neg
