"""支持 `python -m react_agent.server` 的命令行入口。

服务端只有 stdlib 实现（``react_agent.server.app``）：核心安装不附带
FastAPI/Uvicorn 依赖，因此这里不存在可回退的第二个入口。
"""
from react_agent.server.app import main

if __name__ == "__main__":
    main()
