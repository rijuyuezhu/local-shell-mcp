# Agent 能力桥

Agent 能力桥通过 `local-shell-mcp` 暴露额外能力：管理员维护的外部 MCP server，以及来自 project/session、managed 和 global 三类来源的 Markdown Skill。适合在 control server 上提供稳定的附加工具与可复用指令，而不要求每个 MCP 客户端分别配置。

## 目录布局

受管理配置默认位于 `LOCAL_SHELL_MCP_STATE_DIR` 下的 `agent_config`：

```text
/path/to/workspace/.local-shell-mcp/agent_config/
  config.json
  skills/
    paper-writer/
      SKILL.md
      template.md
```

默认 workspace 的路径通常为：

```text
/workspace/.local-shell-mcp/agent_config
```

Skill 按以下顺序发现，并按规范化后的实际路径去重：

1. project/session：`<workdir>/.agents/skills`
2. managed：`<agent_config_dir>/<skills.directory>`
3. global：`$XDG_CONFIG_HOME/agents/skills`；若 `XDG_CONFIG_HOME` 未设置或为相对路径，则使用 `~/.config/agents/skills`

同名 Skill 由第一个有效来源获胜。高优先级目录损坏或缺少 `SKILL.md` 时，不会阻止低优先级的有效版本。所有来源共享 Skill 数量、扫描条目和路径字节预算；重复项和截断会以有界 warning 返回。符号链接及逃逸出当前来源根目录的路径仍会被拒绝。

为 `list_agent_skills`、`activate_agent_skill` 或 `read_agent_skill_file` 传入 `session_id` 时，project 来源是该显式本地 session 的 workdir。远程 session 会把发现与读取操作分派到对应 worker，使用 worker session 的 workdir；control machine 不会解析远端来源路径。不传 `session_id` 时，project 来源为 `workspace_root`，动态 Skill 工具也使用这一默认 registry。

## `config.json`

最小配置：

```json
{
  "version": 1
}
```

包含 stdio MCP、HTTP MCP、Skill 与动态工具的示例：

```json
{
  "version": 1,
  "mcpServers": {
    "github": {
      "type": "stdio",
      "command": "github-mcp-server",
      "args": ["stdio"],
      "env": {
        "EXAMPLE_ENV_VALUE": "replace-me"
      }
    },
    "docs": {
      "type": "http",
      "url": "https://docs.example.com/mcp",
      "headers": {
        "X-Example-Header": "replace-me"
      },
      "enabled": true
    }
  },
  "skills": {
    "enabled": true,
    "directory": "skills"
  },
  "dynamicTools": {
    "mcp": true,
    "skills": true
  }
}
```

MCP server `type` 支持 `stdio`、`http` 和 `sse`。`env`、`headers`、状态输出和错误 payload 会尽力脱敏，但配置目录仍应作为敏感应用配置保护。

## Skills

每个 Skill 是一个包含 `SKILL.md` 的目录：

```text
.agents/skills/debugging/SKILL.md
```

示例：

```markdown
# Debugging

Use this skill for debugging failing tests. First reproduce the failure, then inspect the smallest relevant code path, then propose a minimal fix.
```

Skill 名称来自目录名。先调用 `list_agent_skills` 获取准确名称、选中的 `source` 和 `source_path`，再使用相同的可选 `session_id` 调用 `activate_agent_skill` 或 `read_agent_skill_file`。

开启动态 Skill 工具后，`paper-writer` 之类的 Skill 还会作为类似 `activate_skill__paper_writer` 的一级 MCP 工具出现。动态工具只针对默认 workspace registry，不随每个 session 改变。

## Bridge 工具

| 工具 | 用途 |
|---|---|
| `agent_config_status` | 显示配置路径、manifest 状态、Skill 来源与数量、MCP server 状态、动态工具开关和脱敏错误 |
| `list_agent_skills` | 列出 Skill，不加载正文；可传 `session_id` |
| `activate_agent_skill` | 按准确名称加载一个 Skill；应沿用相同 `session_id` |
| `read_agent_skill_file` | 读取 `activate_agent_skill` 返回的有界 related file |
| `list_agent_mcp_servers` | 列出上游 MCP server 与可用状态 |
| `list_agent_mcp_tools` | 列出一个或全部上游 MCP server 的工具 |
| `call_agent_mcp_tool` | 调用一个上游 MCP 工具 |

推荐流程：

```text
Use local-shell-mcp to run agent_config_status, list available agent skills and MCP servers, then tell me which extra capabilities are available.
```

调用上游工具前先列出工具：

```text
Use local-shell-mcp to list tools for the agent MCP server named docs, then call its search tool with query "deployment".
```

## 动态工具

动态工具由两层开关共同控制：

1. 应用设置：`LOCAL_SHELL_MCP_AGENT_DYNAMIC_MCP_TOOLS` 与 `LOCAL_SHELL_MCP_AGENT_DYNAMIC_SKILL_TOOLS`。
2. manifest：`dynamicTools.mcp` 与 `dynamicTools.skills`。

当客户端只应使用固定 bridge 工具、而不希望工具列表随磁盘配置变化时，应关闭动态工具。

## 设置

| 设置 | 默认值 | 含义 |
|---|---:|---|
| `LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED` | `true` | 启用 Agent bridge 工具 |
| `LOCAL_SHELL_MCP_STATE_DIR` | `/workspace/.local-shell-mcp` | 状态根目录；managed `agent_config` 位于其中 |
| `LOCAL_SHELL_MCP_AGENT_MCP_PROBE_TIMEOUT_S` | `5` | 外部 MCP server 探测超时 |
| `LOCAL_SHELL_MCP_AGENT_MCP_CALL_TIMEOUT_S` | `60` | 外部 MCP 工具调用超时 |
| `LOCAL_SHELL_MCP_AGENT_DYNAMIC_MCP_TOOLS` | `true` | 注册动态上游 MCP 工具 |
| `LOCAL_SHELL_MCP_AGENT_DYNAMIC_SKILL_TOOLS` | `true` | 注册动态 Skill 工具 |

## 注意事项

- stdio MCP server 命令运行于服务端环境；Docker 部署时即容器内，本地源码/二进制部署时即宿主机。
- 网络 MCP server 使用服务端网络路径，而不是 ChatGPT 客户端网络路径。
- 暴露动态工具前应检查工具名称和描述。
- project/global Skill 仍受相同的 regular-file、无 symlink 和来源根目录 containment 限制。