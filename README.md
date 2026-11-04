# Eva

Ruyi Studio 出品的本地 **AI 助手**：对话、多模型、工具/技能、记忆、知识库、定时任务、工作流、MCP。使用需账号密码登录。

本文是 **Windows / Linux / Docker 三平台部署说明**。安装包都在 [GitHub Releases](https://github.com/jevonsu/EVA/releases/latest)。

| 平台 | 下载哪个包 | 启动 | 更新 |
|------|-----------|------|------|
| Windows | `EVA-win-x64.zip` | 双击 `启动EVA.bat` | 前端左上角「新版本」或启动器「更新」 |
| Linux | `EVA-linux-src.tar.gz` | `./run.sh` | 前端左上角「新版本」，或 `./update.sh` |
| Docker | `EVA-docker-context.zip` | `docker compose up -d` | 换新 `app/` 后 `docker compose build && up -d` |

> 三个包都是自含的：拷一个包到目标机器就能部署，不需要本源码仓。包里已内置检查更新用的 Token，不用另外配。

---

## 一、Windows

**要求**：Windows 10/11 x64，不用装 Python。

1. 下载 `EVA-win-x64.zip`，解压到任意目录（例如 `D:\EVA`）。
2. 双击 `启动EVA.bat`（或 `EVA\EVA.exe`），打开 Eva 启动窗口。
3. 在启动窗口里选端口，点「启动」，浏览器会打开 `http://127.0.0.1:<端口>/`。
4. 第一次使用时创建管理员账号；登录后在 **设定 → LLM** 填 API Key。

- 启动窗口「选项」可勾选 **开机启动**。
- 同一台电脑可以开多份 Eva，每份用不同目录和端口。

**更新**（两种方式选一种）：
- 前端左上角 Eva 名字下方出现「新版本 vX.Y.Z」→ 点开看更新说明 → 确认更新。会自动换程序并重启。
- 启动器左侧「更新」→ 停止服务 → 点「更新」。

更新只替换 `EVA.exe` / `_internal`，`data/`、`.env`、工作区都保留。

---

## 二、Linux

**要求**：Python 3.11+（`python3 -m venv` 要能用），能访问 LLM API。

```bash
mkdir -p ~/eva && tar -xzf EVA-linux-src.tar.gz -C ~/eva
cd ~/eva/eva_linux          # 以包内实际目录为准
chmod +x run.sh update.sh
./run.sh --host 0.0.0.0 --port 8080
```

- 第一次运行会自动建 venv、装依赖，之后直接启动。
- 访问 `http://<服务器IP>:8080/`，健康检查 `/health`。
- 要常驻运行可以用包里的 `eva.service`（systemd）：改好路径后放进 `/etc/systemd/system/`，再 `systemctl enable --now eva`。

**更新**：
- 前端左上角「新版本」→ 确认更新：自动下载新源码包、覆盖并重启。
- 手动：下载新的 `EVA-linux-src.tar.gz` 解压到临时目录，执行 `./update.sh /tmp/新src`，然后重启（用 systemd 的会自动重启）。

更新保留 `data/` 和 `.env`。

---

## 三、Docker

**要求**：Docker + Compose（`docker compose version` 能出结果）。

```bash
mkdir -p ~/eva_docker && cd ~/eva_docker
unzip EVA-docker-context.zip
cp .env.example .env        # 按需修改
mkdir -p data
docker compose build
docker compose up -d
```

- 访问 `http://<主机IP>:8080/`，健康检查 `/health`；日志看 `docker compose logs -f eva`。
- `.env` 里的 `HOST` 不用改，compose 会设成 `0.0.0.0`。
- `CORS_ORIGINS` 写成实际访问地址；只用 HTTP 时 `AUTH_COOKIE_SECURE=false`。
- 停止用 `docker compose stop`；删容器用 `docker compose down`（`./data` 会保留）。

**更新**：
- 推荐：下载新的 `EVA-docker-context.zip`，覆盖本目录 `app/`（保留 `data/`、`.env`），然后 `docker compose build && docker compose up -d`。
- 前端左上角「新版本」也能在容器里更新并重启，但**重建镜像后会回到旧版**，所以要长期升级还是得用上面的方法。

---

## 通用说明

- **账号**：第一次打开时创建管理员（或在 `.env` 设 `EVA_ADMIN_USER` / `EVA_ADMIN_PASSWORD`）。账号存在 `data/auth/`，只存 bcrypt 哈希。
- **LLM**：Key 不要写进 `.env`，登录后在 **设定 → LLM** 填写，存在 `data/config.json`。
- **数据**：都在 `data/`（默认 SQLite `eva.db`）。迁移或备份时拷 `data/` 和 `.env` 就行。
- **安全**：Windows 默认只监听本机 `127.0.0.1`。Linux/Docker 对外开放时，**不要把端口直接暴露到公网**，前面加 Nginx/Caddy 并保持 `AUTH_ENABLED=true`；有反向代理时才开 `AUTH_TRUST_PROXY=true`。
- **默认关掉的危险能力**：`ALLOW_CREATE_TOOL=false`。`WEBHOOK_ALLOW_TOOLS` 默认 `true`（Webhook 可用工具），可在 .env 设为 false 关闭。

---

## 开发者（本源码仓）

- 本地运行：`python -m venv .venv` → `pip install -r requirements.txt` → `run.bat` / `python run.py`（`--cli` 是无窗口模式）。
- 打包与发布：双击 `OPC/发布程序/启动.bat`，按钮有 docker打包 / linux打包 / win打包 / 3平台发布 / 发布；产物在 `发布程序/OUT`。发布前要填版本说明。
- 刷新本机三套目录：`OPC/同步三包.ps1`。
- 技术栈：Python 3.11+ · FastAPI · Uvicorn · APScheduler · MCP · 原生前端（`app/static/`）。

© Ruyi Studio