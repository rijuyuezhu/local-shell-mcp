# 故障排查

## 连接器只显示 `search` 和 `fetch`

常见原因：

- 未启用 ChatGPT Developer Mode。
- 当前客户端是普通 connector 或只支持只读工具的 Deep Research 类客户端。
- 服务端工具列表变化后未刷新连接器。

启用 Developer Mode 后重新刷新连接器，才能看到完整 coding-agent 工具面。

## OAuth 审批失败

检查：

```env
LOCAL_SHELL_MCP_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=...
```

连接器 URL 必须精确为：

```text
https://your-public-host.example.com/mcp
```

公开 base URL 只填写 origin，不附加 `/mcp`。

## 公开 URL 无法访问

先检查本地健康端点：

```bash
curl -i http://127.0.0.1:8765/healthz
```

再检查 tunnel 或 reverse proxy：

- 应转发到服务端口，通常为 `8765`。
- ChatGPT 访问的外部连接必须保持 HTTPS。
- 公网 hostname 必须与 `LOCAL_SHELL_MCP_BASE_URL` 一致。

## 容器无法写入状态目录

若容器不能写 `/workspace/.local-shell-mcp`，检查宿主机挂载 workspace 的 owner：

```bash
mkdir -p workspaces/default/agent/workspace
stat -c '%u:%g %n' workspaces/default/agent/workspace
```

Docker entrypoint 通常按该 owner 创建运行时 `agent` 用户。owner 不符合预期时，先修复宿主机权限，或在 `.env` 中设置 `DOCKER_AGENT_UID` 和 `DOCKER_AGENT_GID`，然后重启：

```bash
docker compose restart local-shell-mcp
```

## 工具调用超时

公开工具调用受 watchdog 与 shell timeout 限制。检查：

```env
LOCAL_SHELL_MCP_TOOL_TIMEOUT_S=60
LOCAL_SHELL_MCP_RUN_SHELL_DEFAULT_TIMEOUT_S=10
LOCAL_SHELL_MCP_RUN_SHELL_MAX_TIMEOUT_S=60
```

长时间 dev server、REPL 或交互命令应使用持久化 shell；长时间非交互任务可使用 `bash(async_=true)` 与 `job`。

## 远程 worker 无法连接

检查：

- invite 尚未过期且未被使用。
- 远端机器可通过 outbound HTTPS 访问公开 control server。
- control server 设置 `LOCAL_SHELL_MCP_REMOTE_ENABLED=true`。
- 粘贴命令包含正确的 `--server`、`--invite`、`--name` 和 `--workdir`。
- worker 状态目录可写，且 Python 3.14 或 `uv` provisioning 可用。

然后让 MCP 客户端执行：

```text
Use local-shell-mcp `remote_admin(action="list", args={})`.
```

worker 在线但远程 Skill 不出现时，确认 Skill 位于该远程 session workdir 的 `.agents/skills/<name>/SKILL.md`，并将同一个 `session_id` 传给 `list_agent_skills`、`activate_agent_skill` 和 `read_agent_skill_file`。

## Skill 来源不符合预期

`list_agent_skills` 会返回每个 Skill 的 `source` 和 `source_path`。优先级为：

1. 当前 project/session 的 `.agents/skills`
2. managed `agent_config/<skills.directory>`
3. global `$XDG_CONFIG_HOME/agents/skills` 或 `~/.config/agents/skills`

同名 Skill 由第一个有效来源获胜。查看 `warnings` 可确认低优先级 duplicate、缺少 `SKILL.md`、预算截断或不安全路径。相对 `XDG_CONFIG_HOME` 会被忽略并回退到 `~/.config`。

## OpenTUI 无法启动

先确认 HTTP 服务运行：

```bash
curl -i http://127.0.0.1:8765/healthz
local-shell-mcp tui --help
```

OpenTUI runtime 按自定义 `ui_tui_command`、相邻/PATH sidecar、release runtime、可选 embedded payload、Bun 源码模式依次查找。源码 checkout 可执行：

```bash
cd ui-opentui
bun install --frozen-lockfile
bun run build:tui
```

`--api-base` 必须是无凭据的 loopback HTTP(S) URL，并以 `/api/ui` 结尾。OAuth 公网 URL 不能直接作为 native TUI API base；应连接本机服务或使用受信任的本地转发。

## 审计日志缺少预期调用

每个已路由 MCP/REST debug tool 调用通常会产生 `tool_call_start` 和 `tool_call_end`。检查：

- connector 实际连接的是当前服务实例。
- tail 的路径与配置状态目录一致。
- 状态目录可写。
- 请求没有在路由前被认证、body limit 或其他 middleware 拒绝。

被路由前拒绝的请求可能使用独立审计事件，而不会产生工具调用对。

## Release 二进制缺少系统工具

standalone binary 包含 Python 服务与默认 OAuth 依赖，但不会打包 Git、tmux、shell、编译器或 LibreOffice；这些来自宿主系统。release archive 还包含对应平台的 `local-shell-mcp-tui` sidecar。Docker 镜像提供最小 Ubuntu runtime，包括 Git、SSH client、ripgrep 和 tmux，并使用 `uv` 安装 Python 依赖。