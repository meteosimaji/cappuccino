import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient

import api
from tool_manager import ToolManager
from cappuccino_agent import CappuccinoAgent


@pytest.mark.asyncio
async def test_task_endpoints(tmp_path, monkeypatch):
    db_path = tmp_path / "db.sqlite"
    tm = ToolManager(db_path=str(db_path))
    await tm.agent_update_plan("t1", "demo plan")

    monkeypatch.setattr(api, "tool_manager", tm)
    monkeypatch.setattr(api, "agent", CappuccinoAgent(tm))

    client = TestClient(api.app)

    resp = client.get("/agent/tasks")
    assert resp.status_code == 200
    tasks = resp.json()["tasks"]
    assert tasks and tasks[0]["id"] == "t1"

    resp = client.post("/agent/tasks/t1/advance")
    assert resp.status_code == 200
    assert resp.json()["phase"] == 1

    resp = client.post("/agent/tasks/t1/schedule", json={"schedule": "daily"})
    assert resp.status_code == 200
    assert resp.json()["schedule"] == "daily"

    await tm.close()
