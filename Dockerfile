# syntax=docker/dockerfile:1
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    REACT_AGENT_HOST=0.0.0.0 \
    REACT_AGENT_PORT=8765 \
    REACT_AGENT_APP=docs_troubleshoot \
    REACT_AGENT_RAG_MODE=keyword \
    REACT_AGENT_DISABLE_MCP=1

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY schemas ./schemas

RUN pip install --no-cache-dir -e .

EXPOSE 8765

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/ready', timeout=2)"

CMD ["react-agent-server", "--host", "0.0.0.0", "--port", "8765"]
