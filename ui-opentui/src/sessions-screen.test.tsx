import { afterEach, describe, expect, test } from "bun:test"
import { testRender } from "@opentui/react/test-utils"
import { act } from "react"
import { SessionsScreen } from "./sessions-screen"
import type { Machine } from "./types"

const originalFetch = globalThis.fetch
const renderers: Array<{ destroy: () => void }> = []

function success(data: unknown): Response {
  return new Response(JSON.stringify({ ok: true, message: "", data }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  })
}

async function renderUntil(
  setup: { renderOnce: () => Promise<void> },
  predicate: () => boolean,
  attempts = 20,
): Promise<void> {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    await act(async () => {
      await Promise.resolve()
      await setup.renderOnce()
    })
    if (predicate()) return
    await new Promise((resolve) => setTimeout(resolve, 0))
  }
  throw new Error("Timed out waiting for OpenTUI state")
}

afterEach(() => {
  globalThis.fetch = originalFetch
  const reactTestGlobal = globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }
  reactTestGlobal.IS_REACT_ACT_ENVIRONMENT = false
  for (const renderer of renderers.splice(0)) renderer.destroy()
})

describe("SessionsScreen audit loading", () => {
  test("keeps the session audit list request alive while detail selection is empty", async () => {
    let auditListSignal: AbortSignal | undefined
    let resolveAuditList: ((response: Response) => void) | undefined
    let detailCalls = 0
    const statuses: string[] = []
    const auditListResponse = new Promise<Response>((resolve) => {
      resolveAuditList = resolve
    })

    globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
      const parsed = new URL(String(input))
      const path = parsed.pathname.replace("/api/ui", "")
      if (path === "/sessions") {
        return Promise.resolve(success({
          machine: "local",
          remote: false,
          sessions: [{
            session_id: "agent001",
            target: "local",
            machine: null,
            workdir: "/workspace/project",
            created_at: 1,
            updated_at: 2,
            label: "Agent session",
            active: true,
          }],
          count: 1,
          include_inactive: false,
          active_window_hours: 5,
        }))
      }
      if (path === "/todos") {
        return Promise.resolve(success({
          machine: "local",
          session_id: "agent001",
          revision: 0,
          todos: [],
        }))
      }
      if (path === "/audit/detail") {
        detailCalls += 1
        return Promise.resolve(success({
          entry: {
            id: parsed.searchParams.get("id"),
            ts: 1,
            event: "tool_call",
            node: "local",
            operation: "files",
            tool: "read",
            status: "success",
            ok: true,
            input: { path: "README.md" },
            output: { ok: true },
          },
        }))
      }
      if (path === "/audit") {
        auditListSignal = init?.signal || undefined
        return auditListResponse
      }
      throw new Error(`Unexpected request: ${parsed.pathname}${parsed.search}`)
    }) as typeof fetch

    const machines: Machine[] = [{ name: "local", status: "online" }]
    const setup = await testRender(
      <SessionsScreen
        machines={machines}
        machine="local"
        onMachine={() => {}}
        width={120}
        height={36}
        setStatus={(message) => statuses.push(message)}
        keyboardEnabled={false}
        onInteractionLockChange={() => {}}
      />,
      { width: 120, height: 36 },
    )
    renderers.push(setup.renderer)

    await renderUntil(setup, () => auditListSignal !== undefined)
    await act(async () => {
      await Promise.resolve()
      await setup.renderOnce()
    })

    expect(auditListSignal?.aborted).toBe(false)

    resolveAuditList?.(success({
      machine: "local",
      remote: false,
      scope: "session",
      entries: [{
        id: "call:1",
        ts: 1,
        event: "tool_call",
        node: "local",
        operation: "files",
        tool: "read",
        status: "success",
        ok: true,
        session: "agent001",
      }],
      count: 1,
      total_matched: 1,
      limits: { entries: 2_000, filter_bytes: 1_024, search_bytes: 4_096 },
    }))

    await renderUntil(
      setup,
      () => detailCalls === 1 && statuses.some((message) => message.includes("1 local Audit records")),
    )

    expect(detailCalls).toBe(1)
    expect(statuses).toContainEqual(expect.stringContaining("agent001 · 1 local Audit records"))
  })

  test("aborts a stale audit list when refresh clears the selected session", async () => {
    let sessionCalls = 0
    let auditListSignal: AbortSignal | undefined
    let resolveAuditList: ((response: Response) => void) | undefined
    const statuses: string[] = []
    const auditListResponse = new Promise<Response>((resolve) => {
      resolveAuditList = resolve
    })

    globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
      const parsed = new URL(String(input))
      const path = parsed.pathname.replace("/api/ui", "")
      if (path === "/sessions") {
        sessionCalls += 1
        const sessions = sessionCalls === 1
          ? [{
              session_id: "agent001",
              target: "local",
              machine: null,
              workdir: "/workspace/project",
              created_at: 1,
              updated_at: 2,
              label: "Agent session",
              active: true,
            }]
          : []
        return Promise.resolve(success({
          machine: "local",
          remote: false,
          sessions,
          count: sessions.length,
          include_inactive: false,
          active_window_hours: 5,
        }))
      }
      if (path === "/todos") {
        return Promise.resolve(success({
          machine: "local",
          session_id: "agent001",
          revision: 0,
          todos: [],
        }))
      }
      if (path === "/audit") {
        auditListSignal = init?.signal || undefined
        return auditListResponse
      }
      throw new Error(`Unexpected request: ${parsed.pathname}${parsed.search}`)
    }) as typeof fetch

    const machines: Machine[] = [{ name: "local", status: "online" }]
    const setup = await testRender(
      <SessionsScreen
        machines={machines}
        machine="local"
        onMachine={() => {}}
        width={120}
        height={36}
        setStatus={(message) => statuses.push(message)}
        keyboardEnabled
        onInteractionLockChange={() => {}}
      />,
      { width: 120, height: 36 },
    )
    renderers.push(setup.renderer)

    await renderUntil(setup, () => auditListSignal !== undefined)
    setup.mockInput.pressKey("r")
    await renderUntil(
      setup,
      () => sessionCalls === 2 && statuses.some((message) => message.includes("0 active")),
    )

    expect(auditListSignal?.aborted).toBe(true)

    resolveAuditList?.(success({
      machine: "local",
      remote: false,
      scope: "session",
      entries: [{
        id: "call:stale",
        ts: 1,
        event: "tool_call",
        node: "local",
        operation: "files",
        tool: "read",
        status: "success",
        ok: true,
        session: "agent001",
      }],
      count: 1,
      total_matched: 1,
      limits: { entries: 2_000, filter_bytes: 1_024, search_bytes: 4_096 },
    }))
    await act(async () => {
      await Promise.resolve()
      await setup.renderOnce()
    })

    expect(statuses).not.toContainEqual(expect.stringContaining("agent001 · 1 local Audit records"))
  })
})

