FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    REACT_AGENT_HOST=0.0.0.0 \
    REACT_AGENT_PORT=8765 \
    REACT_AGENT_DEFAULT_APP=docs_troubleshoot \
    REACT_AGENT_RAG_MODE=keyword \
    REACT_AGENT_DISABLE_MCP=1

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY schemas ./schemas

ARG REACT_AGENT_INSTALL_EXTRAS=""
ARG REACT_AGENT_TORCH_VERSION="2.7.1+cpu"
RUN if [ "$REACT_AGENT_INSTALL_EXTRAS" = "rag" ]; then \
      pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu "torch==${REACT_AGENT_TORCH_VERSION}"; \
    fi; \
    pip install --no-cache-dir -e ".[service]"; \
    if [ -n "$REACT_AGENT_INSTALL_EXTRAS" ] && [ "$REACT_AGENT_INSTALL_EXTRAS" != "service" ]; then \
      pip install --no-cache-dir -e ".[${REACT_AGENT_INSTALL_EXTRAS}]"; \
    fi

EXPOSE 8765

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/ready', timeout=2)"

# FastAPI/Uvicorn is the default service surface.  The stdlib server remains
# available through `react-agent-server` for minimal/offline compatibility.
CMD ["react-agent-api"]
