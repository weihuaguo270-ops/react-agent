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
RUN if [ -n "$REACT_AGENT_INSTALL_EXTRAS" ]; then \
      if [ "$REACT_AGENT_INSTALL_EXTRAS" = "rag" ]; then \
        pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu "torch==${REACT_AGENT_TORCH_VERSION}"; \
      fi; \
      pip install --no-cache-dir -e ".[${REACT_AGENT_INSTALL_EXTRAS}]"; \
    else \
      pip install --no-cache-dir -e .; \
    fi

EXPOSE 8765

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/ready', timeout=2)"

CMD ["react-agent-server", "--host", "0.0.0.0", "--port", "8765"]
