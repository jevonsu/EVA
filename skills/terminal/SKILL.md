# 受控终端

系统技能。在 **workspace**（默认）或 **Eva 项目根** 执行本机命令，不是完整管理员 shell。

**怎么喊：** 执行命令、pip 安装、跑脚本、终端、npm、git clone。

**何时用：** 装 Python 包、跑工作区里的脚本、git、npm、看命令输出。

**不要用：** 读写工作区文件（用 `workspace`）；HTTP/业务 API（用对应技能或集成）；格式化磁盘、关机、改注册表。

## 动作

| action | 行为 | token |
|---|---|---|
| `run` | 一次性执行，等到结束再返回（默认 90s，最长 300s）。超时 / 用户停止对话 / EVA 关闭时结束**整棵进程树**。服务器、`tail -f`、watch 等常驻命令直接拒绝 | 等待期间不耗 token；返回后再打一轮模型 |
| `bg` | 会结束的后台任务，立刻返回 `job_id` | 推荐给 pip/npm/clone |
| `poll` | 看后台日志尾部 | 每次 poll 才打一轮 |
| `kill` | 结束后台任务（先核对 pid 身份，再杀整棵树） | |
| `pwd` | 允许的目录与 venv python | |
| `service` | **用户明确要求**的常驻服务（web/dev server、端口服务）。脱离 EVA 运行，输出写 `data/services/<id>.log`；停止对话、超时、删会话、重启 EVA 都不结束 | 最多 5 个；启动前检查端口 |
| `services` | 列出服务；带 `service_id` 看该服务日志尾部 | |
| `stop_service` | 结束服务。只有用户本轮明确说停止/关闭时才调用，且 `confirm=true`；否则返回 `need_confirm` | |

进程分类：① `run`、技能 HTTP、CLI 模型调用 = EVA 内部执行，必须结束；② `service` = 受保护服务，只有用户明确停止才结束；③ `bg` = 有限后台任务。
定时任务 / 工作流 / Webhook 路径禁止 `service` 与 `stop_service`。登记表：`data/services.json`（EVA 启动时按 pid+创建时间重新接管，只改状态不杀进程）。
Docker 部署：容器内 EVA 是 PID 1，重启 EVA = 重启容器，容器内服务必然随之结束。

`pip` / `python` 会改写到 Eva 的 `.venv`。检测到 `pip install` / `npm install` / `git clone` 时，`run` 会自动改成 `bg`。

日志：`data/terminal_jobs/<id>.log`。

## 安全边界（受保护，不可卸载 / 覆盖）

黑名单在 `app/services/terminal_exec.py` 的 `_DENY`，命中即拒绝，不执行。覆盖：

- 磁盘/系统：format、diskpart、bcdedit、shutdown/Restart-Computer、vssadmin/wbadmin 删卷影、cipher /w
- 注册表/账户/计划任务：reg delete、reg add HKLM、net user/localgroup、schtasks /create、提权 runas
- 递归删根：`rm -rf /`、`rd|del|Remove-Item … /s|-Recurse` 指向盘符根、`%SystemRoot%`、`$env:windir`、`~`
- 编码/间接执行：`powershell|pwsh(.exe)` 的 `-e/-ec/-enc/-EncodedCommand`（含完整路径与缩写）、`iex`/Invoke-Expression、`[scriptblock]::Create`、Invoke-Command -ScriptBlock、FromBase64String、DownloadString、`certutil -decode/-urlcache`
- LOLBin：mshta、regsvr32、rundll32、wscript、cscript、bitsadmin
- 管道执行：`… | iex|sh|bash|cmd|powershell`，`curl|wget|iwr|irm … |`
- `python -c` 内含 base64 / exec( / os.system / subprocess
- Defender/防火墙：Set/Add-MpPreference、netsh advfirewall

**边界说明：** 黑名单是“拦常见误用与明显绕过”，不是沙箱；正则无法穷尽所有混淆。真正的边界仍是：cwd 限定在 workspace / Eva 根、超时、后台任务可 kill。需要更高权限的操作请让用户自己在终端执行。

## 记忆 / 知识门禁

本技能不写 memory/知识库；若调用方写入，进暂存而非金叶。
