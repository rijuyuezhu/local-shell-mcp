# local-shell-mcp

`local-shell-mcp` 让 ChatGPT 和其他 MCP 客户端以受控方式访问你拥有的机器。它通过支持 OAuth 的 MCP 服务提供 shell、文件系统、搜索、补丁、审计、远程工作节点和 Agent 能力桥。

## 从这里开始

多数用户应优先使用本地服务方案：

1. 在需要执行命令的机器上安装或克隆 `local-shell-mcp`。
2. 将 `.env.example` 复制为 `.env`，配置公开 URL、OAuth 模式和审批 PIN。
3. 使用 Cloudflare Tunnel 暴露服务。
4. 将 `/mcp` 端点添加为 ChatGPT 自定义连接器。

完整流程见[快速开始](getting-started/quickstart.md)。

Docker Compose 仍受支持。发布的 Docker 镜像支持 `linux/amd64` 和 `linux/arm64`；只有在确实希望模型控制的工具运行于容器内时才优先选择 Compose。

## 提供的能力

- ChatGPT 兼容的 `/mcp` 端点。
- 面向公开部署的内置 OAuth 审批流程。
- 本地 shell、Python、文件、搜索、补丁、Todo、审计和下载链接工具。
- 可选远程工作节点，在另一台机器上运行相同类别的工具。
- 可选 Agent 能力桥，通过本服务暴露外部 MCP server 与 Markdown Skill。
- 可针对当前 workspace 启动服务的 VS Code 扩展。
- 原生浏览器 WebUI，以及可选的 OpenTUI 终端客户端。

## 常用入口

| 需求 | 页面 |
|---|---|
| 部署服务 | [快速开始](getting-started/quickstart.md) |
| 暴露公网端点 | [Cloudflare Tunnel](getting-started/cloudflare-tunnel.md) |
| 添加 ChatGPT | [ChatGPT 连接器](getting-started/chatgpt-connector.md) |
| 使用 Docker | [Docker Compose](getting-started/docker-compose.md) |
| 管理浏览器界面或 OpenTUI | [人机界面](guides/human-interface.md) |
| 在另一台机器运行任务 | [远程工作节点](guides/remote-workers.md) |
| 添加外部 MCP server 或 Skill | [Agent 能力桥](guides/agent-bridge.md) |
| 查看全部设置 | [配置参考](reference/configuration.md) |
| 查看全部工具 | [工具参考](reference/tools.md) |
| 调试源码 checkout | [开发](development.md) |

## 安全模型

本项目有意向 AI 客户端提供真实 shell 与文件系统能力。公开部署必须启用 OAuth，使用足够长的随机审批 PIN，检查 `workspace_root`，并且除非服务运行在一次性容器或虚拟机中，否则不要启用 full-control 模式。

审计日志会记录完整工具输入与输出。状态目录包含敏感会话数据，不应公开。