import asyncio
from pathlib import Path
import sys

SOURCE = Path(sys.argv[1])
sys.path.insert(0, str(SOURCE))

from jinja2 import Environment


async def reject_z(values):
    for value in values:
        if value != "z":
            yield value


async def run() -> None:
    env = Environment(enable_async=True)
    env.filters["reject_z"] = reject_z
    template = env.from_string("{{ items|reject_z|unique|list }}")
    result = await template.render_async(items=["a", "b", "c", "c", "a", "d", "z"])
    assert result == "['a', 'b', 'c', 'd']"

    unchanged = await env.from_string("{{ items|unique|list }}").render_async(
        items=["a", "a", "b"]
    )
    assert unchanged == "['a', 'b']"


if __name__ == "__main__":
    asyncio.run(run())
