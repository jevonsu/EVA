# Eva — container image (CLI / server only; no Windows launcher / tray)
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    EVA_DEPLOY=docker \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOST=0.0.0.0 \
    PORT=8080

WORKDIR /app

# Runtime CA certs for HTTPS LLM / MCP calls
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# pystray is Windows tray-only; skip so Linux slim builds stay lean and reliable
RUN grep -iv '^[[:space:]]*pystray' requirements.txt > /tmp/requirements.docker.txt \
    && pip install --no-cache-dir -r /tmp/requirements.docker.txt \
    && rm -f /tmp/requirements.docker.txt

COPY . .

EXPOSE 8080

# --host overrides .env HOST=127.0.0.1 so the service is reachable via published ports
CMD ["python", "run.py", "--cli", "--host", "0.0.0.0", "--port", "8080", "--no-browser"]
