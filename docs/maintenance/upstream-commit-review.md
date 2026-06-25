# Upstream commit 功能对照表

本表用于记录 origin 相对 upstream 的功能同步状态。判断标准是**功能效果**，不是代码位置、文件名或补丁逐字一致。

## 范围

- Wenrui Huang 第一次基于 upstream 的提交：`0d37e8f`（父提交为 upstream `a7a75fb`）。

- 检查的 upstream 范围：`a7a75fb..4514979`，共 56 个提交，按 upstream 时间顺序排列。

- 对照的 origin 头部：检查时为 `9388fd0` / v3.7.0。


## 状态含义

- **已实现**：origin 当前功能上覆盖 upstream 提交的用户可见行为或维护目标。

- **部分实现**：origin 覆盖了主要目标，但有默认值、配置面、文档范围或 CI 形态差异。

- **已抛弃**：origin 明确不采用该 upstream 方向，或该补丁只适用于已不存在的旧结构/版本线。


## 逐提交结论

| # | 日期 | upstream commit | upstream 主题 | 状态 | 结论 | 原因 / origin 证据 |
|---:|---|---|---|---|---|---|
| 1 | 2026-06-12 | `37b87f1` | fix-html-output | **已实现** | OAuth 授权页反射字段已做 HTML escape。 | 当前 `src/local_shell_mcp/oauth/authorization.py` 对 hidden input、error、resource、scope、pin_hint 使用 `html_lib.escape`；功能上覆盖 XSS/HTML 注入修复。 |
| 2 | 2026-06-12 | `de6d459` | fix-worker-vendor-path | **已实现** | 远程 worker bootstrap 已把 vendor 目录加入 PYTHONPATH。 | `src/local_shell_mcp/remote/join_worker.sh` 使用 `$TMPDIR:$TMPDIR/vendor`；`remote/bundle.py` 打包 vendor；`tests/test_e2e_remote_worker.py` 有断言。 |
| 3 | 2026-06-12 | `2afbde2` | check-release-version-match | **已实现** | release workflow 会校验 tag 版本与 `pyproject.toml` 版本一致。 | `.github/workflows/release.yml` 中保留 release tag 解析与 mismatch 报错逻辑；版本号本身按 origin 线维护。 |
| 4 | 2026-06-12 | `ce2a9a7` | handle-truncated-unicode | **已实现（适配）** | 读取被字节上限截断的 UTF-8 文件时不会崩溃。 | 当前 `src/local_shell_mcp/ops/files.py` 使用 incremental UTF-8 decoder，在截断场景避免半个多字节字符导致异常；表现与 upstream replace-char 不完全相同，但功能问题已解决。 |
| 5 | 2026-06-12 | `390a18f` | fix-pattern-edge-case | **已实现** | 内容搜索 query 以 `-` 开头时不会被 ripgrep 当成选项。 | `src/local_shell_mcp/ops/search.py` 在 query 前插入 `--`；相关测试覆盖 `rg` 缺失时的 skip。 |
| 6 | 2026-06-12 | `c971abd` | fix-git-add-path-separator | **已抛弃（不适用）** | origin 当前工具面不再提供独立 `git_add_tool`。 | 当前 git 操作主要通过 `run_shell_command` / `apply_patch` 等通用工具完成；没有需要移植的专用 git-add 包装器，因此该修复在当前架构下不适用。 |
| 7 | 2026-06-12 | `0a7ee3f` | add-docker-build-ignore | **已实现（适配）** | Docker build context 已被 `.dockerignore` 收敛。 | 当前 `.dockerignore` 采用更严格的默认忽略 `**` + 白名单方式，只保留 Dockerfile、项目元数据、`src/**` 和必要 scripts，比 upstream 列表式忽略更保守。 |
| 8 | 2026-06-12 | `2593bc0` | fix-search-test-literal | **已实现（测试适配）** | 对应测试中的 literal 换行/转义问题已在当前测试形态中不存在。 | 当前搜索测试已按拆分后的 `ops/search.py` 结构维护，并包含 `rg` 可用性保护；不需要原补丁逐字移植。 |
| 9 | 2026-06-12 | `dc88eb3` | fix-oauth-import-order | **已抛弃（样式补丁不适用）** | 这是旧 `oauth.py` 的 import 排序修正；当前 OAuth 模块已拆分。 | 当前代码在 `src/local_shell_mcp/oauth/` 包内维护；该提交不改变功能，原路径不再是当前结构的移植目标。 |
| 10 | 2026-06-12 | `e761b07` | ci-search-test-guard | **已实现** | CI/本地测试不会因缺失 `rg` 二进制而错误失败。 | `tests/test_search_ops.py` 使用 `shutil.which(get_settings().rg_bin)` 保护搜索测试。 |
| 11 | 2026-06-13 | `78fd6d5` | Raise public shell timeout cap to 120 seconds | **部分实现** | origin 没有采用 upstream 默认 120s cap，但把 shell timeout 做成配置项。 | 当前默认 `run_shell_max_timeout_s` 仍是 60；用户可通过 `LOCAL_SHELL_MCP_RUN_SHELL_MAX_TIMEOUT_S` / config 提高上限。功能诉求“可提高 cap”覆盖，upstream 默认值被本仓库安全策略保留为 60。 |
| 12 | 2026-06-13 | `8e5a988` | Bump version to 2.3.0 | **已抛弃（被 origin 版本线取代）** | 单纯 upstream 2.x 版本号提交不适用于 origin。 | origin 当前版本线是 3.x（检查时为 v3.7.0），不会回退到 upstream 2.3.0。 |
| 13 | 2026-06-13 | `e44a6ad` | Exclude cryptography from PyInstaller binaries | **已实现** | PyInstaller release 构建排除了 `cryptography`。 | 当前 `.github/workflows/release.yml` 保留 `--exclude-module cryptography`。 |
| 14 | 2026-06-13 | `572d947` | Prepare v2.3.1 release | **已抛弃（被 origin 版本线取代）** | upstream 2.3.1 release 元数据不适用于 origin。 | origin 维护自己的版本、发布产物和 changelog/release workflow；不复制 upstream 2.3.1 bump。 |
| 15 | 2026-06-13 | `9b04a02` | Add public file link downloads | **已实现（适配）** | 临时文件下载链接功能已存在。 | 当前有 `create_file_link` / `list_file_links` / `revoke_file_link`、`/download/{token}` 路由、`tests/test_downloads.py` 和 E2E 覆盖；模块位置改为 `ops/downloads.py`、`server/shared/downloads.py`、registry。 |
| 16 | 2026-06-13 | `0c3dc20` | Add remote file transfer tools | **已实现（适配）** | 远程文件/目录传输功能已存在。 | 当前有 `remote_copy_file`、`remote_copy_dir`、`remote_pull_file`、`remote_push_file` 等工具；实现拆到 `ops/transfer.py`、`remote/transfer.py`、`tools/registry/transfer.py` 并有 transfer/remote-transfer 测试。 |
| 17 | 2026-06-14 | `4384da8` | Add MCP output schemas | **已实现（适配）** | 所有 MCP 工具输出 schema 已由 declarative registry / typed schema 暴露。 | `tests/test_mcp_chatgpt_compat.py` 检查 outputSchema；`docs/reference/generated/tools.json` 也包含每个工具的 outputSchema。 |
| 18 | 2026-06-15 | `be33c71` | Add stable MCP tool surface coverage | **已实现（适配）** | 工具面稳定性测试已在 origin 架构下实现。 | `tests/test_tool_surface.py` 覆盖本地/远程工具集合、HTTP 侧行为和关键描述；比 upstream 旧 `tools.py` 形态更贴合当前 registry 架构。 |
| 19 | 2026-06-15 | `f92e662` | Normalize REST tool validation errors | **已实现（适配）** | REST 工具错误统一为结构化 error envelope。 | 当前 `server/http/errors.py` 和 `tools/declarative.py` 处理缺参、ValueError、HTTPException；`tests/test_http_validation.py` 覆盖。 |
| 20 | 2026-06-15 | `5f9682d` | Audit routed MCP tool calls | **已实现（适配）** | MCP/HTTP routed tool call 审计已实现。 | 当前审计逻辑分布在 `server/mcp/watchdogs.py`、`tools/local_invocations.py` 和 `audit.py`；`tests/test_audit_tool_calls.py` 覆盖输入输出/错误路径。 |
| 21 | 2026-06-15 | `5d01c5d` | Filter shell subprocess environment | **已实现（策略适配）** | shell 子进程环境会过滤服务端敏感环境变量。 | 当前 `_subprocess_env()` 固定过滤 `LOCAL_SHELL_MCP_`、`DOCKER_`、`PYTHONPATH`、`CLOUDFLARE_TUNNEL_TOKEN`；没有移植 upstream 可配置 blocklist，因为 origin 选择固定安全策略。 |
| 22 | 2026-06-15 | `2516bd2` | Improve MCP tool descriptions | **已实现（适配）** | 当前工具描述已按 registry 分散维护，并包含用途/限制/替代工具提示。 | `tools/registry/*.py` 中的描述会生成到 MCP schema 和 docs；`tests/test_tool_surface.py` / `tests/test_mcp_chatgpt_compat.py` 检查关键文案。 |
| 23 | 2026-06-15 | `2a308c8` | Add HTTP MCP parity coverage | **已实现（适配）** | HTTP 与 MCP 工具注册由 declarative registry 统一派生，避免两套手写表漂移。 | 当前测试覆盖 REST/MCP payload 和远程路由开关；功能上覆盖 upstream parity 目标。 |
| 24 | 2026-06-15 | `60db561` | Add remote capability checks | **已实现（适配）** | 远程 worker 能力清单、allowlist 和拒绝未知工具的行为已覆盖。 | 当前有 `remote/tool_specs.py`、`remote/manager.py` 和 `tests/test_remote_worker_tool_specs.py` / E2E worker 测试。 |
| 25 | 2026-06-15 | `e1ee6cf` | Add documentation site | **已实现（适配）** | origin 已有 MkDocs 文档站。 | 当前 `mkdocs.yml`、`docs/getting-started/`、`docs/guides/`、`docs/reference/` 等构成当前文档站；内容结构按 origin 重新组织。 |
| 26 | 2026-06-15 | `19fe715` | Add MCP tool export script | **已实现（适配）** | 工具参考 JSON 导出脚本已存在。 | 当前 `scripts/export-tools-json.py` 基于 `server.mcp.app.build_mcp` 和 declarative registry 导出；相关 generated docs 和测试覆盖。 |
| 27 | 2026-06-15 | `acfbbfc` | Update metadata | **已抛弃（被 origin 元数据取代）** | upstream 包元数据/项目 URL/版本线与 origin 不一致。 | origin 使用自己的 repo URL、Python 3.14/3.x 版本线和发布配置；不移植 upstream 元数据。 |
| 28 | 2026-06-15 | `1c81534` | Fix lint in added tests | **已实现（等价清理）** | 对应 upstream 测试文件没有逐字保留，但当前适配后的测试纳入 pre-commit/pyright/pytest。 | 当前 CI 运行 pre-commit、pyright、pytest；功能上保留“新增测试 lint-clean”的目标。 |
| 29 | 2026-06-15 | `7d71773` | Add agent bridge core modules | **已实现（被更完整实现取代）** | agent bridge 已在 origin 中以拆分模块实现。 | 当前 `src/local_shell_mcp/agent_bridge/` 包含 config、service、skills、state、MCP adapters 和 registry 工具；比 upstream 初版更贴合当前架构。 |
| 30 | 2026-06-15 | `2c9e262` | Add GitHub Pages docs deployment | **已实现（适配）** | docs GitHub Pages workflow 已存在。 | 当前 `.github/workflows/docs.yml` build MkDocs，并在 main push 后 upload/deploy Pages。 |
| 31 | 2026-06-15 | `caa11f8` | Configure GitHub Pages workflow | **已实现（适配）** | Pages workflow 已按 origin 工具链配置。 | 当前 docs workflow 使用 Python 3.14、uv、`mkdocs build --strict` 和 Pages deploy；和 upstream 目标一致但具体版本不同。 |
| 32 | 2026-06-15 | `5f59004` | Polish documentation landing page | **已实现（适配）** | 文档首页已由 origin 当前信息架构维护。 | 当前 `docs/index.md` 与 MkDocs nav 作为 canonical landing；没有逐字移植 upstream 文案。 |
| 33 | 2026-06-15 | `9a284ea` | Improve docs and multilingual coverage | **部分实现** | 通用文档/社区文件有 origin 版本；多语言覆盖未采用。 | 当前有 community docs、guides、reference，但没有 upstream 那套本地化页面；多语言部分被跳过。 |
| 34 | 2026-06-15 | `65cfec4` | Use native docs internationalization | **已抛弃（跳过）** | origin 未启用 MkDocs native i18n。 | 当前 `mkdocs.yml` 未配置 i18n plugin；维护策略仍以英文 docs 为 canonical。 |
| 35 | 2026-06-15 | `112e027` | Improve documentation structure and coverage | **部分实现** | origin 有自己的 docs 结构和覆盖面，但未导入 upstream 全量页面。 | 当前 `docs/` 结构已经覆盖 getting-started/guides/reference/security/troubleshooting/community；upstream 部分页面按本仓库信息架构改写或跳过。 |
| 36 | 2026-06-15 | `9ceac6b` | Expand documentation structure and tool reference | **已实现（适配）** | 工具/配置 reference 已由生成文件和 renderer 支撑。 | 当前 `docs/reference/generated/tools.json`、`configuration.json`、`reference-renderer.js` 和 reference 页面实现工具参考；具体生成方式不同。 |
| 37 | 2026-06-15 | `e49a142` | Add localized documentation pages | **已抛弃（跳过）** | localized docs 页面未进入 origin。 | 当前 `docs/` 没有保留 upstream 的多语言页面；与 i18n 决策一致。 |
| 38 | 2026-06-15 | `ea79fa9` | Add native Windows persistent sessions | **已抛弃（跳过）** | Windows native persistent session 后端未采用。 | origin 当前 persistent shell 仍以 Unix/tmux 和容器工作流为主；Windows 后端需要单独设计和 CI。 |
| 39 | 2026-06-15 | `4c838fe` | Add Windows ConPTY shell backend | **已抛弃（跳过）** | ConPTY/pywinpty 后端未采用。 | 当前没有 `pywinpty`/ConPTY 依赖或后端；避免在现有 Linux/container 抽象中引入未验证平台复杂度。 |
| 40 | 2026-06-15 | `a3a6267` | Bump version to 2.6.0 | **已抛弃（被 origin 版本线取代）** | upstream 2.6.0 版本号不适用于 origin。 | origin 当前发布线为 3.x；不移植 upstream 版本 bump。 |
| 41 | 2026-06-15 | `b30781c` | Fix remote worker join bootstrap | **已实现（适配）** | 远程 worker join/bootstrap 修复已按当前 package split 实现。 | 当前有 `remote_worker.py` entrypoint、`remote/join_worker.sh`、bundle 打包和 E2E bootstrap 测试。 |
| 42 | 2026-06-16 | `3382d10` | Fix remote worker dependency bootstrap | **已实现（适配）** | worker 启动路径减少服务端依赖，真正执行工具时再加载本地 registry。 | 当前 `remote/worker.py` 使用标准库 HTTP/JSON 路径并有 `tests/test_remote_worker_bootstrap.py` 验证 bootstrap import/依赖边界。 |
| 43 | 2026-06-16 | `e91fbf0` | Fix remote worker HTTP client behind Cloudflare | **已实现（适配）** | worker POST 优先使用 curl，并保留 urllib fallback 与非 2xx/非 JSON 错误处理。 | 当前 `remote/worker.py` 有 `_worker_post_json_with_curl`、HTTP status marker、`-L`、urllib fallback；`tests/test_remote_worker_bootstrap.py` 覆盖 curl/urllib/错误路径。 |
| 44 | 2026-06-17 | `2581856` | Keep remote workers retrying connection failures | **已实现** | worker 注册、poll、submit result 会对瞬时连接失败持续重试。 | 当前 `remote/worker.py` 有 `_worker_post_json_forever`、指数退避和 capped delay；测试覆盖 retry until success。 |
| 45 | 2026-06-17 | `4283bce` | remote reconnect | **已实现（适配）** | 远程 worker identity 持久化、控制端 registry 和 `/remote/resume` 已存在。 | 当前 `remote/constants.py` 定义 `remote-workers.json` / `identity.json`，`remote/manager.py` 实现 `resume_worker`，`remote/http.py` 注册 `/remote/resume`，worker 端读写 identity。 |
| 46 | 2026-06-17 | `5f0de67` | Add purpose metadata to risky tool calls | **已实现（适配）** | 高风险 shell 工具保留可选 `purpose` 参数并进入 schema；不再产生单独的 purpose 审计事件。 | 当前 `bash`、`run_python_code` 参数包含 `purpose`；generated tools reference 覆盖 schema，通用 tool call audit 仍记录完整输入。 |
| 47 | 2026-06-17 | `e778822` | Add tracked job management tools | **已实现（适配）** | 本地/远程 tracked job 工具已实现。 | 当前有 `ops/jobs.py`、`tools/registry/jobs.py`、job result models、`job_start/list/tail/stop/retry` 和 remote_job 对应工具；`tests/test_jobs.py` 覆盖。 |
| 48 | 2026-06-17 | `fd8411f` | Report remote worker status counts | **已实现** | `remote_list_machines` 会返回 online/offline/total counts 和队列/last_seen 信息。 | 当前 `remote/manager.py` 的 `list_machines()` 生成 `counts`、`last_seen_age_s`、`queue_depth`；bootstrap/remote tests 覆盖。 |
| 49 | 2026-06-17 | `10f7806` | Add built-in version reporting | **已实现（适配）** | CLI/HTTP/MCP version reporting 已存在。 | 当前 `version.py`、`ops/version.py`、`tools/registry/version.py` 和 `tests/test_version.py` 提供/覆盖版本信息；返回 origin 版本线。 |
| 50 | 2026-06-17 | `4e90402` | Expand CI smoke coverage | **部分实现** | origin CI 覆盖已扩展，但没有逐字复制 upstream smoke job。 | 当前 CI 有 pre-commit、pyright、ubuntu/macos pytest、VS Code extension build；是否需要 upstream 那些精确 smoke 命令由 origin CI 策略另行决定。 |
| 51 | 2026-06-17 | `5511920` | Fix lint for new tool modules | **已实现（等价清理）** | 新增/拆分工具模块按当前 lint/type/test 体系维护。 | 当前 CI 的 pre-commit + pyright + pytest 会覆盖这类清理；upstream 具体 lint patch 不再逐字适用。 |
| 52 | 2026-06-17 | `45abb91` | Bump version to 2.7.0 | **已抛弃（被 origin 版本线取代）** | upstream 2.7.0 版本号不适用于 origin。 | origin 当前为 3.x 发布线；不移植 upstream 2.7.0 bump。 |
| 53 | 2026-06-17 | `58049c7` | Fix localized docs translations | **已抛弃（不适用）** | localized docs 已整体跳过，因此翻译修复也不适用。 | 当前没有 upstream localized docs 页面。 |
| 54 | 2026-06-17 | `a0a60db` | Add docs i18n regression check | **已抛弃（不适用）** | native i18n 未采用，因此 i18n regression check 未加入。 | 当前 scripts/workflows 中没有 i18n 检查；与 docs i18n 跳过决策一致。 |
| 55 | 2026-06-17 | `8262a39` | Handle remote worker KeyboardInterrupt cleanly | **已实现** | worker CLI 捕获 KeyboardInterrupt 并平滑退出。 | 当前 `remote/worker.py` 在 CLI 入口处理 `KeyboardInterrupt`；`tests/test_remote_worker_bootstrap.py` 覆盖。 |
| 56 | 2026-06-18 | `4514979` | Refine MCP tool security scopes | **已实现（适配）** | 工具 security scopes 已按读/写/执行/下载等用途细分。 | 当前 `tests/test_mcp_chatgpt_compat.py` 检查 search/fetch、文件链接、写入、执行等 scope；`docs/reference/generated/tools.json` 输出对应 `securitySchemes`。 |

## 备注

多处 upstream 变更在 origin 中被重新落位到拆分后的模块，例如 `ops/*`、`server/http/*`、`server/mcp/*`、`tools/registry/*`、`remote/*` 和 typed schemas。因此，本表只记录功能等价性，不要求补丁逐字或路径一致。

版本号类提交统一按 origin 自己的 3.x 发布线处理；上游 2.x bump 不应移植。文档 i18n 与 Windows native/ConPTY 后端目前也被视为未采用方向，需要单独设计后才能进入 origin。
