# 人机界面

HTTP 服务默认在 `/ui` 提供原生浏览器 Human UI。它是默认的跨平台管理界面。可选 OpenTUI 客户端使用同一组经过认证的 Human UI API，可通过原生终端、release/Docker sidecar、Bun 源码模式，或浏览器中的独立 OpenTUI Console 运行。

## 启动 HTTP 服务

```bash
local-shell-mcp --mode http
```

默认地址：

```text
http://127.0.0.1:8765/ui
```

原生 WebUI 提供 Dashboard、Remotes、Terminals、Files、Todos 和 Audit。它不依赖 OpenTUI，OpenTUI 也不会替换这些浏览器页面。

## OpenTUI 客户端

保持 HTTP 服务运行，在另一终端执行：

```bash
local-shell-mcp tui
```

CLI 默认连接配置端口上的 loopback API：

```text
http://127.0.0.1:<port>/api/ui
```

也可显式指定 loopback HTTPS 或其他本地端口：

```bash
local-shell-mcp tui --api-base https://localhost:9443/api/ui
```

`--api-base` 只接受无凭据的 loopback HTTP(S) URL，并要求路径精确为 `/api/ui`。权限为 `0600` 的本地 UI token 只通过子进程环境变量传递，不会出现在命令行参数中。

运行时解析顺序：

1. 管理员配置的 `ui_tui_command`。
2. 与主程序相邻或位于 `PATH` 的平台 sidecar。
3. release/runtime sidecar。
4. 可选压缩内嵌 payload。
5. 安装 Bun 时的 `ui-opentui/src/tui.tsx` 源码。

源码开发：

```bash
cd ui-opentui
bun install --frozen-lockfile
bun run typecheck
bun test
bun run build:tui
```

当运行时可用时，浏览器会显示独立 **OpenTUI Console**。xterm 连接到 `<ui_path>/ws/opentui`，服务端为其启动私有 PTY/ConPTY 进程。关闭 Console 只终止该 OpenTUI 进程，不会关闭持久化 tmux/ConPTY shell。

## 认证

- loopback 且 `auth_mode: none` 时，浏览器和 CLI 可直接访问。
- OAuth 部署中，浏览器 UI 与 Console 使用现有 OAuth scope。
- 浏览器不会获得私有本地 token；只有服务端启动的 OpenTUI 子进程通过环境变量获得它，用于 loopback API 调用。
- 不应在公开或共享网络上使用 `auth_mode: none`。

## Dashboard

Dashboard 显示系统资源、远程节点、作业、持久化 shell、告警、活动、审计数量和 Todo 状态。浏览器使用安全的文本节点和显式 SVG 元素；OpenTUI 使用终端原生面板与有界图表。worker 返回的文本不会被解释为 HTML 或脚本。

## Remotes

Remotes 页面支持：

- 查看 online/offline worker。
- 创建一次性邀请。
- 重命名和撤销 worker。
- 查看版本、能力和系统信息。

浏览器和 OpenTUI 都通过 control-plane API 完成操作，不拼接远程 shell 命令。

## Terminals

Terminals 管理持久化 tmux 或 ConPTY shell。关闭浏览器附件、刷新页面或断开连接只释放当前连接，不会自动杀死持久化 shell；需要终止 shell 时使用 **Kill selected**。

OpenTUI 使用相同的 machine-scoped terminal API，并支持命令历史、窗口尺寸同步、原始输入与滚动。

## Files

Files 支持本地目录浏览、预览、编辑、新建、复制、移动、重命名和删除。远程 worker 当前仅支持明确暴露的读写/删除能力；不支持的 copy、move、rename 和 mkdir 会在浏览器与 OpenTUI 中禁用，不会通过远程 shell 模拟。

编辑器读取完整的有界 UTF-8 文件并返回 SHA-256 revision。保存时会在路径锁内比较 revision；若文件已被其他进程修改，则拒绝覆盖并要求重新加载。

图片先经过字节限制与 PNG/JPEG/GIF/WebP 魔数检查。OpenTUI 请求 viewport 时，服务端再使用 Pillow 解码第一帧并生成受限 RGBA 缩略图；源像素数、输出尺寸和终端 cell mapping 都有独立限制。

## Todos

浏览器和 OpenTUI 都支持新增、删除、编辑内容、状态和优先级。写入使用 revision guard，避免旧页面覆盖较新的 Todo 列表。

## Audit

Audit 支持筛选、列表/详情布局、JSON 高亮和 `view_image` 预览。原始内联 MCP 图片字段在返回详情前会被清除；无效、超限或无法解码的图片只产生隔离的预览错误，脱敏后的审计详情仍可阅读。

## 配置

```yaml
ui_enabled: true
ui_path: /ui
ui_tui_command: null
ui_terminal_idle_timeout_s: 3600
ui_terminal_max_connections: 8
ui_wallpaper: aurora
```

对应环境变量：

```env
LOCAL_SHELL_MCP_UI_ENABLED=true
LOCAL_SHELL_MCP_UI_PATH=/ui
# LOCAL_SHELL_MCP_UI_TUI_COMMAND=/opt/local-shell-mcp-tui
LOCAL_SHELL_MCP_UI_TERMINAL_IDLE_TIMEOUT_S=3600
LOCAL_SHELL_MCP_UI_TERMINAL_MAX_CONNECTIONS=8
LOCAL_SHELL_MCP_UI_WALLPAPER=aurora
```

`ui_terminal_max_connections` 由持久化 terminal attachment 与浏览器 OpenTUI Console 共享。`ui_wallpaper` 可选 `aurora`、`grid` 或 `none`，均为本地 CSS，不会向第三方请求背景图片。

## 安全说明

Human UI 与 OpenTUI 可以用服务账户权限执行真实命令，因此部署信任边界与 REST/MCP 完全相同。公开部署应使用 OAuth、限制 workspace、保护状态目录，并保持 full-control 关闭，除非运行环境是可丢弃的容器或虚拟机。