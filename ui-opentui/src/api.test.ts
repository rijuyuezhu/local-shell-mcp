import { afterEach, describe, expect, test } from "bun:test"
import { API_BASE, api, formatError } from "./api"

const originalFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = originalFetch
})

function success(data: unknown = { value: true }): Response {
  return new Response(JSON.stringify({ ok: true, message: "", data }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  })
}

function forkPayload(url: string, init?: RequestInit): unknown {
  const parsed = new URL(url)
  const path = parsed.pathname.replace("/api/ui", "")
  if (path === "/bootstrap") {
    return {
      version: { version: "3.9.1" },
      ui: { features: { remotes: true, wallpaper: "aurora" } },
      machines: [{ name: "local", status: "online" }],
      counts: { online: 1, offline: 0, total: 1 },
    }
  }
  if (path === "/dashboard") {
    return {
      generated_at: 10,
      health: "healthy",
      version: { version: "3.9.1" },
      system: { timestamp: 10, cpu_percent: 2 },
      alerts: [],
      activity: [],
      audit_total_24h: 4,
    }
  }
  if (path === "/machines") {
    return {
      machines: [{ name: "local", status: "online" }],
      counts: { online: 1, offline: 0, total: 1 },
    }
  }
  if (path === "/terminals") {
    return {
      machine: parsed.searchParams.get("machine") || "local",
      shells: [{ shell_id: "shell-1", name: "demo", cwd: ".", command: null }],
    }
  }
  if (path === "/terminals/read") {
    return { shell_id: parsed.searchParams.get("shell_id"), output: "ready" }
  }
  if (path.startsWith("/terminals/")) {
    const body = JSON.parse(String(init?.body || "{}")) as Record<string, unknown>
    return { ...body, shell_id: body.shell_id || "shell-2" }
  }
  if (path === "/todos") {
    if (init?.method === "PUT") {
      const body = JSON.parse(String(init.body)) as Record<string, unknown>
      return { machine: body.machine, revision: 8, todos: body.todos }
    }
    return {
      machine: parsed.searchParams.get("machine") || "local",
      revision: 7,
      todos: [{ id: "a", content: "A", status: "pending", priority: "medium" }],
    }
  }
  if (path === "/files") {
    const directory = parsed.searchParams.get("path") || "."
    return {
      machine: parsed.searchParams.get("machine") || "local",
      path: directory,
      parent: ".",
      entries: [{ path: `${directory}/entry`, name: "entry", type: "file" }],
      mutations: { write: true, delete: true, copy: true, move: true, rename: true, mkdir: true },
    }
  }
  if (path === "/files/preview") {
    return { kind: "text", content: "hello", media_type: "text/plain", file_sha256: "a".repeat(64) }
  }
  if (path === "/files/content") {
    return { kind: "text", content: "hello", file_sha256: "b".repeat(64) }
  }
  if (path.startsWith("/files/")) return { action: path.slice("/files/".length) }
  if (path === "/audit/detail") {
    return {
      entry: {
        id: parsed.searchParams.get("id"),
        ts: 1,
        event: "tool_result",
        node: parsed.searchParams.get("machine") || "local",
        operation: "files",
      },
    }
  }
  if (path === "/audit") {
    return { entries: [], count: 0, total_matched: 0, machine: parsed.searchParams.get("machine") }
  }
  if (path === "/remotes") {
    if (init?.method === "POST") return { command: "join", expires_at: 20, ttl_s: 60 }
    return { machines: [], counts: { online: 0, offline: 0, total: 0 }, enabled: true }
  }
  if (path.startsWith("/remotes/")) return { ok: true }
  return { value: true }
}

