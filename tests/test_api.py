import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient

import api


@pytest.mark.asyncio
async def test_run_endpoint(monkeypatch):
    async def fake_run(self, query):
        return "ok"

    monkeypatch.setattr(api.CappuccinoAgent, "run", fake_run)
    client = TestClient(api.app)
    resp = client.post("/agent/run", json={"query": "hello"})
    assert resp.status_code == 200
    assert resp.json()["result"] == "ok"


def test_websocket_events(monkeypatch):
    async def fake_stream(self, query):
        for i in range(2):
            yield f"thought {i}"
        yield "tool_output:done"

    monkeypatch.setattr(api.CappuccinoAgent, "stream_events", fake_stream)
    client = TestClient(api.app)
    with client.websocket_connect("/agent/events") as ws:
        ws.send_json({"query": "hi"})
        data1 = ws.receive_text()
        data2 = ws.receive_text()
        data3 = ws.receive_text()
    assert data1 == "thought 0"
    assert data3 == "tool_output:done"
