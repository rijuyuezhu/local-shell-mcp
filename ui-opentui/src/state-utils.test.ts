import { describe, expect, test } from "bun:test"
import {
  clampIndex,
  nextPreviewMeasurement,
  nextValue,
  payloadMatches,
  scopedItems,
  sessionInventoryRequestMatches,
  sessionResourceRequestMatches,
  updateTodo,
} from "./state-utils"

describe("clampIndex", () => {
  test("never produces a negative selection for an empty list", () => {
    expect(clampIndex(3, 0)).toBe(0)
    expect(clampIndex(-1, 0)).toBe(0)
  })

  test("keeps selection inside a non-empty list", () => {
    expect(clampIndex(-2, 3)).toBe(0)
    expect(clampIndex(8, 3)).toBe(2)
  })
})

describe("preview measurement", () => {
  test("accepts only the first layout measurement for one viewport", () => {
    expect(nextPreviewMeasurement("", "120x40:split", 42.8, 27.2)).toEqual({
      viewport: "120x40:split",
      columns: 42,
      rows: 26,
    })
    expect(nextPreviewMeasurement("120x40:split", "120x40:split", 41, 26)).toBeNull()
  })

  test("measures again after the terminal viewport changes", () => {
    expect(nextPreviewMeasurement("120x40:split", "121x40:split", 43, 27)).toEqual({
      viewport: "121x40:split",
      columns: 43,
      rows: 26,
    })
  })
})

describe("todo mutations", () => {
  const todos = [{ id: "a", content: "A", status: "pending", priority: "medium" }]

  test("cycles unknown and known values safely", () => {
    expect(nextValue("pending", ["pending", "in_progress", "completed"] as const)).toBe("in_progress")
    expect(nextValue("unknown", ["low", "medium", "high"] as const)).toBe("low")
  })

  test("applies updates to the latest matching item", () => {
    expect(updateTodo(todos, "a", (todo) => ({ content: `${todo.content}!` }))[0]!.content).toBe("A!")
    expect(updateTodo(todos, "missing", { content: "ignored" })).toEqual(todos)
  })
})


describe("machine-scoped state", () => {
  test("hides items from a previous machine immediately", () => {
    expect(scopedItems("worker-a", "worker-b", ["stale"])).toEqual([])
    expect(scopedItems("worker-a", "worker-a", ["current"])).toEqual(["current"])
  })

  test("accepts file payloads only for the current machine and path", () => {
    const payload = { machine: "worker-a", path: "src" }
    expect(payloadMatches(payload, "worker-a", "src")).toBe(true)
    expect(payloadMatches(payload, "worker-b", "src")).toBe(false)
    expect(payloadMatches(payload, "worker-a", ".")).toBe(false)
  })

  test("rejects stale session resource responses", () => {
    const request = { generation: 3, machine: "worker-a", sessionId: "session-a" }
    expect(sessionResourceRequestMatches(request, request)).toBe(true)
    expect(sessionResourceRequestMatches(request, { ...request, generation: 4 })).toBe(false)
    expect(sessionResourceRequestMatches(request, { ...request, machine: "worker-b" })).toBe(false)
    expect(sessionResourceRequestMatches(request, { ...request, sessionId: "session-b" })).toBe(false)
  })

  test("rejects stale session inventory responses", () => {
    const request = { generation: 5, machine: "worker-a", includeInactive: false }
    expect(sessionInventoryRequestMatches(request, request)).toBe(true)
    expect(sessionInventoryRequestMatches(request, { ...request, generation: 6 })).toBe(false)
    expect(sessionInventoryRequestMatches(request, { ...request, machine: "worker-b" })).toBe(false)
    expect(sessionInventoryRequestMatches(request, { ...request, includeInactive: true })).toBe(false)
  })
})
