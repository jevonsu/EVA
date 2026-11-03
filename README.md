# Eva

Ruyi Studio 出品的本地 **AI 助手**（v0.1.5）。

对话、多模型、工具 / 技能、长期记忆、知识库、定时任务、工作流与 MCP。使用前需 **账号密码登录**（首次打开创建管理员，或在 `.env` 设置 `EVA_ADMIN_USER` / `EVA_ADMIN_PASSWORD`）。

---

## 功能概览

| 能力 | 说明 |
|------|------|
| 对话 | 多会话、工具调用、流式 / 完整模式 |
| LLM | 预置 DeepSeek；也可添加其它 OpenAI 兼容接口（xAI、Ollama 等） |
| 工具 / 技能 | 内置工具 + `skills/` 技能包；业务技能请用设定 → Skills 导入 `.evaskill`（对话内热创建默认关闭） |
| 记忆 | 长期偏好与规则注入 |
| 知识库 | Wiki 式页面：检索、读写、版本 |
| 任务 | 定时 / 手动任务调度 |
| 工作流 | 可编排多步流程 |
| MCP | 连接外部 MCP Server，扩展工具 |
| 鉴权 | 本机用户名/密码（bcrypt）+ 加密会话；同一目录再启动保持登录 |

界面：`http://127.0.0.1:<端口>/`  
登录：`http://127.0.0.1:<端口>/login`  
健康检查：`http://127.0.0.1:<端口>/health`

**默认只听本机** `HOST=127.0.0.1`。**不要**改成 `0.0.0.0` 除非你明确要暴露到局域网/公网——本机会话文件在无 Cookie 时仍可被识别为已登录，打到端口的客户端约等于已登录。局域网场景请另加反向代理与鉴权，勿当作已安全交付。

---

## 环境要求

- **Python 3.11+**（推荐 3.11 / 3.12）
- 可访问的 **LLM API**（OpenAI 兼容）
- 本机管理员 **用户名** 与 **密码**（首次启动时创建；日常改名/改密在**启动器**）

---

## 安装与启动

在项目根目录执行。

### 1. 虚拟环境与依赖

**Windows（PowerShell）**

```powershell
cd path\to\eva
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

**Linux / macOS**

```bash
cd /path/to/eva
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

### 2. 配置

项目里只有一份 **`.env`**，启动时直接读取（可参考 `.env.example`）。  
LLM **不要**写在 `.env`：预置 DeepSeek，登录后在 **设定 → LLM** 填写 API Key。

发布安全相关默认：

| 变量 | 默认 | 说明 |
|------|------|------|
| `ALLOW_CREATE_TOOL` | `false` | 关闭对话内 `create_tool` 落盘热加载 |
| `WEBHOOK_ALLOW_TOOLS` | `false` | 禁止 Webhook 通道开启工具 |
| `HOST` | `127.0.0.1` | 仅本机监听 |

### 3. 启动

Windows 默认打开 **Eva 启动窗口**（启动 / 停止、改端口、登录与账号、看状态和日志）。

双击项目目录里的 **`run.bat`** 即可（不要双击 `run.py`：`.py` 常被编辑器打开）。

```bash
run.bat                       # 打开启动窗口
python run.py                 # 打开启动窗口；已勾选「开机启动」时自动运行服务
python run.py --autostart     # 强制打开即启动
python run.py --no-autostart  # 只打开窗口，等你点「启动」
python run.py --no-browser    # 启动后不打开浏览器
python run.py --debug         # 详细日志（同 DEBUG=true）
python run.py --cli           # 旧的阻塞式终端（脚本 / 无窗口环境）
```

Windows 建议用 `.venv\Scripts\python.exe run.py`（会转到 `pythonw.exe`，不留控制台）。

**端口**

- 窗口里的端口框可改；点启动后写入 `data/launch.json`。`.env` 里的 `PORT` 只是建议值。
- **以后再开同一目录**：窗口填上次端口。
- 命令行也可预填：`python run.py --port 8181`

停止：窗口里点「停止」，或关闭窗口。`--cli` 模式仍是终端 `Ctrl+C`。

启动窗口「选项」可勾选 **开机启动**：登录 Windows 后自动打开启动器并运行服务（写入当前用户「启动」文件夹）；之后手动运行 `python run.py` 也会自动启动。取消勾选后需点「启动」。可用 `--no-autostart` 只打开窗口。

同一台机器可以开多份 Eva，每份用自己的目录和端口。

### 4. 升级

启动器左侧「更新」：检查 GitHub Release 上的便携包（`EVA-update.zip`），停止服务后点「更新」。只替换 `EVA.exe` / `_internal`，不改 `data/`、工作区、`.env`。私有仓库可在「更多设定」填写 Token，或使用环境变量 `GITHUB_TOKEN`。

