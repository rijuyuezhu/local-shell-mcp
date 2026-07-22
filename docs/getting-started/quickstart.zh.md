# 快速开始

本指南先以本地服务方式启动 `local-shell-mcp`，再通过 Cloudflare Tunnel 暴露服务，最后把公开的 `/mcp` 端点连接到 ChatGPT。

本地服务是推荐默认方案：它不受 Docker 镜像平台限制，也更符合日常开发工作流。容器部署见 [Docker Compose](docker-compose.md)。

## 前置条件

需要准备：

- 用于执行 shell、文件和 Git 操作的 Linux 主机或虚拟机。
- `git`、`uv`、`python3`、`tmux`、`ripgrep` 和 `cloudflared`。
- 公开域名对应的 Cloudflare Tunnel token。
- 一个允许 AI coding agent 控制的 workspace 目录。
- 可以添加自定义 MCP 连接器的 ChatGPT 套餐和客户端模式。

## 1. 克隆并安装依赖

```bash
git clone https://github.com/rijuyuezhu/local-shell-mcp.git
cd local-shell-mcp
uv sync --group dev
```

长期运行时，请把 checkout 放在稳定路径，例如 `~/Code/local-shell-mcp`。

## 2. 创建 `.env`

```bash
cp .env.example .env
```

至少设置：

```env
LOCAL_SHELL_MCP_MODE=mcp
LOCAL_SHELL_MCP_HOST=127.0.0.1
LOCAL_SHELL_MCP_PORT=8765
LOCAL_SHELL_MCP_WORKSPACE_ROOT=/path/to/your/workspace
LOCAL_SHELL_MCP_STATE_DIR=/path/to/your/workspace/.local-shell-mcp
LOCAL_SHELL_MCP_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_ALLOW_FULL_CONTROL=false
CLOUDFLARE_TUNNEL_TOKEN=your-cloudflare-tunnel-token
```

注意：

- `LOCAL_SHELL_MCP_BASE_URL` 只填写公开 origin，不附加 `/mcp`。
- `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN` 保护本地审批页，应使用长随机值。
- `LOCAL_SHELL_MCP_ALLOW_FULL_CONTROL=false` 会保留内置 workspace 和命令限制。
- `LOCAL_SHELL_MCP_STATE_DIR` 存储审计日志、临时文件、OAuth 签名状态、私有下载快照与链接状态，以及 Agent bridge 配置。

## 3. 本地冒烟测试

```bash
set -a
. ./.env
set +a
uv run local-shell-mcp --mode mcp
```

另开终端：

```bash
curl -i http://127.0.0.1:8765/healthz
```

健康检查成功后可先停止前台进程。

## 4. 配合 Cloudflare Tunnel 启动

仓库自带脚本，会先用 `uv` 启动 `local-shell-mcp`，再在同一终端运行 `cloudflared`：

```bash
scripts/run-with-cloudflare-tunnel.sh
```

公开 MCP 端点应为：

```text
https://your-public-host.example.com/mcp
```

Cloudflare 侧的完整配置见 [Cloudflare Tunnel](cloudflare-tunnel.md)。

## 5. 安装为用户级 systemd 服务

创建 `~/.config/systemd/user/local-shell-mcp.service`：

```ini
[Unit]
Description=local-shell-mcp
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/YOU/Code/local-shell-mcp
ExecStart=/usr/bin/env bash scripts/run-with-cloudflare-tunnel.sh
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

启用并查看日志：

```bash
systemctl --user daemon-reload
systemctl --user enable --now local-shell-mcp.service
journalctl --user -u local-shell-mcp.service -f -n 200
```

修改 `.env` 后执行 `systemctl --user restart local-shell-mcp.service`。

## 6. 添加 ChatGPT 连接器

自定义 MCP 连接器 URL：

```text
https://your-public-host.example.com/mcp
```

使用 `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN` 完成 OAuth 审批。要使用完整 shell、文件系统和 Git 工具面，需要选择支持完整 MCP tools 的客户端模式。

## 7. 尝试第一个提示词

```text
Use local-shell-mcp. First choose an explicit project workdir, then run session_start with that workdir and summarize the returned session_id, workdir, git status, and instruction file paths. Do not change files yet.
```

随后可尝试：

```text
Use local-shell-mcp to inspect this repository, run the tests, and summarize what you found before making any changes.
```

## 8. 查看审计日志

默认路径：

```bash
tail -F /path/to/your/workspace/.local-shell-mcp/audit_log/audit.jsonl | jq -C --unbuffered .
```

审计日志在配置的字节限制内保留非敏感工具输入与输出，并尽力对凭据字段和文本进行脱敏。它仍然属于敏感数据，未经检查不应公开。