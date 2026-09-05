import type {
  ApiEnvelope,
  AgentSessionPayload,
  AuditEntry,
  AuditPayload,
  BootstrapPayload,
  DashboardPayload,
  FilePreview,
  FilesPayload,
  InvitePayload,
  Machine,
  MachinePayload,
  TerminalPayload,
  TerminalSession,
  TodoItem,
  TodoPayload,
} from "./types"

const configuredBase = process.env.WORKGATE_UI_API_BASE || "http://127.0.0.1:8765/api/ui"
const localToken = process.env.WORKGATE_UI_LOCAL_TOKEN || ""
export const API_BASE = configuredBase.replace(/\/$/, "")

function queryString(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue
    search.set(key, String(value))
  }
  const encoded = search.toString()
  return encoded ? `?${encoded}` : ""
}

const REQUEST_TIMEOUT_MS = 45_000

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController()
  const externalSignal = init?.signal
  const abortFromExternal = () => controller.abort(externalSignal?.reason)
  if (externalSignal?.aborted) abortFromExternal()
  else externalSignal?.addEventListener("abort", abortFromExternal, { once: true })
  const timeout = setTimeout(() => controller.abort(new Error("Request timed out")), REQUEST_TIMEOUT_MS)
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        ...(localToken ? { "X-Workgate-UI-Token": localToken } : {}),
        ...init?.headers,
      },
    })
    let payload: ApiEnvelope<T>
    try {
      payload = (await response.json()) as ApiEnvelope<T>
    } catch {
      throw new Error(`${response.status} ${response.statusText}`)
    }
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || payload.error || `${response.status} ${response.statusText}`)
    }
    return payload.data
  } finally {
    clearTimeout(timeout)
    externalSignal?.removeEventListener("abort", abortFromExternal)
  }
}

type ForkBootstrap = {
  version?: Record<string, unknown>
  ui?: { features?: Record<string, unknown> }
  machines?: Machine[]
  counts?: Record<string, number>
}

type ForkFilesPayload = Omit<FilesPayload, "parent_entries"> & {
  parent_entries?: FilesPayload["parent_entries"]
}

type ForkTerminalPayload = {
  machine: string
  shells?: Array<{
    shell_id: string
    name?: string | null
    cwd?: string | null
    command?: string | null
  }>
  sessions?: TerminalSession[]
}

type ForkDashboardPayload = Partial<DashboardPayload> & {
  generated_at: number
  health: DashboardPayload["health"]
  version: Record<string, unknown>
  system: DashboardPayload["system"]
  alerts: DashboardPayload["alerts"]
  activity: DashboardPayload["activity"]
  audit_total_24h: number
}

function machineCounts(machines: Machine[], counts?: Record<string, number>): Record<string, number> {
  const online = machines.filter((machine) => machine.status === "online").length
  return {
    online,
    offline: Math.max(0, machines.length - online),
    total: machines.length,
    ...counts,
  }
}

function normalizeMachinePayload(payload: { machines?: Machine[]; counts?: Record<string, number>; enabled?: boolean }): MachinePayload {
  const machines = payload.machines || []
  return {
    machines,
    counts: machineCounts(machines, payload.counts),
    ...(payload.enabled === undefined ? {} : { enabled: payload.enabled }),
  }
}

function normalizePreview(payload: FilePreview): FilePreview {
  return {
    ...payload,
    mime_type: payload.mime_type || payload.media_type,
    sha256: payload.sha256 || payload.file_sha256 || null,
  }
}

function normalizeTerminalPayload(payload: ForkTerminalPayload): TerminalPayload {
  const sessions = payload.sessions || (payload.shells || []).map((shell) => ({
    session_id: shell.shell_id,
    name: shell.name,
    cwd: shell.cwd,
    command: shell.command,
  }))
  return { machine: payload.machine, sessions }
}

function terminalBody(body: Record<string, unknown>): Record<string, unknown> {
  const normalized = { ...body }
  if (typeof normalized.session_id === "string" && normalized.shell_id === undefined) {
    normalized.shell_id = normalized.session_id
    delete normalized.session_id
  }
  return normalized
}

