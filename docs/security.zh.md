# 安全

`local-shell-mcp` 向 AI 客户端提供真实 shell 执行能力，应视为高风险管理接口。

## 推荐部署方式

- 优先运行在可丢弃的容器或虚拟机中。
- 公开部署必须使用 HTTPS，并设置 `LOCAL_SHELL_MCP_AUTH_MODE=oauth`。
- 不要挂载 Docker socket、宿主机根目录、无限制 SSH key 或整个 `~/.ssh`。
- Git 凭据优先使用单仓库 deploy key 或短期 GitHub App installation token。
- 默认保持 `LOCAL_SHELL_MCP_ALLOW_FULL_CONTROL=false`。
- 每次会话后检查审计日志，并与短期状态一起轮换或销毁。

Cloudflare Tunnel 可作为公网传输层；Cloudflare Access 是可选附加层，不替代内置认证。

## OAuth 安全

内置 OAuth 面向“单个本地操作者将 ChatGPT 等 MCP 客户端连接到高风险 shell server”的场景，不是通用多用户身份系统。公开 HTTP 部署应使用 `oauth`，`none` 只用于可信本地测试。

### 标准边界

- `/mcp` 作为 OAuth protected resource，通过 RFC 9728 metadata 告知 authorization server。
- `WWW-Authenticate` 包含 `resource_metadata`，客户端可先发现 protected-resource metadata。
- authorization-server metadata 遵循 RFC 8414。
- authorization 与 token 请求都必须携带 RFC 8707 `resource`，并且必须匹配本服务。
- bearer token 只能放在 `Authorization` header，不能放在 URL query。
- token 绑定 canonical MCP resource，并验证 `iss`、`aud` 与 `iat`。
- authorization code 使用 PKCE；兼容 `S256` 与 `plain`，客户端应优先 `S256`。

### 已实现控制

- OAuth bootstrap、well-known metadata、健康检查、remote-worker enrollment 和 tokenized download URL 保持公开；普通 MCP/REST 工具路由受认证 middleware 保护。
- canonical resource 默认是完整 `/mcp` URL，而不只是 origin。
- 动态注册客户端的 authorization code 绑定已注册 redirect URI；token exchange 必须提交相同 `client_id`、`redirect_uri`、`resource` 与 PKCE verifier。
- authorization code 短期、一次性、仅存内存，重复使用返回 `invalid_grant`。
- access token 使用本地随机 secret 签名，secret 存储于权限 `0600` 的 `state_dir/oauth-jwt-secret`。
- 本地审批表单会转义反射字段，并可要求 `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN`。
- PIN 失败、客户端注册、code/token 签发、无效 bearer token 和成功认证请求都会写入审计。

### 运维要求

- 公网服务必须使用 HTTPS，并将 `LOCAL_SHELL_MCP_BASE_URL` 设置为外部可见 origin。
- OAuth 与公开 base URL 同时启用时，启动要求非占位且至少 8 字符的 admin PIN；生产环境应使用更长随机值。
- 共享主机应保持 `LOCAL_SHELL_MCP_AUTH_BYPASS_LOCALHOST=false`。
- 状态目录包含 JWT secret、OAuth 状态、下载快照和可能敏感的审计数据，必须私有。
- 公网部署应使用较短 token TTL；当前没有 refresh token 和服务端 revocation list，token 泄露后的主要恢复机制是过期与状态轮换。

### 已知限制

- 待审批动态客户端注册存于内存并按 TTL 过期；首次本地批准后才持久化。
- 已批准客户端重启后仍存在；authorization code 会因进程重启而失效。
- 动态客户端注册为兼容 MCP onboarding 而较宽松，但持久化仍要求本地审批与 PIN。
- authorization server 与 resource server 同机，不获取第三方 metadata，也不会把入站 MCP token 转发给上游 API。
- bearer token 不是 proof-of-possession，获得 token 的人可在过期前使用。
- metadata 未签名，客户端必须使用 HTTPS 并验证 issuer 与 resource。

## 入站 HTTP 请求限制

所有 HTTP 模式应用在解析 REST、MCP、OAuth、下载和 remote-worker 请求前应用 `max_http_request_bytes`。默认 16,000,000 字节；只有可信前端已实施同等或更严格限制时才应设为 `0`。

服务同时检查声明大小与实际 ASGI body 大小：超限 `Content-Length` 会在读取前返回 413；chunked、缺失/无效长度或伪造较小长度时，会按实际消息累计。拒绝事件记录 method、path、声明/实际大小和限制，但不记录 body 内容。

## Full-control 模式

`LOCAL_SHELL_MCP_ALLOW_FULL_CONTROL=true` 会关闭内置命令与路径 denylist，但 MCP safety annotations 仍保持保守。除可丢弃容器或 VM 外不应启用。

Docker 默认根据挂载 `/workspace` 的 owner 创建非 root `agent` 用户。`DOCKER_AGENT_UID`/`DOCKER_AGENT_GID` 只用于覆盖自动检测；`DOCKER_RUN_AS_ROOT=true` 只应用于隔离环境。

## Tokenized 文件下载链接

`create_file_link` 为显式本地或远程 session 中的一个普通文件创建不可变的 creation-time snapshot。创建、列出和撤销仍是受保护工具操作，只有生成的 `/download/{token}` URL 公开。原文件随后变化、删除或被替换都不会改变已有链接。

快照与主/备 metadata 存储于私有 `state_dir`，服务前校验 identity、大小和 SHA-256。过期、撤销、次数耗尽、孤儿或中断传输残留会被清理。浏览器响应默认 attachment；`inline=true` 时增加 `Content-Security-Policy: sandbox`，所有响应增加 `nosniff`、`no-referrer` 和 `private, no-store`。

生成 URL 属于 bearer secret。敏感文件应使用短 TTL、`max_downloads=1`，并尽量保持 `inline=false`。

## Session 间传输

`session_copy` 通过现有有界 worker RPC chunk 协议在显式本地或远程 session 间复制文件和目录。文件只有在 offset、接收范围、最终大小、临时文件身份和可选 SHA-256 全部验证后才发布。

目录复制拒绝 symlink 和特殊文件，先在 sibling staging 目录解包并验证，再提交；提交失败会恢复备份。archive entry 与解包字节分别受 `max_transfer_archive_entries` 和 `max_transfer_unpacked_bytes` 限制。应把被攻陷的远程 worker 视为可能提供恶意数据，control 侧仍会验证路径、类型、大小、checksum 和资源预算。

## Audit 日志处理

审计记录在单事件预算内保留非敏感输入、输出、错误、文件内容和命令输出。凭据类 key、自由文本和 tokenized download URL 会尽力脱敏，超大事件变为标记 preview；未知 secret 格式或业务敏感数据仍可能保留。

`audit_log/audit.jsonl` 是敏感 session 状态，不是已彻底清洗的 telemetry。应保留在受控状态目录，使用 `max_audit_event_bytes` 与 `max_audit_log_bytes` 控制短期留存，不要发送到不具备同等信任等级的第三方日志系统。

## 考虑的威胁

- 仓库文件中的 prompt injection。
- 过度授权模型执行恶意命令。
- 从挂载文件或环境变量泄露 secret。
- 通过 Docker socket 或 privileged mount 接管宿主机。
- 意外破坏性命令。

## 报告问题

在敏感环境中使用时，可提交 issue 或私下联系维护者报告安全问题。