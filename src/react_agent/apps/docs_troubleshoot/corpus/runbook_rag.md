# Runbook：RAG 无命中与离线 CI

- 确认语料已 ingest；空库会提示文档库为空
- 离线 CI / 评测优先配置 `REACT_AGENT_RAG_MODE=keyword`
- 语义检索需 `pip install -e ".[rag]"`；失败应回退关键词
