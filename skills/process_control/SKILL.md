# 进程管理（process_control）

系统技能。查询本机进程，并在**告知 + 用户同意**后结束指定 PID。

## 两步流程（代码强制）

1. `action=query`（`pid` / `name` / `port` 三选一）
   - 按 PID：返回完整告知（作用、程序路径、命令行、父进程、启动时间、用户、CPU/内存、监听端口、子进程、是否 EVA 创建、结束后的影响）、确认卡片和 `confirm_token`（绑定 PID + 启动时间 + 命令行指纹 + 会话 + 本轮；5 分钟、一次性）。
   - 按名称/端口：列出全部匹配，让用户挑一个 PID，再按 PID 查询。不支持按名称批量结束。
2. 用户回答确认卡（**由服务端直接执行，模型不需要也拿不到令牌**）
   - 卡片点「同意结束…」（choice=process/tree），或卡片后紧接着回复「同意/可以/确认…」：EVA 按会话 + PID 找到令牌，直接结束并把结果回给用户；模型下一轮能在历史里看到结果，不会再问。
   - 卡片点「取消」或回复「取消/不要/算了…」：撤销该 PID 的令牌，不再追问。
   - 令牌过期 / EVA 重启后丢失 / 子进程变多：重新核对并**只重发一次**确认卡；再次过期就直接说明，不再弹卡。
   - 令牌持久化在 `data/process_kill_tokens.json`（5 分钟内重启仍有效，执行前照样核对身份）。
3. `action=kill`（`pid` + `confirm_token` + `scope`，模型路径，仍保留）
   - 必须是**下一轮**，且用户原话明确同意（同意/可以/确认…），不含否定（不要/不同意/别/取消/算了…；单个「不」字如「不错」不算否定）。
   - 执行前再次核对身份；`scope=tree` 时若子进程比告知时多，拒绝并要求重新告知。
   - 先温和结束（Windows：不带 /F 的 taskkill；Linux：SIGTERM），5 秒不退再强制；回报每个 PID 是否已退出。

## 硬拒绝

PID 0/4/1、System、Registry、smss、csrss、wininit、winlogon、services、lsass、svchost、dwm、fontdrvhost、MsMpEng 等；Linux 的 init/systemd/sshd/dockerd/containerd 等；EVA 自身及其上级进程；Grok Bot 客户端。explorer.exe 等可恢复的重要进程允许，但告知里会特别警告。

## 其它

- EVA 自己的一次性命令超时/停止、bg 任务等**自动清理不经过这里**（保持自动）。
- 登记服务（terminal action=service）被结束时，登记表同步标记 stopped；`terminal action=stop_service` 也走同一套告知+确认。
- 定时任务 / 工作流 / Webhook 路径禁止 `kill`。
- 终端里的 taskkill / Stop-Process / kill / pkill / killall 等会被拦下，提示改用本工具。
- 权限不足（其他用户/管理员进程）如实报错，不提权。
- 审计日志：`data/process_kill_audit.jsonl`（时间、PID、名称、命令行、会话、用户确认原话、结果；密钥打码）。
- 设定 → 工具里可关闭本工具（默认开启）。
