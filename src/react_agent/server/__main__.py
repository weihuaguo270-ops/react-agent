"""支持 python -m react_agent.server 的命令行入口。

已安装 [service]（FastAPI/Uvicorn）时默认使用 FastAPI 服务面；仅核心安装时装不到
fastapi，则回退到 stdlib 服务面，保证轻量运行时仍可用。
"""
try:
    from react_agent.server.fastapi_app import main
except ImportError:
    from react_agent.server.app import main

if __name__ == "__main__":
    main()
