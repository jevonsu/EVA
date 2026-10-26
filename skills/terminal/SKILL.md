# 受控终端

系统技能。在 **workspace**（默认）或 **Eva 项目根** 执行本机命令，不是完整管理员 shell。

**怎么喊：** 执行命令、pip 安装、跑脚本、终端、npm、git clone。

**何时用：** 装 Python 包、跑工作区里的脚本、git、npm、看命令输出。

**不要用：** 读写工作区文件（用 `workspace`）；HTTP/业务 API（用对应技能或集成）；格式化磁盘、关机、改注册表。

## 动作

| action | 行为 | token |
|---|---|---|
| `run` | 等到结束再返回（默认 90s，最长 300s） | 等待期间不耗 token；返回后再打一轮模型 |
| `bg` | 立刻返回 `job_id` | 推荐给 pip/npm/clone |
| `poll` | 看后台日志尾部 | 每次 poll 才打一轮 |
| `kill` | 结束后台任务 | |
| `pwd` | 允许的目录与 venv python | |

`pip` / `python` 会改写到 Eva 的 `.venv`。检测到 `pip install` / `npm install` / `git clone` 时，`run` 会自动改成 `bg`。

日志：`data/terminal_jobs/<id>.log`。
