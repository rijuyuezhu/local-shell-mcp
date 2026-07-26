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
})
