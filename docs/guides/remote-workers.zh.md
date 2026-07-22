# 远程工作节点

远程 worker 让 control server 在另一台机器上运行普通的 session-bound 代码工作，同时只保留一个公开 MCP 连接器。适合 GPU 服务器、实验室机器、构建主机或远程 checkout。

## 工作方式

1. MCP 客户端在 control server 上调用 `remote_admin(action="invite", args={...})`。
2. 服务返回包含一次性 invite code 的 shell 命令。
3. 在远端机器粘贴该命令。
4. 远端下载带 digest 的 worker bundle manifest，验证并安装到持久状态目录，注册后通过 long-poll 获取任务。
5. worker 在本地保存身份，重启后继续使用同一注册；长工具调用期间独立发送 heartbeat。
6. 每次 poll 报告协议、包版本、bundle 版本和实际运行 runtime 的 digest。digest 不一致时，controller 只在 worker 空闲时要求升级。
7. 客户端先用 `remote_admin(action="list", args={})` 获取机器名，再用 `session_start(target="remote", machine=..., workdir=...)` 开始远程工作。

worker enrollment 路由必须公开，invite command 应视为短期敏感凭据。control server 将注册状态及备份存储于 `state_dir/remote-workers.json`；主文件损坏时从备份恢复，两份都无效时会拒绝继续管理，而不是静默遗忘已信任 worker。

## 要求

Control server：

- 公开的 `LOCAL_SHELL_MCP_BASE_URL` 必须能被远端机器访问。
- `LOCAL_SHELL_MCP_REMOTE_ENABLED=true`。
- OAuth 继续保护普通 MCP/REST 工具调用。

远端机器：

- 需要 `curl` 与 Python 3.14 或更高版本。缺少 Python 时，join script 可使用已有 `uv`，或临时下载 `uv` 安装器来准备 Python 3.14。
- 选择的 workdir 应已存在，或可由运行 worker 的用户创建。
- worker 状态目录默认为 `$XDG_STATE_HOME/local-shell-mcp-worker` 或 `~/.local/state/local-shell-mcp-worker`，可通过 `LOCAL_SHELL_MCP_WORKER_STATE_DIR` 覆盖。
- Git、编译器、CUDA 和包管理器等能力来自远端机器自身。

## 创建邀请

可让 MCP 客户端执行：

```text
Use local-shell-mcp to create a remote worker invite named gpu1 with workdir /home/me/project.
```

等价调用：

```json
{
  "action": "invite",
  "args": {
    "name": "gpu1",
    "workdir": "/home/me/project",
    "ttl_s": 600
  }
}
```

返回命令类似：

```bash
curl -fsSL https://your-public-host.example.com/join | bash -s -- --invite lsmcp_inv_xxxxx --name gpu1 --workdir /home/me/project
```

invite 只能使用一次，并在 TTL 后失效。

## 手动启动已安装 worker

首次 enrollment：

```bash
local-shell-mcp worker \
  --server https://your-public-host.example.com \
  --invite lsmcp_inv_xxxxx \
  --name gpu1 \
  --workdir /home/me/project
```

`--server` 填公开 origin，不附加 `/mcp`。成功 enrollment 后，可使用持久化身份恢复，不再把 invite 或 access token 放进重启命令：

```bash
local-shell-mcp worker \
  --server https://your-public-host.example.com \
  --name gpu1 \
  --workdir /home/me/project
```

## 自动 runtime 升级

Poll protocol v1 协商实际 worker bundle digest。digest 匹配时正常返回 heartbeat 或 job；不匹配时先返回强制升级指令，不会先取出任务。旧 worker 不发送版本化 payload 时保持原行为，需要用当前 join command 重启后才启用自动升级。

manifest 包含 schema version、bundle version、SHA-256、大小和带 digest 的 URL。worker 拒绝跨 origin URL、redirect、大小或 digest 不匹配及数字版本降级。bundle 是严格的 source-only allowlist，不是 controller 包的完整副本。

安装只接受有界普通文件和目录，拒绝绝对路径、`..`、重复项、符号链接、硬链接、设备文件和不完整包布局。新 runtime 先解压到临时目录，再原子替换；失败时恢复旧 runtime。POSIX 使用 process replacement，Windows 启动已验证 runtime 后退出旧进程。access token 只存在于权限受限的身份文件中。

## 验证连接

推荐流程：

1. `remote_admin(action="list", args={})`
2. `session_start(target="remote", machine="gpu1", workdir="/home/me/project")`
3. `read(session_id=..., path=".")` 或 `search(...)`
4. 优先使用 `hashline_edit`；精确范围修改使用 `edit_lines`；已有可移植 diff 时使用 `apply_patch`
5. `bash(session_id=..., command=...)` 运行命令和验证

远程 session 也可调用 `list_agent_skills`、`activate_agent_skill` 和 `read_agent_skill_file`。Skill discovery 在 worker 上执行，project 来源为该远程 session 的 workdir，control server 不会解析远端路径。

## 运行远程命令

示例：

```text
Use local-shell-mcp on remote machine gpu1. Inspect /home/me/project, run git status, then run the test command you find in the project docs. Report results before editing files.
```

长时间、非交互命令使用 `bash(session_id=..., async_=true)`，再通过 `job(session_id=..., ...)` 管理返回的 `job_id`。作业元数据、终端状态和有界输出由 worker 持久化。

## 撤销 worker

```text
Use local-shell-mcp to revoke remote machine gpu1 with `remote_admin(action="revoke", args={"machine": "gpu1"})`.
```

撤销后 worker 不再接收任务；重新连接需要新的 invite。

## 设置

| 设置 | 默认值 | 含义 |
|---|---:|---|
| `LOCAL_SHELL_MCP_REMOTE_ENABLED` | `true` | 启用 remote worker 路由和 MCP 工具 |
| `LOCAL_SHELL_MCP_REMOTE_INVITE_TTL_S` | `600` | 一次性 invite 默认寿命 |
| `LOCAL_SHELL_MCP_REMOTE_POLL_TIMEOUT_S` | `25` | long-poll 超时，也参与在线状态判断 |
| `LOCAL_SHELL_MCP_REMOTE_JOB_TIMEOUT_S` | `3600` | control 侧等待远端 job 结果的超时 |
| `LOCAL_SHELL_MCP_REMOTE_MAX_PENDING_JOBS` | `64` | 每个 worker 最大排队或执行中任务数 |

可通过 `--remote-enabled false` 或 `LOCAL_SHELL_MCP_REMOTE_ENABLED=false` 禁用远程模式。