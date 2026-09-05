import type { Machine } from "./types"

export function remoteVersion(machine: Machine): string {
  const version = machine.info?.workgate_version
  return typeof version === "string" && version.trim() ? version : "—"
}

export function remoteSystemInfo(machine: Machine): Record<string, unknown> {
  const info = { ...(machine.info || {}) }
  delete info.workgate_version
  return info
}
