"""支持 `python -m react_agent.server` 的命令行入口。

Service installations use FastAPI/Uvicorn by default.  A core-only install
still falls back to the stdlib server so the lightweight runtime remains usable.
"""
try:
    from react_agent.server.fastapi_app import main
except ImportError:
    from react_agent.server.app import main

if __name__ == "__main__":
    main()