describe("SessionsScreen navigation and layout", () => {
  test("windows the session sidebar and selects sessions with j/k", async () => {
    const selectedResources: string[] = []
    const sessions = Array.from({ length: 14 }, (_, index) => ({
      session_id: `agent${String(index).padStart(3, "0")}`,
      target: "local" as const,
      machine: null,
      workdir: `/workspace/project-${index}`,
      created_at: index + 1,
      updated_at: index + 2,
      label: `Session ${index}`,
      active: true,
    }))

    globalThis.fetch = ((input: RequestInfo | URL) => {
      const parsed = new URL(String(input))
      const path = parsed.pathname.replace("/api/ui", "")
      if (path === "/sessions") {
        return Promise.resolve(success({
          machine: "local",
          remote: false,
          sessions,
          count: sessions.length,
          include_inactive: false,
          active_window_hours: 5,
        }))
      }
      if (path === "/todos") {
        const sessionId = parsed.searchParams.get("session_id") || ""
        selectedResources.push(sessionId)
        return Promise.resolve(success({ machine: "local", session_id: sessionId, revision: 0, todos: [] }))
      }
      if (path === "/audit") {
        return Promise.resolve(success({
          machine: "local",
          remote: false,
          scope: "session",
          entries: [],
          count: 0,
          total_matched: 0,
          limits: { entries: 2_000, filter_bytes: 1_024, search_bytes: 4_096 },
        }))
      }
      throw new Error(`Unexpected request: ${parsed.pathname}${parsed.search}`)
    }) as typeof fetch

    const setup = await testRender(
      <SessionsScreen
        machines={[{ name: "local", status: "online" }]}
        machine="local"
        onMachine={() => {}}
        width={100}
        height={24}
        setStatus={() => {}}
        keyboardEnabled
        onInteractionLockChange={() => {}}
      />,
      { width: 100, height: 24 },
    )
    renderers.push(setup.renderer)

    await renderUntil(
      setup,
      () => selectedResources.includes("agent000") && setup.captureCharFrame().includes("Sessions · 14"),
    )
    const initialFrame = setup.captureCharFrame()
    expect(initialFrame).toContain("Sessions · 14 · 1-4")
    expect(initialFrame).toContain("Session 0")
    expect(initialFrame).toContain("Session 3")
    expect(initialFrame).not.toContain("Session 4")
    expect(initialFrame).not.toContain("Session 13")

    await act(async () => {
      setup.mockInput.pressKey("j")
      await setup.renderOnce()
    })
    await renderUntil(setup, () => selectedResources.includes("agent001"))
    expect(setup.captureCharFrame()).toContain("Overview · Session 1")
  })

  test("labels paired session audit records as coalesced calls", async () => {
    let detailCalls = 0
    globalThis.fetch = ((input: RequestInfo | URL) => {
      const parsed = new URL(String(input))
      const path = parsed.pathname.replace("/api/ui", "")
      if (path === "/sessions") {
        return Promise.resolve(success({
          machine: "local",
          remote: false,
          sessions: [{
            session_id: "agent001",
            target: "local",
            machine: null,
            workdir: "/workspace/project",
            created_at: 1,
            updated_at: 2,
            label: "Agent session",
            active: true,
          }],
          count: 1,
          include_inactive: false,
          active_window_hours: 5,
        }))
      }
      if (path === "/todos") {
        return Promise.resolve(success({ machine: "local", session_id: "agent001", revision: 0, todos: [] }))
      }
      if (path === "/audit/detail") {
        detailCalls += 1
        return Promise.resolve(success({
          entry: {
            id: "call:1",
            ts: 1,
            event: "tool_call",
            node: "local",
            operation: "files",
            tool: "read",
            status: "success",
            ok: true,
            paired: true,
            source_events: ["tool_call_start", "tool_call_end"],
            input: { path: "README.md" },
            output: { ok: true },
          },
        }))
      }
      if (path === "/audit") {
        return Promise.resolve(success({
          machine: "local",
          remote: false,
          scope: "session",
          entries: [{
            id: "call:1",
            ts: 1,
            event: "tool_call",
            node: "local",
            operation: "files",
            tool: "read",
            status: "success",
            ok: true,
            paired: true,
            session: "agent001",
          }],
          count: 1,
          total_matched: 1,
          limits: { entries: 2_000, filter_bytes: 1_024, search_bytes: 4_096 },
        }))
      }
      throw new Error(`Unexpected request: ${parsed.pathname}${parsed.search}`)
    }) as typeof fetch

    const setup = await testRender(
      <SessionsScreen
        machines={[{ name: "local", status: "online" }]}
        machine="local"
        onMachine={() => {}}
        width={140}
        height={36}
        setStatus={() => {}}
        keyboardEnabled
        onInteractionLockChange={() => {}}
      />,
      { width: 140, height: 36 },
    )
    renderers.push(setup.renderer)

    await renderUntil(setup, () => detailCalls === 1)
    await act(async () => {
      setup.mockInput.pressKey("v")
      await setup.renderOnce()
    })
    await renderUntil(setup, () => setup.captureCharFrame().includes("TODOS"))
    await act(async () => {
      setup.mockInput.pressKey("v")
      await setup.renderOnce()
    })
    await renderUntil(setup, () => setup.captureCharFrame().includes("Call request"))
    const frame = setup.captureCharFrame()
    expect(frame).toContain("Coalesced call")
    expect(frame).toContain("Call request")
    expect(frame).toContain("Call result")
    expect(frame).not.toContain(" Input ")
  })
})