打包与发布在 **Eva 项目外面**：双击 `OPC/发布程序/启动.bat`（GUI「发布程序」，产物在 `发布程序/OUT`）。菜单 1 打包并发布、2 发布、3 打包；每次版本号 +1 并同步 GitHub。启动器「更新」下载 `EVA-update.zip`，不改 `data/` / `.env`。

---

## Docker 部署

面向 Linux 服务器 / 无头环境。容器只跑 CLI 服务（`run.py --cli`），**不包含** Windows 启动器、托盘与开机启动。Windows 本机仍用 `run.bat` / 启动器；**容器侧升级走镜像重建或镜像仓库 pull，不要用启动器里的在线更新 zip**。

### 准备

1. 安装 Docker 与 Compose 插件。
2. 项目根目录准备 `.env`（可从 `.env.example` 复制）。LLM Key 仍建议登录后在 **设定 → LLM** 填写。
3. 确保存在 `data/` 目录（首次可空；compose 会挂到容器内）。

### 构建与启动

```bash
cd /path/to/eva
docker compose build
docker compose up -d
```

浏览器访问：`http://<主机>:8080/`（健康检查：`/health`）。

常用：

```bash
docker compose logs -f eva   # 看日志
docker compose stop          # 停止
docker compose down          # 停止并移除容器（保留 ./data）
```

### 更新版本

数据在宿主机 `./data` 卷中，换镜像一般不丢会话与配置。

本地源码更新后：

```bash
git pull   # 或同步新版本源码
docker compose build
docker compose up -d
```

若使用镜像仓库（自行 `docker tag` / `push` 后）：

```bash
docker compose pull
docker compose up -d
```

不要依赖容器内的 `EVA.exe` / 启动器「更新」按钮。

### 安全注意

- 容器内监听 `0.0.0.0:8080` 才能映射端口；**勿把该端口裸奔到公网**。前面加 Nginx / Caddy 等反向代理，并保持 `AUTH_ENABLED=true`。
- 宿主机 `.env` 里即便写了 `HOST=127.0.0.1`，compose 也会用环境变量覆盖为 `0.0.0.0`；对外暴露时务必加反代与鉴权。
- 若反代传 `X-Forwarded-For`，可按需设 `AUTH_TRUST_PROXY=true`（仅信任的代理后开启）。
- `CORS_ORIGINS` 按实际访问域名/端口调整。
- 镜像构建时会跳过 `pystray`（仅 Windows 托盘）；SQL Server 的 `pyodbc` 默认未装，需要时自行改镜像并安装 ODBC。

可选：在 `docker-compose.yml` 取消注释 `./workspace:/app/workspace`，持久化工作区文件。

---

## 鉴权与账号

| 场景 | 行为 |
|------|------|
| 该目录第一次使用 | 登录页或启动器创建管理员用户名+密码（或 .env 种子） |
| 同一目录再启动（可换端口） | 校验本机会话，**不用重输密码** |
| 改用户名 / 改密码 | **启动器**（设定页不再管理账号） |
| 称呼 | 顶栏一体菜单可改 `display_name`；对话默认用它称呼你 |
| 注销 | 启动器或顶栏菜单；或清 `data/auth/local_session*` |

会话存在本目录 `data/auth/`（加密会话文件 + 安装 ID）。  
账号密码存在本机 `data/auth/users.json`（仅 bcrypt 哈希）。可选用 `.env` 的 `EVA_ADMIN_USER` / `EVA_ADMIN_PASSWORD` 种子首个管理员。

**本机会话语义**：无 Cookie/Bearer 时仍可能读到加密会话并视为已登录。这是本机单用户特性；一旦把 `HOST` 改成 `0.0.0.0`，任何打到该端口的客户端都可能等于已登录。

---

## 环境变量（`.env`）

```env
# —— 服务 ——
HOST=127.0.0.1         # 仅本机；勿随意改 0.0.0.0
PORT=8080              # 仅首次建议端口；选定后记在 data/launch.json
DEBUG=false            # 交付关闭。true 或 --debug：终端详细日志 + 访问记录
CORS_ORIGINS=http://127.0.0.1:8080,http://localhost:8080

AGENT_NAME=Eva
DATA_DIR=./data
MCP_SERVERS=

# —— 账号密码鉴权 ——
AUTH_ENABLED=true
# EVA_ADMIN_USER=admin
# EVA_ADMIN_PASSWORD=change-me-now
AUTH_SESSION_DAYS=7
AUTH_COOKIE_SECURE=false

# —— 发布安全（默认关闭危险能力）——
ALLOW_CREATE_TOOL=false
WEBHOOK_ALLOW_TOOLS=false
```

