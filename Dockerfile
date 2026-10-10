# syntax=docker/dockerfile:1
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    REACT_AGENT_HOST=0.0.0.0 \
    REACT_AGENT_PORT=8765 \
    REACT_AGENT_DEFAULT_APP=docs_troubleshoot \
    REACT_AGENT_RAG_MODE=keyword \
    REACT_AGENT_DISABLE_MCP=1 \
    REACT_AGENT_DATA_DIR=/app/data

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY schemas ./schemas

ARG REACT_AGENT_INSTALL_EXTRAS=""
ARG REACT_AGENT_TORCH_VERSION="2.7.1+cpu"
# 默认装 [service]：镜像里因此同时具备 stdlib 服务面与 FastAPI 入口点
# （react-agent-api）。REACT_AGENT_INSTALL_EXTRAS 可追加 rag 等；
# rag 走 PyTorch CPU 源，避免在 slim 镜像里拉入 CUDA 版 torch。
RUN if [ "$REACT_AGENT_INSTALL_EXTRAS" = "rag" ]; then \
      pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu "torch==${REACT_AGENT_TORCH_VERSION}"; \
    fi; \
    pip install --no-cache-dir -e ".[service]"; \
    if [ -n "$REACT_AGENT_INSTALL_EXTRAS" ] && [ "$REACT_AGENT_INSTALL_EXTRAS" != "service" ]; then \
      pip install --no-cache-dir -e ".[${REACT_AGENT_INSTALL_EXTRAS}]"; \
    fi \
    && mkdir -p /app/data

# Mutable runtime data (approvals / trajectories / reports) lives in a volume.
# Without a writable approval dir the async approval gate fails CLOSED.
VOLUME ["/app/data"]

EXPOSE 8765

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/ready', timeout=2)"

# 默认服务面：FastAPI（react-agent-api；端口与 REACT_AGENT_HOST/PORT 由默认值
# 0.0.0.0:8765 提供）。stdlib 入口在镜像内仍可用，覆盖 CMD 即可切换：
#   docker run ... react-agent:ci react-agent-server --host 0.0.0.0 --port 8765
CMD ["react-agent-api"]
