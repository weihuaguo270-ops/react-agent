"""地图/搜索类工具示例。

这是一个无外部依赖的适配器示例，使用固定 POI 数据演示 Agent 如何把地点检索
和路线估算编排成任务。接入真实地图服务时，只需替换函数内部的数据访问层。
"""
from __future__ import annotations

import json

_POIS = [
    {"name": "北京南站", "kind": "交通", "lat": 39.8652, "lng": 116.3786},
    {"name": "国家大剧院", "kind": "景点", "lat": 39.9037, "lng": 116.3883},
    {"name": "中关村软件园", "kind": "园区", "lat": 40.0508, "lng": 116.2956},
]


def search_poi(query: str, city: str = "北京", limit: int = 5) -> str:
    """按名称/类型检索 POI，返回稳定 JSON 以便结构化输出和回归测试。"""
    needle = (query or "").strip().lower()
    hits = [p for p in _POIS if not needle or needle in p["name"].lower() or needle in p["kind"].lower()]
    return json.dumps({"city": city, "query": query, "results": hits[: max(1, min(limit, 10))]}, ensure_ascii=False)


def estimate_route(origin: str, destination: str, mode: str = "transit") -> str:
    """返回演示路线估算；真实业务应由地图连接器提供距离和 ETA。"""
    durations = {"walk": 45, "transit": 28, "driving": 22}
    selected = mode if mode in durations else "transit"
    return json.dumps({
        "origin": origin,
        "destination": destination,
        "mode": selected,
        "duration_min": durations[selected],
        "distance_km": 12.4,
        "source": "mock_geo_adapter",
    }, ensure_ascii=False)


SEARCH_POI_DEFINITION = {
    "type": "function",
    "function": {
        "name": "search_poi",
        "description": "查询城市中的地点或地点类型，返回结构化 POI 结果",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}, "city": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 10},
        }, "required": ["query"]},
    },
}

ESTIMATE_ROUTE_DEFINITION = {
    "type": "function",
    "function": {
        "name": "estimate_route",
        "description": "估算两个地点之间的路线时间",
        "parameters": {"type": "object", "properties": {
            "origin": {"type": "string"}, "destination": {"type": "string"},
            "mode": {"type": "string", "enum": ["walk", "transit", "driving"]},
        }, "required": ["origin", "destination"]},
    },
}
