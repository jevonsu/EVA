# Eva

Ruyi Studio 出品的本地 **AI 助手**（v0.1.0）。

对话、多模型、工具 / 技能、长期记忆、知识库、定时任务、工作流与 MCP。使用前需 **卡密登录**（卡密由管理员在 CardServer 发卡台发放）。

---

## 功能概览

| 能力 | 说明 |
|------|------|
| 对话 | 多会话、工具调用、流式 / 完整模式 |
| LLM | 预置 DeepSeek；也可添加其它 OpenAI 兼容接口（xAI、Ollama 等） |
| 工具 / 技能 | 内置工具 + `skills/` 技能包；可在对话中创建 / 更新业务技能 |
| 记忆 | 长期偏好与规则注入 |
| 知识库 | Wiki 式页面：检索、读写、版本 |
| 任务 | 定时 / 手动任务调度 |
| 工作流 | 可编排多步流程 |
| MCP | 连接外部 MCP Server，扩展工具 |
| 鉴权 | CardServer 卡密 + 本机安装绑定；同一目录再启动不用重输卡密 |

界面：`http://127.0.0.1:<端口>/` 或 `http://<本机IP>:<端口>/`（需登录）  
登录：`http://127.0.0.1:<端口>/login`  
健康检查：`http://127.0.0.1:<端口>/health`  

默认 `HOST=0.0.0.0`，局域网用 **http://本机IP:端口** 打开（不要用 https）。若打不开，检查 Windows 防火墙是否放行该端口入站。仅本机访问时把 `.env` 改成 `HOST=127.0.0.1`。

---

## 环境要求

- **Python 3.11+**（推荐 3.11 / 3.12）
- 可访问的 **LLM API**（OpenAI 兼容）
- 管理员提供的 **鉴权网关地址**、**控制密钥**（与 CardServer 相同）和 **卡密**

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

项目里只有一份 **`.env`**，启动时直接读取。按需改网关与 `AUTH_CONTROL_KEY`。  
LLM **不要**写在 `.env`：预置 DeepSeek，登录后在 **设定 → LLM** 填写 API Key。

### 3. 启动

Windows 默认打开 **Eva 启动窗口**（启动 / 停止、改端口、看状态和日志），不再弹出独立终端。

```bash
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

### 4. 发布到私有 GitHub / 旧版升级

默认仓库：`jevonsu/EVA`（私有）。**不会自动上传。**

```powershell
python scripts\publish_github.py                 # 只预览：文件、版本、不会推送
.\publish-github.bat --publish                   # PowerShell 必须加 .\
python scripts\publish_github.py --publish       # 交互输入 YES 后才 commit / tag / push / Release
```

资源管理器里可双击 `publish-github.bat`。PowerShell 里不要直接打文件名，要用 `.\publish-github.bat`。  
`.env`、`data/`（会话、卡密、数据库、设定）、`workspace/`、`.venv` 不会进仓库，旧目录升级时也不会被覆盖。

旧版检查更新：启动器「检查 / 更新」，或网页 **设定 → 更新**。私有仓库需要本机 git 凭据，或在该页填写 Token / 环境变量 `GITHUB_TOKEN`。

---

## 鉴权

| 场景 | 行为 |
|------|------|
| 该目录第一次使用 | 登录页填写网关 + 卡密 |
| 同一目录再启动（可换端口） | 校验本机会话，**不用重输卡密**，没有注销按钮 |
| 复制整个文件夹再开 | 视为新安装，须重新鉴权。原卡已被占用时，发卡台先 **解绑设备/项目** |
| CardServer 吊销该卡 | 约十几秒内本机失效；重启后必须重新登录，原卡密无法再登 |

会话存在本目录 `data/auth/`（加密会话文件 + 安装 ID），**不用 Cookie**。  
发卡网关与控制密钥由**发卡方**写在发给客户的 `.env` 里（`AUTH_CONTROL_URL` + `AUTH_CONTROL_KEY`）。客户登录页只填卡密。

---

## 环境变量（`.env`）

```env
# —— 服务 ——
HOST=0.0.0.0           # 本机 + 局域网；仅本机改 127.0.0.1
PORT=8080              # 仅首次建议端口；选定后记在 data/launch.json
DEBUG=false            # 交付关闭。true 或 --debug：终端详细日志 + 访问记录
CORS_ORIGINS=*

AGENT_NAME=Eva
DATA_DIR=./data
MCP_SERVERS=

# —— 卡密鉴权 ——
AUTH_ENABLED=true
AUTH_CONTROL_URL=              # 空=登录页手填。部署后写 http://CardServer主机:8090
AUTH_CONTROL_URLS=             # 可选多网关：公司内网=http://10.x.x.x,外出公网=http://公网:端口
AUTH_CONTROL_KEY=      # 必须与 CardServer 相同；空则登录页必填，否则网关 403
AUTH_NODE_ID=eva
AUTH_SESSION_DAYS=7
AUTH_COOKIE_SECURE=false
```

- **DEBUG**：交付保持 `false`（终端只有启动摘要）。开发观察请求 / 鉴权时改 `true`。
- **LLM**：预置 DeepSeek（`deepseek-flash`），API Key 为空。登录后在 **设定 → LLM** 填写 Key，写入 `data/config.json`。
- 403：检查 `AUTH_CONTROL_KEY` 是否与**当前发卡台**一致。CardServer 部署到服务器后，以服务器管理台「控制密钥」为准，本机旧密钥通常对不上。Eva `.env` 为空时登录页必须填写。

---

## 目录结构

```
eva/
├── run.py                 # 入口
├── requirements.txt
├── pyproject.toml
├── .env                   # 唯一配置文件
├── app/
├── skills/
├── data/                  # 运行时数据（本机）
└── workspace/
```

### `data/` 目录

| 路径 | 用途 |
|------|------|
| `launch.json` | 记住的监听端口 |
| `config.json` | 人设 / LLM / 工具 / 集成（含密钥，不进业务库） |
| `storage.json` | 存储后端配置 |
| `eva.db` | 默认业务库（会话 / 记忆 / 知识库 / 任务 / 工作流） |
| `auth/` | 本机安装 ID、加密会话、登录网关记忆 |
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
| `create_tool` | 创建 / 更新业务 skill（`update=true` 就地覆盖） |
| `read_skill` | 读取 skill 源码 |
| `delete_tool` | 删除业务 skill |
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

业务技能可放在 `skills/<id>/`，或通过对话创建后写入 `workspace/skills/`（草稿）再晋升到 `skills/`。

设定 → **Skills**：导出 / 导入 `.evaskill` 技能包，卸载业务技能。系统技能（`reload_runtime` 等）不能卸载。员工包默认只带系统技能，业务包按需导入。

---

## 使用提示

1. 第一次启动选端口，登录页填 **网关 + 卡密**。  
2. 登录后在 **设定** 中配置 LLM、人设与需要的 MCP。  
3. 同一目录以后再开，直接进入，不必重输卡密。  
4. 复制项目到新目录再开，须重新鉴权；发卡台可能要先解绑。  
5. 吊销卡密后，本机很快不能继续用。  
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
