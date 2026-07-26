import { describe, expect, test } from "bun:test"
import {
  DOUBLE_CLICK_WINDOW_MS,
  fileListJumpTarget,
  isDoubleClick,
  pathBreadcrumbs,
  selectionIndexForPath,
} from "./file-navigation"

describe("file pointer navigation", () => {
  test("requires two presses on the same item within the double-click window", () => {
    const first = { target: "src", at: 1_000 }
    expect(isDoubleClick(first, "src", 1_000 + DOUBLE_CLICK_WINDOW_MS)).toBe(true)
    expect(isDoubleClick(first, "tests", 1_100)).toBe(false)
    expect(isDoubleClick(first, "src", 1_000 + DOUBLE_CLICK_WINDOW_MS + 1)).toBe(false)
    expect(isDoubleClick(first, "src", 999)).toBe(false)
  })

  test("restores the clicked preview entry by its full path", () => {
    const entries = [
      { path: "src/index.ts" },
      { path: "src/components/index.ts" },
    ]
    expect(selectionIndexForPath(entries, "src/components/index.ts")).toBe(1)
    expect(selectionIndexForPath(entries, "src/missing.ts")).toBeNull()
  })

  test("applies g/G jumps only to the active list pane", () => {
    expect(fileListJumpTarget({ name: "g" }, "list", 4)).toBe(0)
    expect(fileListJumpTarget({ name: "g", shift: true }, "list", 4)).toBe(3)
    expect(fileListJumpTarget({ name: "g" }, "preview", 4)).toBeNull()
    expect(fileListJumpTarget({ name: "g", shift: true }, "preview", 4)).toBeNull()
    expect(fileListJumpTarget({ name: "x" }, "list", 4)).toBeNull()
  })
})

describe("file path breadcrumbs", () => {
  test("builds workspace-relative breadcrumbs", () => {
    expect(pathBreadcrumbs("src/local_shell_mcp/ui/static")).toEqual([
      { label: ".", path: "." },
      { label: "src", path: "src" },
      { label: "local_shell_mcp", path: "src/local_shell_mcp" },
      { label: "ui", path: "src/local_shell_mcp/ui" },
      { label: "static", path: "src/local_shell_mcp/ui/static" },
    ])
  })

  test("builds absolute POSIX breadcrumbs", () => {
    expect(pathBreadcrumbs("/var/lib/lsm")).toEqual([
      { label: "/", path: "/" },
      { label: "var", path: "/var" },
      { label: "lib", path: "/var/lib" },
      { label: "lsm", path: "/var/lib/lsm" },
    ])
  })

  test("builds Windows drive and UNC breadcrumbs", () => {
    expect(pathBreadcrumbs("C:\\Users\\agent")).toEqual([
      { label: "C:\\", path: "C:\\" },
      { label: "Users", path: "C:\\Users" },
      { label: "agent", path: "C:\\Users\\agent" },
    ])
    expect(pathBreadcrumbs("\\\\server\\share\\folder")).toEqual([
      { label: "\\\\server\\share", path: "\\\\server\\share" },
      { label: "folder", path: "\\\\server\\share\\folder" },
    ])
  })
})
