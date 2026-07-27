"""ReAct Agent — 生产向运行时原型（可服务化 / 可回归；非多租户平台）。

Core：``react_loop`` + 工具 + harness + ToolGuard + 权限闸门。
主场景：``REACT_AGENT_APP=docs_troubleshoot``（文档/API 排障）。
框架对照：``experiments/langgraph``（可选 ``[langgraph]``）。
成熟度：``docs/PRODUCTION_MATURITY.md``。
"""
