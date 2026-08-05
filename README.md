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

# 编辑 .env 填写 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL
python run.py
```

默认：http://127.0.0.1:8080/

## 与 AgentOS 的关系

| | AgentOS V6.0.1 | Eva |
|--|----------------|-----|
| 路径 | `Documents\AgentOS V6.0.1` | `Documents\eva` |
| 定位 | 完整现网实例 | 干净底座，后续独立演进 |
| 端口默认 | 80（可改） | 8080 |
| Git | 视原仓库而定 | 已 `git init`（独立仓库） |

部署细节可参考原 AgentOS 仓库 README 的 Windows / Linux 章节。