- **DEBUG**：交付保持 `false`（终端只有启动摘要）。开发观察请求 / 鉴权时改 `true`。
- **LLM**：预置 DeepSeek（`deepseek-flash`），API Key 为空。登录后在 **设定 → LLM** 填写 Key，写入 `data/config.json`。
- **导出**：设定导出默认脱敏；含明文密钥需管理员二次确认并记审计。账号密码不随配置导入导出。

---

## 目录结构

```
eva/
├── run.py                 # 入口
├── requirements.txt
├── pyproject.toml
├── Dockerfile             # 容器镜像
├── docker-compose.yml     # Compose 编排
├── .dockerignore
├── .env                   # 唯一配置文件
├── app/
├── skills/
├── data/                  # 运行时数据（本机 / 卷）
└── workspace/
```

### `data/` 目录

| 路径 | 用途 |
|------|------|
| `launch.json` | 记住的监听端口 |
| `config.json` | 人设 / LLM / 工具 / 集成（含密钥，不进业务库） |
| `storage.json` | 存储后端配置 |
| `eva.db` | 默认业务库（会话 / 记忆 / 知识库 / 任务 / 工作流） |
| `auth/` | 本机安装 ID、加密会话、用户哈希 |
| `workflows/definitions/` | 工作流定义 |
| `webhooks/` | Webhook 通道 |
| `tools/meta_dynamic.json` | 动态工具元数据 |
| `logs/` | 运行日志 |

业务数据默认 **SQLite**；可在 **设定 → 存储** 切换到 PostgreSQL / MySQL / MariaDB / SQL Server。

---

## 工具与技能

### 内置工具（不可被 LLM 删除）

| 工具 | 作用 |
|------|------|
| `create_tool` | 创建 / 更新业务 skill（**默认禁用**；需 `ALLOW_CREATE_TOOL=true`） |
| `read_skill` | 读取 skill 源码 |
| `delete_tool` | 删除业务 skill（随 create 开关） |
| `list_skills` / `validate_skill` / `promote_skill` | 技能列表、校验、草稿晋升 |
| `integrations` | 读写集成配置（密钥不要写进 skill） |
| `workspace` | 工作区文件操作 |
| `memory` / `kb` / `workflow` | 记忆、知识库、工作流 |
| `get_current_time` / `calculator` / `system_info` | 基础工具 |

### 受保护 skill（`skills/`，不可 update / delete）

| 技能 | 作用 |
|------|------|
| `reload_runtime` | 热重载工具 / 模型配置 |
| `list_api_models` | 列出 API 可用模型 |
| `server_health_check` | 本机健康检查 |

业务技能可放在 `skills/<id>/`，或通过设定 → Skills 导入 `.evaskill`。对话内热创建默认关闭，避免模型输出落盘并 `exec_module`。

设定 → **Skills**：导出 / 导入 `.evaskill` 技能包，卸载业务技能。系统技能（`reload_runtime` 等）不能卸载。员工包默认只带系统技能，业务包按需导入。

---

## Webhook

- 管理：设定 → Webhook；入站需 Token（恒定时间比较 + 失败限流）。
- 默认 `use_tools=false`，且 **不可**在 UI/API 打开，除非 `.env` 设 `WEBHOOK_ALLOW_TOOLS=true`。
- 即便开启工具，也会屏蔽 `create_tool` / `delete_tool` / `promote_skill` / `terminal` 等危险工具。

---

## 使用提示

1. 第一次启动选端口，登录页或启动器创建 **用户名 + 密码**。  
2. 登录后在 **设定** 中配置 LLM、人设与需要的 MCP；账号改密只在启动器。  
3. 同一目录以后再开，直接进入，不必重输密码（本机会话）。  
4. 复制项目到新目录再开，须重新鉴权。  
5. 设定导出默认脱敏；勿把含明文密钥的导出文件外传。  
6. 改代码后需重启进程。`DEBUG=true` 只增加终端日志，**不会**热重载。

---

## 技术栈

- **后端**：Python 3.11+ · FastAPI · Uvicorn · Pydantic  
- **LLM**：OpenAI 兼容 SDK（`openai`）  
- **调度**：APScheduler  
- **扩展**：MCP Client  
- **前端**：原生 HTML / CSS / JS（`app/static/`）

---

## 版权

© Ruyi Studio

<!-- 追加到 EVA/README.md 的 Docker 节 -->
> **部署入口已拆分**：本目录 `EVA` 只保留源码。分发/部署请用同级目录：
> - Windows 打包/发布：`OPC/eva_win`（`打包.bat` / `发布.bat`）
> - Linux 源码部署：`OPC/eva_linux`（`run.sh`、`update.sh`、`eva.service`）
> - Docker 部署：`OPC/eva_docker`（`docker compose build && docker compose up -d`，上下文为 `../EVA`）
>
> 若 EVA 根目录仍有旧 `Dockerfile` / `docker-compose.yml`，以 `eva_docker` 为准。