function terminalResult<T>(value: T): T {
  if (!value || typeof value !== "object" || Array.isArray(value)) return value
  const payload = value as Record<string, unknown>
  if (typeof payload.shell_id !== "string" || payload.session_id !== undefined) return value
  return { ...payload, session_id: payload.shell_id } as T
}

async function rawFiles(machine: string, path: string, signal?: AbortSignal): Promise<ForkFilesPayload> {
  return request(`/files${queryString({ machine, path })}`, { signal })
}

async function rawTerminals(machine: string, signal?: AbortSignal): Promise<TerminalPayload> {
  return normalizeTerminalPayload(
    await request<ForkTerminalPayload>(`/terminals${queryString({ machine })}`, { signal }),
  )
}

async function rawTodos(machine: string, sessionId: string, signal?: AbortSignal): Promise<TodoPayload> {
  return request(`/todos${queryString({ machine, session_id: sessionId })}`, { signal })
}

export const api = {
  async bootstrap(): Promise<BootstrapPayload> {
    const payload = await request<ForkBootstrap>("/bootstrap")
    const machines = normalizeMachinePayload(payload)
    const features = payload.ui?.features || {}
    return {
      version: payload.version || {},
      machines,
      features: {
        ...features,
        remote: Boolean(features.remotes ?? features.remote ?? machines.enabled !== false),
        wallpaper: String(features.wallpaper || "aurora"),
      },
    }
  },

  async dashboard(signal?: AbortSignal): Promise<DashboardPayload> {
    const [dashboard, machines, terminals] = await Promise.all([
      request<ForkDashboardPayload>(`/dashboard${queryString({ machine: "local" })}`, { signal }),
      request<MachinePayload>("/machines", { signal }),
      rawTerminals("local", signal),
    ])
    return {
      generated_at: dashboard.generated_at,
      health: dashboard.health,
      version: dashboard.version,
      system: dashboard.system,
      machines: normalizeMachinePayload(machines),
      jobs: dashboard.jobs || [],
      job_counts: dashboard.job_counts || {},
      sessions: terminals.sessions,
      session_count: terminals.sessions.length,
      alerts: dashboard.alerts,
      activity: dashboard.activity,
      audit_total_24h: dashboard.audit_total_24h,
      todo_counts: dashboard.todo_counts || { total: 0, open: 0 },
    }
  },

  async machines(): Promise<MachinePayload> {
    return normalizeMachinePayload(await request<MachinePayload>("/machines"))
  },

  sessions(machine = "local", includeInactive = false, signal?: AbortSignal): Promise<AgentSessionPayload> {
    return request(`/sessions${queryString({ machine, include_inactive: includeInactive || undefined })}`, { signal })
  },

  terminateSession(machine: string, sessionId: string): Promise<{ machine: string; session: AgentSessionPayload["sessions"][number] }> {
    return request("/sessions/terminate", {
      method: "POST",
      body: JSON.stringify({ machine, session_id: sessionId }),
    })
  },

  async files(machine: string, path: string, signal?: AbortSignal): Promise<FilesPayload> {
    const current = await rawFiles(machine, path, signal)
    const parentEntries = current.parent_entries || (
      current.parent === current.path
        ? current.entries
        : (await rawFiles(machine, current.parent, signal)).entries
    )
    return { ...current, parent_entries: parentEntries }
  },

  async filePreview(
    machine: string,
    path: string,
    columns?: number,
    rows?: number,
    cellAspect?: number,
    signal?: AbortSignal,
  ): Promise<FilePreview> {
    const payload = await request<FilePreview>(
      `/files/preview${queryString({ machine, path, columns, rows, cell_aspect: cellAspect })}`,
      { signal },
    )
    return normalizePreview(payload)
  },

  async fileContent(machine: string, path: string): Promise<FilePreview> {
    return normalizePreview(
      await request<FilePreview>(`/files/content${queryString({ machine, path })}`),
    )
  },

  fileAction<T = unknown>(action: string, body: Record<string, unknown>): Promise<T> {
    const normalized = { ...body }
    let resolvedAction = action
    if (action === "touch") {
      resolvedAction = "write"
      normalized.content = ""
      normalized.overwrite = false
    }
    if (action === "rename" && normalized.name === undefined && typeof normalized.destination === "string") {
      normalized.name = normalized.destination.split(/[\\/]/).filter(Boolean).at(-1) || ""
      delete normalized.destination
    }
    return request(`/files/${encodeURIComponent(resolvedAction)}`, {
      method: "POST",
      body: JSON.stringify(normalized),
    })
  },

  terminals(machine: string, signal?: AbortSignal): Promise<TerminalPayload> {
    return rawTerminals(machine, signal)
  },

  async terminalRead(
    machine: string,
    sessionId: string,
    lines = 500,
    signal?: AbortSignal,
  ): Promise<{ session_id: string; output: string }> {
    const payload = await request<{ shell_id: string; output: string }>(
      `/terminals/read${queryString({ machine, shell_id: sessionId, lines })}`,
      { signal },
    )
    return { session_id: payload.shell_id, output: payload.output }
  },

  async terminalAction<T = unknown>(action: string, body: Record<string, unknown>): Promise<T> {
    const result = await request<T>(`/terminals/${encodeURIComponent(action)}`, {
      method: "POST",
      body: JSON.stringify(terminalBody(body)),
    })
    return terminalResult(result)
  },

  todos(machine: string, sessionId: string): Promise<TodoPayload> {
    return rawTodos(machine, sessionId)
  },

  writeTodos(
    todos: TodoItem[],
    expectedRevision: number,
    machine: string,
    sessionId: string,
  ): Promise<TodoPayload> {
    return request("/todos", {
      method: "PUT",
      body: JSON.stringify({ machine, session_id: sessionId, todos, expected_revision: expectedRevision }),
    })
  },

  audit(filters: Record<string, string | number | boolean | null | undefined>, signal?: AbortSignal): Promise<AuditPayload> {
    const { node, ...rest } = filters
    return request(`/audit${queryString({ ...rest, scope: "global", machine: node || rest.machine })}`, { signal })
  },

  sessionAudit(
    machine: string,
    sessionId: string,
    filters: Record<string, string | number | boolean | null | undefined> = {},
    signal?: AbortSignal,
  ): Promise<AuditPayload> {
    return request(`/audit${queryString({ ...filters, scope: "session", machine, session: sessionId })}`, { signal })
  },

  async auditDetail(
    machine: string,
    id: string,
    columns?: number,
    rows?: number,
    cellAspect?: number,
    signal?: AbortSignal,
  ): Promise<AuditEntry> {
    const payload = await request<{ entry: AuditEntry }>(
      `/audit/detail${queryString({ machine, id, columns, rows, cell_aspect: cellAspect })}`,
      { signal },
    )
    if (payload.entry.image_preview) {
      payload.entry.image_preview = normalizePreview(payload.entry.image_preview)
    }
    return payload.entry
  },

  async sessionAuditDetail(
    machine: string,
    sessionId: string,
    id: string,
    columns?: number,
    rows?: number,
    cellAspect?: number,
    signal?: AbortSignal,
  ): Promise<AuditEntry> {
    const payload = await request<{ entry: AuditEntry }>(
      `/audit/detail${queryString({
        machine,
        scope: "session",
        session: sessionId,
        id,
        columns,
        rows,
        cell_aspect: cellAspect,
      })}`,
      { signal },
    )
    if (payload.entry.image_preview) {
      payload.entry.image_preview = normalizePreview(payload.entry.image_preview)
    }
    return payload.entry
  },

  async remotes(signal?: AbortSignal): Promise<MachinePayload> {
    return normalizeMachinePayload(await request<MachinePayload>("/remotes", { signal }))
  },

  invite(body: { name?: string; workdir?: string; ttl_s?: number }): Promise<InvitePayload> {
    return request("/remotes", {
      method: "POST",
      body: JSON.stringify(body),
    })
  },

  remoteAction<T = unknown>(action: string, body: Record<string, unknown>): Promise<T> {
    return request(`/remotes/${encodeURIComponent(action)}`, {
      method: "POST",
      body: JSON.stringify(body),
    })
  },
}

export function formatError(error: unknown): string {
  if (error instanceof Error) return error.message
  return String(error)
}