describe("fork API adapter", () => {
  test("normalizes shared Human UI responses", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = []
    globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      calls.push({ url, init })
      return success(forkPayload(url, init))
    }) as unknown as typeof fetch

    const bootstrap = await api.bootstrap()
    const dashboard = await api.dashboard()
    const files = await api.files("worker a", "src path")
    const preview = await api.filePreview("local", "", 80, 24, 2.75)
    const content = await api.fileContent("local", "a/b")
    const terminals = await api.terminals("worker a")
    const read = await api.terminalRead("worker a", "shell-1", 25)
    const detail = await api.auditDetail("worker a", "call:abc/123")

    expect(bootstrap.machines.machines[0]?.name).toBe("local")
    expect(bootstrap.features.wallpaper).toBe("aurora")
    expect(dashboard.session_count).toBe(1)
    expect(dashboard.todo_counts).toEqual({ total: 1, open: 1 })
    expect(files.parent_entries[0]?.name).toBe("entry")
    expect(preview.mime_type).toBe("text/plain")
    expect(preview.sha256).toBe("a".repeat(64))
    expect(content.sha256).toBe("b".repeat(64))
    expect(terminals.sessions[0]).toMatchObject({ session_id: "shell-1", name: "demo" })
    expect(read).toEqual({ session_id: "shell-1", output: "ready" })
    expect(detail.node).toBe("worker a")

    const urls = calls.map((call) => call.url)
    expect(urls).toContain(`${API_BASE}/files?machine=worker+a&path=src+path`)
    expect(urls).toContain(`${API_BASE}/files?machine=worker+a&path=.`)
    expect(urls).toContain(`${API_BASE}/terminals/read?machine=worker+a&shell_id=shell-1&lines=25`)
    expect(urls).toContain(`${API_BASE}/audit/detail?machine=worker+a&id=call%3Aabc%2F123`)
    expect(calls.every((call) => new Headers(call.init?.headers).get("Accept") === "application/json")).toBe(true)
  })

  test("maps fork action fields without shell interpolation", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = []
    globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      calls.push({ url, init })
      return success(forkPayload(url, init))
    }) as unknown as typeof fetch

    await api.fileAction("touch", { machine: "local", path: "new.txt" })
    await api.fileAction("rename", { machine: "local", path: "old", destination: "dir/new" })
    await api.terminalAction("send", { machine: "local", session_id: "s", input_text: "x" })
    await api.writeTodos(
      [{ id: "a", content: "A", status: "pending", priority: "medium" }],
      7,
    )
    await api.audit({ node: "worker a", empty: "", zero: 0, enabled: false, omitted: null })

    expect(calls[0]?.url).toBe(`${API_BASE}/files/write`)
    expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({
      machine: "local",
      path: "new.txt",
      content: "",
      overwrite: false,
    })
    expect(JSON.parse(String(calls[1]?.init?.body))).toEqual({
      machine: "local",
      path: "old",
      name: "new",
    })
    expect(JSON.parse(String(calls[2]?.init?.body))).toEqual({
      machine: "local",
      shell_id: "s",
      input_text: "x",
    })
    expect(JSON.parse(String(calls[3]?.init?.body))).toMatchObject({
      machine: "local",
      expected_revision: 7,
    })
    expect(calls[4]?.url).toBe(`${API_BASE}/audit?zero=0&enabled=false&machine=worker+a`)
  })

  test("propagates an already-aborted external signal", async () => {
    const external = new AbortController()
    external.abort(new Error("cancelled"))
    let observed: AbortSignal | undefined
    globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
      observed = init?.signal as AbortSignal
      return success(forkPayload(String(_input), init))
    }) as unknown as typeof fetch

    await api.files("local", ".", external.signal)

    expect(observed?.aborted).toBe(true)
    expect((observed?.reason as Error).message).toBe("cancelled")
  })
})

describe("API response handling", () => {
  test("uses server message or error for failed envelopes", async () => {
    globalThis.fetch = (async () =>
      new Response(JSON.stringify({ ok: false, message: "conflict", error: "fallback" }), {
        status: 409,
        statusText: "Conflict",
      })) as unknown as typeof fetch
    expect(api.todos()).rejects.toThrow("conflict")

    globalThis.fetch = (async () =>
      new Response(JSON.stringify({ ok: false, message: "", error: "typed-error" }), {
        status: 400,
        statusText: "Bad Request",
      })) as unknown as typeof fetch
    expect(api.todos()).rejects.toThrow("typed-error")
  })

  test("reports status text when JSON is unavailable or the envelope has no detail", async () => {
    globalThis.fetch = (async () =>
      new Response("not-json", { status: 502, statusText: "Bad Gateway" })) as unknown as typeof fetch
    expect(api.todos()).rejects.toThrow("502 Bad Gateway")

    globalThis.fetch = (async () =>
      new Response(JSON.stringify({ ok: true, data: null }), {
        status: 503,
        statusText: "Unavailable",
      })) as unknown as typeof fetch
    expect(api.todos()).rejects.toThrow("503 Unavailable")
  })
})

describe("formatError", () => {
  test("formats Error instances and arbitrary values", () => {
    expect(formatError(new Error("boom"))).toBe("boom")
    expect(formatError(42)).toBe("42")
    expect(formatError(null)).toBe("null")
  })
})
