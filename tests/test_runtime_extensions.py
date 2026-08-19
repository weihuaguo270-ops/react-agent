"""Runtime 扩展的无外部服务契约测试。"""
import json
import time

from react_agent.server.task_manager import TaskManager
from react_agent.tools.geo import estimate_route, search_poi


def test_geo_tools_return_structured_results():
    pois = json.loads(search_poi("交通"))
    assert pois["results"]
    route = json.loads(estimate_route("北京南站", "国家大剧院"))
    assert route["duration_min"] > 0
    assert route["source"] == "mock_geo_adapter"


def test_task_manager_lifecycle():
    manager = TaskManager(max_workers=1)
    record = manager.submit(lambda: {"ok": True})
    deadline = time.time() + 2
    while time.time() < deadline:
        current = manager.get(record.task_id)
        if current and current.status == "succeeded":
            break
        time.sleep(0.01)
    assert manager.get(record.task_id).public()["status"] == "succeeded"
    assert manager.get(record.task_id).public()["result"] == {"ok": True}
