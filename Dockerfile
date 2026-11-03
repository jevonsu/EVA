# Eva — container image (CLI / server only; no Windows launcher / tray)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    EVA_DEPLOY=docker \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOST=0.0.0.0 \
    PORT=8080

WORKDIR /app

# python:3.12-slim 自带 CA 证书；跳过 apt，避免飞牛等国内网络构建卡住

COPY requirements.txt .

# pystray is Windows tray-only; skip so Linux slim builds stay lean and reliable
RUN grep -iv '^[[:space:]]*pystray' requirements.txt > /tmp/requirements.docker.txt \
    && pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com -r /tmp/requirements.docker.txt \
    && rm -f /tmp/requirements.docker.txt

COPY . .

EXPOSE 8080

# --host overrides .env HOST=127.0.0.1 so the service is reachable via published ports
CMD ["python", "run.py", "--cli", "--host", "0.0.0.0", "--port", "8080", "--no-browser"]
