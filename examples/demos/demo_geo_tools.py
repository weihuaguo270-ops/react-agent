"""地图/搜索工具调用示例：先查 POI，再估算路线。"""
import json

from react_agent.tools.geo import estimate_route, search_poi


def main() -> None:
    pois = json.loads(search_poi("交通", city="北京"))
    first = pois["results"][0]["name"]
    route = json.loads(estimate_route(first, "国家大剧院", mode="transit"))
    print(json.dumps({"poi": pois, "route": route}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
