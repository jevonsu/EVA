# Eva

> **独立项目路径：** `C:\Users\jevonsu\Documents\eva`  
> 由 AgentOS 干净剥离而来，与 `AgentOS V6.0.1` 并列于 Documents，后续单独开发。

AgentOS 干净发行包：仅系统 builtin + 受保护 skill，**无设备集成数据、无业务 skill、无密钥**。

## 能力边界

### Builtin 工具（`app/tools/builtin.py`，LLM **不能**改/删这些工具本身）

| 工具 | 作用 |
|------|------|
| `create_tool` | **创建 / 更新**业务 skill（`update=true` 就地覆盖） |
| `read_skill` | 读取 skill 源码（更新前建议先读） |
| `delete_tool` | **删除**可变业务 skill |
| `integrations` | 读写集成配置（host/密码/Token 等，禁止写进 skill 代码） |
| `workspace` / `memory` / `kb` / `workflow` | 工作区、记忆、知识库、工作流 |
| `get_current_time` / `calculator` / `system_info` | 基础工具 |

**有完整的创建、更新、编辑、删除业务工具的能力**，它们是 builtin 系统工具，不是 `skills/` 下的业务 skill 包。

推荐流程：

1. `create_tool(name=..., description=..., handler_code=...)` → 新建  
2. `read_skill(name=...)` → `create_tool(name=同一名字, update=true, ...)` → 更新/编辑  
3. `delete_tool(name=...)` → 删除  

不可对 builtin 自身及受保护 skill 做 create/update/delete。

### 受保护 skill（`skills/`，LLM 不可 update/delete）

- `reload_runtime`
- `list_api_models`
- `server_health_check`

### 已清空

- `data/config.json` → `integrations: {}`，`llms: []`，人设名 Eva  
- `.env` → 无 Key、无设备集成项  
- 无业务 skill（nas/http/office/…）  
- 无会话/记忆/任务/知识库正文  

## 发卡系统与登录（高防）

整站默认启用 **卡密登录门禁**（`AUTH_ENABLED=true`）。

| 入口 | 地址 | 说明 |
|------|------|------|
| **用户登录** | `/login` | 输入卡密，写入 HttpOnly 会话 Cookie |
| **发卡平台** | `/admin` | 管理员批量制卡、吊销、审计 |
| **对话前台** | `/` | 需有效卡密会话 |

### 安全能力

- 卡密 **高熵**（`EVA-XXXX-…`），库中仅存 **HMAC 查找键 + bcrypt**，明文只在发卡时显示一次  
- 会话 Token **随机 32 字节**，库中只存 HMAC；Cookie：`HttpOnly` + `SameSite=Strict`  
- 登录 **滑动窗口限流** + 失败 **指数退避锁定**  
- 蜜罐字段拦截简单机器人  
- 安全响应头：`X-Frame-Options: DENY`、`nosniff`、`Referrer-Policy: no-referrer`  
- 管理端与用户端 **独立 Cookie**；吊销卡片会踢掉该卡全部会话  
- 单卡可限制 **最大同时在线设备数**

### 配置（`.env`）

```env
AUTH_ENABLED=true
AUTH_PEPPER=请改为长随机串
AUTH_SESSION_DAYS=7
AUTH_COOKIE_SECURE=false
AUTH_ADMIN_USER=admin
AUTH_ADMIN_PASSWORD=change-me-now
# 生产建议：
# AUTH_ADMIN_PASSWORD_HASH=$2b$12$...
```

生成 pepper / bcrypt 示例：

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "from app.auth.security import hash_secret; print(hash_secret('你的强密码'))"
```

### 使用流程

1. 启动服务后打开 `http://127.0.0.1:8080/admin`  
2. 使用 `AUTH_ADMIN_USER` / `AUTH_ADMIN_PASSWORD` 登录  
3. 批量生成卡密（**立即复制**，只显示一次）  
4. 用户打开 `/login` 粘贴卡密进入 `/`  

数据文件：`data/auth/auth.db`（SQLite）。

## 启动

```bash
cd C:\Users\jevonsu\Documents\eva

python -m venv .venv

# Windows PowerShell
.\.venv\Scripts\Activate.ps1

# Linux / macOS
# source .venv/bin/activate

pip install -U pip
pip install -r requirements.txt

# 编辑 .env：LLM_* 与 AUTH_ADMIN_PASSWORD / AUTH_PEPPER
python run.py
```

默认：http://127.0.0.1:8080/  
登录：http://127.0.0.1:8080/login  
发卡：http://127.0.0.1:8080/admin

## 与 AgentOS 的关系

| | AgentOS V6.0.1 | Eva |
|--|----------------|-----|
| 路径 | `Documents\AgentOS V6.0.1` | `Documents\eva` |
| 定位 | 完整现网实例 | 干净底座，后续独立演进 |
| 端口默认 | 80（可改） | 8080 |
| Git | 视原仓库而定 | 已 `git init`（独立仓库） |

部署细节可参考原 AgentOS 仓库 README 的 Windows / Linux 章节。
