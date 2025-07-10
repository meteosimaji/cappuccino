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
