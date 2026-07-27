import type { ScrollBoxRenderable } from "@opentui/core"
import { useKeyboard } from "@opentui/react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { api, formatError } from "./api"
import { HighlightedText } from "./syntax-highlight"
import { auditAggregationLabel, auditInput, auditOutput, formatAuditValue } from "./audit-utils"
import { EmptyState, KeyHint, Loading, Modal, Panel, useVisibleRows } from "./components"
import { truncate } from "./dashboard-utils"
import { handleSelectionScroll } from "./mouse"
import { cyclePane, scrollPaneForKey } from "./pane-navigation"
import {
  clampIndex,
  nextValue,
  sessionInventoryRequestMatches,
  sessionResourceRequestMatches,
  updateTodo,
} from "./state-utils"
import type { SessionInventoryRequest, SessionResourceRequest } from "./state-utils"
import { screenTheme, theme } from "./theme"
import { TODO_ROW_HEIGHT, todoVisibleRowCount } from "./todos-layout"
import type { AgentSession, AuditEntry, Machine, TodoItem, TodoPayload } from "./types"

const colors = screenTheme.Sessions
const VIEWS = ["Overview", "Todos", "Audit"] as const
type SessionView = (typeof VIEWS)[number]
type SessionPane = "sessions" | "content" | "audit-list" | "audit-request" | "audit-result"
const SESSION_CONTENT_PANES = ["sessions", "content"] as const satisfies readonly SessionPane[]
const SESSION_AUDIT_PANES = ["sessions", "audit-list", "audit-request", "audit-result"] as const satisfies readonly SessionPane[]

type SessionDialog =
  | { type: "none" }
  | { type: "add" }
  | { type: "edit"; item: TodoItem }
  | { type: "delete"; item: TodoItem }
  | { type: "terminate"; session: AgentSession }

const STATUS_ORDER = ["pending", "in_progress", "completed"] as const
const PRIORITY_ORDER = ["low", "medium", "high"] as const

function statusIcon(status: string): string {
  if (status === "completed") return "✓"
  if (status === "in_progress") return "◐"
  return "○"
}

function statusColor(status: string): string {
  if (status === "completed") return theme.green
  if (status === "in_progress") return theme.yellow
  return theme.muted
}

function priorityColor(priority: string): string {
  if (priority === "high") return theme.red
  if (priority === "low") return theme.faint
  return theme.blue
}

function timestamp(value?: number | null): string {
  if (!value) return "—"
  return new Date(value * 1000).toLocaleString()
}

function sessionLabel(session?: AgentSession): string {
  if (!session) return "no session"
  return session.label || session.workdir || session.session_id
}

function terminated(session?: AgentSession): boolean {
  return Boolean(session?.termination_requested || session?.termination_requested_at)
}

function auditTitle(entry?: AuditEntry): string {
  return entry?.tool || entry?.event || "Audit event"
}

function auditColor(entry?: AuditEntry): string {
  if (!entry) return theme.muted
  if (entry.ok === false || entry.status === "failed" || entry.error) return theme.red
  if (entry.ok === true || entry.status === "success") return theme.green
  return theme.yellow
}

export function SessionsScreen({
  machines,
  machine,
  onMachine,
  width,
  height,
  setStatus,
  keyboardEnabled,
  onInteractionLockChange,
}: {
  machines: Machine[]
  machine: string
  onMachine: (machine: string) => void
  width: number
  height: number
  setStatus: (message: string) => void
  keyboardEnabled: boolean
  onInteractionLockChange: (locked: boolean) => void
}) {
  const [sessions, setSessions] = useState<AgentSession[]>([])
  const [sessionId, setSessionId] = useState("")
  const sessionIdRef = useRef("")
  const [includeInactive, setIncludeInactive] = useState(false)
  const [view, setView] = useState<SessionView>("Overview")
  const [activePane, setActivePane] = useState<SessionPane>("sessions")
  const [loading, setLoading] = useState(true)
  const [loaded, setLoaded] = useState(false)
  const [dialog, setDialog] = useState<SessionDialog>({ type: "none" })

  const [todos, setTodos] = useState<TodoItem[]>([])
  const [revision, setRevision] = useState(0)
  const [todoSelected, setTodoSelected] = useState(0)
  const [todoFilter, setTodoFilter] = useState<"all" | "open" | "completed">("all")
  const [saving, setSaving] = useState(false)
  const todoState = useRef<{ todos: TodoItem[]; revision: number; sessionId: string }>({
    todos: [],
    revision: 0,
    sessionId: "",
  })
  const mutationQueue = useRef<Promise<void>>(Promise.resolve())
  const pendingMutations = useRef(0)
  const todoRequestGeneration = useRef(0)
  const selectedResourceContext = useRef({ machine, sessionId })
  selectedResourceContext.current.machine = machine
  const inventoryRequestGeneration = useRef(0)
  const inventoryContext = useRef({ machine, includeInactive })
  inventoryContext.current.machine = machine
  inventoryContext.current.includeInactive = includeInactive

  const [auditEntries, setAuditEntries] = useState<AuditEntry[]>([])
  const [auditSelected, setAuditSelected] = useState(0)
  const [auditDetail, setAuditDetail] = useState<AuditEntry | null>(null)
  const [auditLoading, setAuditLoading] = useState(false)
  const auditListRequest = useRef(0)
  const auditListController = useRef<AbortController | null>(null)
  const auditDetailRequest = useRef(0)
  const auditDetailController = useRef<AbortController | null>(null)
  const overviewScrollRef = useRef<ScrollBoxRenderable | null>(null)
  const auditRequestScrollRef = useRef<ScrollBoxRenderable | null>(null)
  const auditResultScrollRef = useRef<ScrollBoxRenderable | null>(null)

  const mounted = useRef(true)
  const currentSession = sessions.find((session) => session.session_id === sessionId)
  const onlineMachines = useMemo(
    () => machines.filter((item) => item.name === "local" || item.status === "online"),
    [machines],
  )
  const sessionIndex = Math.max(0, sessions.findIndex((session) => session.session_id === sessionId))
  const sessionRowCount = Math.max(1, Math.floor((height - 11) / 3))
  const { rows: visibleSessionRows, start: sessionStart } = useVisibleRows(
    sessions,
    sessionIndex,
    sessionRowCount,
  )
  const currentAudit = auditDetail?.id === auditEntries[auditSelected]?.id
    ? auditDetail
    : auditEntries[auditSelected]

  const visibleTodos = useMemo(() => {
    if (todoFilter === "open") return todos.filter((todo) => todo.status !== "completed")
    if (todoFilter === "completed") return todos.filter((todo) => todo.status === "completed")
    return todos
  }, [todoFilter, todos])
  const currentTodo = visibleTodos[clampIndex(todoSelected, visibleTodos.length)]
  const todoRows = todoVisibleRowCount(width, height)
  const { rows: visibleTodoRows, start: todoStart } = useVisibleRows(
    visibleTodos,
    todoSelected,
    todoRows,
  )
  const auditRows = Math.max(5, height - 15)
  const { rows: visibleAuditRows, start: auditStart } = useVisibleRows(
    auditEntries,
    auditSelected,
    auditRows,
  )

  const applyTodoPayload = useCallback((payload: TodoPayload) => {
    const nextRevision = payload.revision || 0
    todoState.current = {
      todos: payload.todos,
      revision: nextRevision,
      sessionId: payload.session_id,
    }
    if (!mounted.current) return
    setTodos(payload.todos)
    setRevision(nextRevision)
    setTodoSelected((value) => clampIndex(value, payload.todos.length))
  }, [])

  const clearResources = useCallback((nextSessionId = "") => {
    auditListRequest.current += 1
    auditListController.current?.abort()
    auditDetailRequest.current += 1
    auditDetailController.current?.abort()
    todoState.current = { todos: [], revision: 0, sessionId: nextSessionId }
    setTodos([])
    setRevision(0)
    setTodoSelected(0)
    setAuditEntries([])
    setAuditSelected(0)
    setAuditDetail(null)
    setAuditLoading(false)
  }, [])

  const loadAudit = useCallback(async (selectedSessionId: string) => {
    auditListController.current?.abort()
    const controller = new AbortController()
    auditListController.current = controller
    const requestId = ++auditListRequest.current
    if (!selectedSessionId) {
      setAuditEntries([])
      setAuditDetail(null)
      return
    }
    setAuditLoading(true)
    try {
      const payload = await api.sessionAudit(
        machine,
        selectedSessionId,
        { limit: 500, sort: "desc" },
        controller.signal,
      )
      if (requestId !== auditListRequest.current || controller.signal.aborted || !mounted.current) return
      setAuditEntries(payload.entries)
      setAuditSelected((value) => clampIndex(value, payload.entries.length))
      setStatus(`Sessions: ${selectedSessionId} · ${payload.total_matched} local Audit records`)
    } catch (error) {
      if (requestId === auditListRequest.current && !controller.signal.aborted && mounted.current) {
        setStatus(`Session Audit: ${formatError(error)}`)
      }
    } finally {
      if (requestId === auditListRequest.current && mounted.current) setAuditLoading(false)
    }
  }, [machine, setStatus])

  const loadResources = useCallback(async (selectedSessionId: string) => {
    const request: SessionResourceRequest = {
      generation: ++todoRequestGeneration.current,
      machine,
      sessionId: selectedSessionId,
    }
    selectedResourceContext.current = {
      machine: request.machine,
      sessionId: request.sessionId,
    }
    clearResources(selectedSessionId)
    if (!selectedSessionId) return
    const [todoResult] = await Promise.allSettled([
      api.todos(machine, selectedSessionId),
      loadAudit(selectedSessionId),
    ])
    const currentRequest: SessionResourceRequest = {
      generation: todoRequestGeneration.current,
      machine: selectedResourceContext.current.machine,
      sessionId: selectedResourceContext.current.sessionId,
    }
    if (!mounted.current || !sessionResourceRequestMatches(request, currentRequest)) return
    if (todoResult.status === "fulfilled") applyTodoPayload(todoResult.value)
    else if (mounted.current) setStatus(`Session Todos: ${formatError(todoResult.reason)}`)
  }, [applyTodoPayload, clearResources, loadAudit, machine, setStatus])

  const load = useCallback(async () => {
    const request: SessionInventoryRequest = {
      generation: ++inventoryRequestGeneration.current,
      machine,
      includeInactive,
    }
    const currentRequest = (): SessionInventoryRequest => ({
      generation: inventoryRequestGeneration.current,
      machine: inventoryContext.current.machine,
      includeInactive: inventoryContext.current.includeInactive,
    })
    setLoading(true)
    try {
      const payload = await api.sessions(machine, includeInactive)
      if (!mounted.current || !sessionInventoryRequestMatches(request, currentRequest())) return
      const previous = todoState.current.sessionId
      const nextSessionId = payload.sessions.some((session) => session.session_id === previous)
        ? previous
        : payload.sessions[0]?.session_id || ""
      setSessions(payload.sessions)
      sessionIdRef.current = nextSessionId
      setSessionId(nextSessionId)
      await loadResources(nextSessionId)
      if (mounted.current && sessionInventoryRequestMatches(request, currentRequest())) {
        setLoaded(true)
        setStatus(
          `Sessions: ${payload.count} ${includeInactive ? "total" : `active in ${payload.active_window_hours || 5}h`} on ${machine}`,
        )
      }
    } catch (error) {
      if (mounted.current && sessionInventoryRequestMatches(request, currentRequest())) {
        setStatus(`Sessions: ${formatError(error)}`)
      }
    } finally {
      if (mounted.current && sessionInventoryRequestMatches(request, currentRequest())) {
        setLoading(false)
      }
    }
  }, [includeInactive, loadResources, machine, setStatus])

  useEffect(() => {
    mounted.current = true
    void load()
    return () => {
      mounted.current = false
      inventoryRequestGeneration.current += 1
      todoRequestGeneration.current += 1
      auditListRequest.current += 1
      auditListController.current?.abort()
      auditDetailRequest.current += 1
      auditDetailController.current?.abort()
    }
  }, [load])

  useEffect(() => {
    onInteractionLockChange(dialog.type !== "none")
    return () => onInteractionLockChange(false)
  }, [dialog.type, onInteractionLockChange])

  useEffect(() => {
    auditDetailController.current?.abort()
    const controller = new AbortController()
    auditDetailController.current = controller
    const requestId = ++auditDetailRequest.current
    setAuditDetail(null)
    const entry = auditEntries[auditSelected]
    if (!entry?.id || !sessionId) return () => controller.abort()
    void api.sessionAuditDetail(machine, sessionId, entry.id, undefined, undefined, undefined, controller.signal)
      .then((detail) => {
        if (requestId === auditDetailRequest.current && !controller.signal.aborted && mounted.current) {
          setAuditDetail(detail)
        }
      })
      .catch((error) => {
        if (requestId === auditDetailRequest.current && !controller.signal.aborted && mounted.current) {
          setStatus(`Session Audit detail: ${formatError(error)}`)
        }
      })
    return () => controller.abort()
  }, [auditEntries, auditSelected, machine, sessionId, setStatus])

  useEffect(() => {
    overviewScrollRef.current?.scrollTo(0)
  }, [sessionId])

  useEffect(() => {
    auditRequestScrollRef.current?.scrollTo(0)
    auditResultScrollRef.current?.scrollTo(0)
  }, [currentAudit?.id])

  const selectSession = async (nextSessionId: string) => {
    if (!nextSessionId || nextSessionId === sessionIdRef.current || saving || loading) return
    sessionIdRef.current = nextSessionId
    setSessionId(nextSessionId)
    await loadResources(nextSessionId)
  }

  const cycleMachine = () => {
    const names = onlineMachines.map((item) => item.name)
    if (names.length > 1) onMachine(nextValue(machine, names))
  }

  const cycleSession = () => {
    const ids = sessions.map((session) => session.session_id)
    if (ids.length > 1) void selectSession(nextValue(sessionIdRef.current, ids))
  }

  const cycleView = () => {
    const nextView = nextValue(view, VIEWS)
    setView(nextView)
    setActivePane(nextView === "Audit" ? "audit-list" : "content")
  }

  const enqueueMutation = useCallback((
    mutate: (items: TodoItem[]) => TodoItem[],
    message?: string,
  ) => {
    pendingMutations.current += 1
    setSaving(true)
    const run = async () => {
      try {
        let base = todoState.current
        let next = mutate(base.todos)
        if (!base.sessionId) throw new Error("No agent session selected")
        let payload: TodoPayload
        try {
          payload = await api.writeTodos(next, base.revision, machine, base.sessionId)
        } catch (error) {
          const detail = formatError(error)
          if (!detail.includes("changed from revision")) throw error
          const latest = await api.todos(machine, base.sessionId)
          applyTodoPayload(latest)
          base = todoState.current
          next = mutate(base.todos)
          payload = await api.writeTodos(next, base.revision, machine, base.sessionId)
        }
        applyTodoPayload(payload)
        if (message && mounted.current) setStatus(message)
      } catch (error) {
        if (mounted.current) setStatus(`Session Todos: ${formatError(error)}`)
      } finally {
        pendingMutations.current = Math.max(0, pendingMutations.current - 1)
        if (mounted.current) setSaving(pendingMutations.current > 0)
      }
    }
    mutationQueue.current = mutationQueue.current.then(run, run)
  }, [applyTodoPayload, machine, setStatus])

  const replaceTodo = (id: string, update: Partial<TodoItem> | ((todo: TodoItem) => Partial<TodoItem>)) => {
    enqueueMutation((items) => updateTodo(items, id, update))
  }

  const addTodo = (content: string) => {
    const trimmed = content.trim()
    if (!trimmed) return
    const item: TodoItem = {
      id: `todo-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
      content: trimmed,
      status: "pending",
      priority: "medium",
    }
    setDialog({ type: "none" })
    enqueueMutation((items) => [...items, item], "Session Todo added")
  }

  const editTodo = (content: string) => {
    if (dialog.type !== "edit") return
    const trimmed = content.trim()
    if (!trimmed) return
    const id = dialog.item.id
    setDialog({ type: "none" })
    replaceTodo(id, { content: trimmed })
  }

  const confirmTerminate = async () => {
    if (dialog.type !== "terminate") return
    const target = dialog.session
    setDialog({ type: "none" })
    try {
      const payload = await api.terminateSession(machine, target.session_id)
      setSessions((current) => current.map((item) => (
        item.session_id === payload.session.session_id ? payload.session : item
      )))
      setStatus(`Sessions: ${target.session_id} marked for immediate termination`)
    } catch (error) {
      setStatus(`Session termination: ${formatError(error)}`)
    }
  }

  const selectAdjacentSession = (delta: number) => {
    const currentIndex = Math.max(0, sessions.findIndex((session) => session.session_id === sessionIdRef.current))
    const next = sessions[clampIndex(currentIndex + delta, sessions.length)]
    if (next) void selectSession(next.session_id)
  }

  const panes = view === "Audit" ? SESSION_AUDIT_PANES : SESSION_CONTENT_PANES
  const cycleActivePane = (delta = 1) => {
    setActivePane((value) => cyclePane(panes, value, delta))
  }

  const moveOrScroll = (key: { name: string; shift?: boolean }) => {
    const delta = key.name === "j" || key.name === "down" ? 1
      : key.name === "k" || key.name === "up" ? -1
      : 0
    if (activePane === "sessions") {
      if (!delta) return false
      selectAdjacentSession(delta)
      return true
    }
    if (view === "Todos" && activePane === "content") {
      if (!delta) return false
      setTodoSelected((value) => clampIndex(value + delta, visibleTodos.length))
      return true
    }
    if (view === "Audit" && activePane === "audit-list") {
      if (!delta) return false
      setAuditSelected((value) => clampIndex(value + delta, auditEntries.length))
      return true
    }
    if (view === "Audit" && activePane === "audit-request") {
      return scrollPaneForKey(auditRequestScrollRef.current, key)
    }
    if (view === "Audit" && activePane === "audit-result") {
      return scrollPaneForKey(auditResultScrollRef.current, key)
    }
    if (view === "Overview" && activePane === "content") {
      return scrollPaneForKey(overviewScrollRef.current, key)
    }
    return false
  }

  useKeyboard((key) => {
    if (!keyboardEnabled) return
    if (dialog.type === "add" || dialog.type === "edit") {
      if (key.name === "escape") setDialog({ type: "none" })
      return
    }
    if (dialog.type === "delete") {
      if (key.name === "escape" || key.name === "n") setDialog({ type: "none" })
      if (key.name === "y" || key.name === "return") {
        const id = dialog.item.id
        setDialog({ type: "none" })
        enqueueMutation((items) => items.filter((todo) => todo.id !== id), "Session Todo deleted")
      }
      return
    }
    if (dialog.type === "terminate") {
      if (key.name === "escape" || key.name === "n") setDialog({ type: "none" })
      if (key.name === "y" || key.name === "return") void confirmTerminate()
      return
    }
    if (key.name === "tab") {
      key.preventDefault()
      cycleActivePane(key.shift ? -1 : 1)
    } else if (key.name === "left") cycleActivePane(-1)
    else if (key.name === "right") cycleActivePane(1)
    else if (moveOrScroll(key)) return
    else if (key.name === "m") cycleMachine()
    else if (key.name === "i") cycleSession()
    else if (key.name === "v") cycleView()
    else if (key.name === "g") setIncludeInactive((value) => !value)
    else if (key.name === "x" && currentSession && !terminated(currentSession)) {
      setDialog({ type: "terminate", session: currentSession })
    } else if (key.name === "r") void load()
    else if (view === "Todos") {
      if (key.name === "n") setDialog({ type: "add" })
      else if (key.name === "e" && currentTodo) setDialog({ type: "edit", item: currentTodo })
      else if (key.name === "d" && currentTodo) setDialog({ type: "delete", item: currentTodo })
      else if ((key.name === "return" || key.name === "space") && currentTodo) {
        replaceTodo(currentTodo.id, (todo) => ({ status: nextValue(todo.status, STATUS_ORDER) }))
      } else if (key.name === "p" && currentTodo) {
        replaceTodo(currentTodo.id, (todo) => ({ priority: nextValue(todo.priority, PRIORITY_ORDER) }))
      } else if (key.name === "f") {
        setTodoFilter((value) => value === "all" ? "open" : value === "open" ? "completed" : "all")
        setTodoSelected(0)
      }
    }
  })

  const counts = {
    total: todos.length,
    open: todos.filter((todo) => todo.status !== "completed").length,
    completed: todos.filter((todo) => todo.status === "completed").length,
  }
  const narrow = width < 92
  const sidebarWidth = narrow ? Math.max(20, Math.floor(width * 0.28)) : 30
  const footerLocked = !keyboardEnabled || dialog.type !== "none"
  const auditInputText = currentAudit ? formatAuditValue(auditInput(currentAudit), "No input recorded") : ""
  const auditOutputText = currentAudit ? formatAuditValue(auditOutput(currentAudit), "No output recorded") : ""

  const overview = currentSession ? (
    <scrollbox
      ref={overviewScrollRef}
      focused={false}
      style={{ flexGrow: 1, minWidth: 0, minHeight: 0, gap: 1, padding: 1 }}
      scrollY
      verticalScrollbarOptions={{ visible: true }}
    >
      <box style={{ height: 2, flexDirection: "row" }}>
        <text fg={colors.accent} attributes={1} content={sessionLabel(currentSession)} />
        <box style={{ flexGrow: 1 }} />
        <text
          fg={terminated(currentSession) ? theme.red : currentSession.active === false ? theme.faint : theme.green}
          attributes={1}
          content={terminated(currentSession) ? "TERMINATION REQUESTED" : currentSession.active === false ? "INACTIVE" : "ACTIVE"}
        />
      </box>
      {[
        ["Session", currentSession.session_id],
        ["Target", currentSession.target],
        ["Machine", currentSession.machine || "local"],
        ["Workdir", currentSession.workdir],
        ["Created", timestamp(currentSession.created_at)],
        ["Last activity", timestamp(currentSession.updated_at)],
        ["Termination", currentSession.termination_requested_at ? timestamp(currentSession.termination_requested_at) : "not requested"],
      ].map(([label, value]) => (
        <box key={label} style={{ minHeight: 2, flexDirection: "row", paddingLeft: 1, paddingRight: 1, backgroundColor: theme.panelAlt }}>
          <text fg={theme.faint} content={`${label.padEnd(15)} `} />
          <text fg={theme.text} content={value} />
        </box>
      ))}
      <box style={{ flexGrow: 1 }} />
      <text fg={theme.muted} content="Todos and Audit below are scoped to this selected session. Global-only control events remain in the top-level Audit screen." />
    </scrollbox>
  ) : (
    <EmptyState title="No session selected" detail={includeInactive ? "No sessions exist on this machine" : "No session responded in the last 5 hours · press g to show all"} />
  )

  const todosView = !currentSession ? (
    <EmptyState title="No session selected" detail="Select a session before viewing Todos" />
  ) : visibleTodos.length === 0 ? (
    <EmptyState title="No matching Todos" detail="Press n to add an item" />
  ) : (
    <box
      onMouseScroll={(event) => handleSelectionScroll(
        event,
        (delta) => setTodoSelected((value) => clampIndex(value + delta, visibleTodos.length)),
      )}
      style={{ flexDirection: "column", flexGrow: 1, overflow: "hidden" }}
    >
      <box style={{ height: 2, flexDirection: "row", paddingLeft: 1 }}>
        <text fg={colors.accent} content={`${counts.total} total · ${counts.open} open · ${counts.completed} done · ${todoFilter.toUpperCase()} · rev ${revision}`} />
      </box>
      {visibleTodoRows.map((todo, offset) => {
        const index = todoStart + offset
        const active = index === todoSelected
        return (
          <box
            key={todo.id}
            onMouseDown={() => setTodoSelected(index)}
            style={{
              height: TODO_ROW_HEIGHT,
              flexShrink: 0,
              flexDirection: "row",
              alignItems: "center",
              paddingLeft: 1,
              paddingRight: 1,
              overflow: "hidden",
              backgroundColor: active ? colors.selected : index % 2 ? theme.panelAlt : undefined,
            }}
          >
            <text fg={statusColor(todo.status)} attributes={1} content={`${statusIcon(todo.status)} `} />
            <box style={{ width: 0, height: 2, flexDirection: "column", flexGrow: 1, overflow: "hidden" }}>
              <text fg={todo.status === "completed" ? theme.faint : active ? theme.text : theme.muted} attributes={active ? 1 : 0} content={todo.content} />
              <text fg={theme.faint} content={todo.id} />
            </box>
            <box style={{ width: 10, flexShrink: 0, alignItems: "center", justifyContent: "center", backgroundColor: theme.panelSoft }}>
              <text fg={priorityColor(todo.priority)} attributes={1} content={todo.priority.toUpperCase()} />
            </box>
          </box>
        )
      })}
    </box>
  )

  const auditView = !currentSession ? (
    <EmptyState title="No session selected" detail="Select a session before viewing its local Audit" />
  ) : auditLoading && auditEntries.length === 0 ? (
    <Loading label="Loading session Audit" />
  ) : auditEntries.length === 0 ? (
    <EmptyState title="No session Audit records" detail="This log contains only model tool activity owned by the selected session" />
  ) : (
    <box style={{ flexGrow: 1, flexDirection: width >= 118 ? "row" : "column", gap: 1 }}>
      <Panel
        title={`Session Audit · ${auditEntries.length}`}
        active={activePane === "audit-list"}
        accent={colors.accent}
        activeBackground={colors.panel}
        onMouseDown={() => setActivePane("audit-list")}
        style={width >= 118 ? { width: 44, flexShrink: 0, paddingTop: 1 } : { height: Math.max(8, Math.floor(height * 0.45)), paddingTop: 1 }}
      >
        <box
          onMouseScroll={(event) => handleSelectionScroll(
            event,
            (delta) => setAuditSelected((value) => clampIndex(value + delta, auditEntries.length)),
          )}
          style={{ flexDirection: "column", flexGrow: 1 }}
        >
          {visibleAuditRows.map((entry, offset) => {
            const index = auditStart + offset
            const active = index === auditSelected
            return (
              <box key={entry.id || `${entry.ts}-${index}`} onMouseDown={() => setAuditSelected(index)} style={{ height: 2, flexDirection: "column", paddingLeft: 1, backgroundColor: active ? colors.selected : index % 2 ? theme.panelAlt : undefined }}>
                <text fg={active ? theme.text : auditColor(entry)} attributes={active ? 1 : 0} content={`${new Date(entry.ts * 1000).toLocaleTimeString()} · ${auditTitle(entry)}`} />
                <text fg={theme.faint} content={`${entry.operation || "other"} · ${entry.status || (entry.ok === false ? "failed" : "recorded")}`} />
              </box>
            )
          })}
        </box>
      </Panel>
      <Panel title="Session call detail" style={{ flexGrow: 1, minHeight: 0, padding: 1, gap: 1, overflow: "hidden" }}>
        {currentAudit ? (
          <>
            <box style={{ height: 1, flexDirection: "row" }}>
              <text fg={colors.accent} attributes={1} content={auditTitle(currentAudit)} />
              <box style={{ flexGrow: 1 }} />
              <text fg={auditColor(currentAudit)} content={currentAudit.status?.toUpperCase() || "EVENT"} />
            </box>
            <text fg={theme.faint} content={`${auditAggregationLabel(currentAudit)} · ${new Date(currentAudit.ts * 1000).toLocaleString()} · ${currentAudit.operation || "other"}`} />
            <Panel
              title="Call request"
              active={activePane === "audit-request"}
              accent={colors.accent}
              activeBackground={colors.panel}
              onMouseDown={() => setActivePane("audit-request")}
              style={{ flexBasis: 0, flexGrow: 1, minHeight: 0, padding: 1, overflow: "hidden" }}
            >
              <scrollbox
                ref={auditRequestScrollRef}
                focused={false}
                style={{ flexGrow: 1, minWidth: 0, minHeight: 0 }}
                scrollY
                verticalScrollbarOptions={{ visible: true }}
              >
                <HighlightedText content={auditInputText} baseColor={theme.faint} />
              </scrollbox>
            </Panel>
            <Panel
              title="Call result"
              active={activePane === "audit-result"}
              accent={colors.accent}
              activeBackground={colors.panel}
              onMouseDown={() => setActivePane("audit-result")}
              style={{ flexBasis: 0, flexGrow: 1, minHeight: 0, padding: 1, overflow: "hidden" }}
            >
              <scrollbox
                ref={auditResultScrollRef}
                focused={false}
                style={{ flexGrow: 1, minWidth: 0, minHeight: 0 }}
                scrollY
                verticalScrollbarOptions={{ visible: true }}
              >
                <HighlightedText content={auditOutputText} baseColor={theme.muted} />
              </scrollbox>
            </Panel>
          </>
        ) : <EmptyState title="No Audit record selected" detail="Use j/k to inspect one call" />}
      </Panel>
    </box>
  )

  return (
    <box style={{ flexGrow: 1, flexDirection: "column", gap: 1 }}>
      <box style={{ height: 4, flexDirection: "row", gap: 1 }}>
        <Panel title="Machine" active accent={colors.accent} activeBackground={colors.panel} onMouseDown={cycleMachine} style={{ flexGrow: 1, alignItems: "center", justifyContent: "center" }}>
          <text fg={colors.accent} attributes={1} content={machine} />
        </Panel>
        <Panel title="Visibility" active accent={colors.accent} activeBackground={colors.panel} onMouseDown={() => setIncludeInactive((value) => !value)} style={{ flexGrow: 1, alignItems: "center", justifyContent: "center" }}>
          <text fg={includeInactive ? theme.yellow : theme.green} attributes={1} content={includeInactive ? "ALL SESSIONS" : "ACTIVE · 5H"} />
        </Panel>
        <Panel title="View" active accent={colors.accent} activeBackground={colors.panel} onMouseDown={cycleView} style={{ flexGrow: 1, alignItems: "center", justifyContent: "center" }}>
          <text fg={colors.accent} attributes={1} content={view.toUpperCase()} />
        </Panel>
      </box>
      <box style={{ flexGrow: 1, flexDirection: "row", gap: 1 }}>
        <Panel
          title={`Sessions · ${loaded ? sessions.length : "—"}${loaded && sessions.length ? ` · ${sessionStart + 1}-${sessionStart + visibleSessionRows.length}` : ""}`}
          active={activePane === "sessions"}
          accent={colors.accent}
          activeBackground={colors.panel}
          onMouseDown={() => setActivePane("sessions")}
          style={{ width: sidebarWidth, minHeight: 0, flexShrink: 0, paddingTop: 1, overflow: "hidden" }}
        >
          {!loaded ? (
            loading ? <Loading label="Loading sessions" /> : <EmptyState title="Sessions unavailable" detail="Press r to retry" />
          ) : sessions.length === 0 ? (
            <EmptyState title="No sessions" detail={includeInactive ? "No sessions exist" : "Press g to show inactive sessions"} />
          ) : (
            <box
              onMouseScroll={(event) => handleSelectionScroll(event, selectAdjacentSession)}
              style={{ flexDirection: "column", flexGrow: 1, minHeight: 0, overflow: "hidden" }}
            >
              {visibleSessionRows.map((session) => {
                const active = session.session_id === sessionId
                return (
                  <box key={session.session_id} onMouseDown={() => void selectSession(session.session_id)} style={{ height: 3, flexShrink: 0, flexDirection: "column", paddingLeft: 1, paddingRight: 1, overflow: "hidden", backgroundColor: active ? colors.selected : undefined }}>
                    <text fg={active ? theme.text : colors.accent} attributes={active ? 1 : 0} content={truncate(sessionLabel(session), Math.max(4, sidebarWidth - 4))} />
                    <text fg={terminated(session) ? theme.red : session.active === false ? theme.faint : theme.green} content={terminated(session) ? "■ TERMINATION REQUESTED" : session.active === false ? "○ inactive" : "● active"} />
                    <text fg={theme.faint} content={truncate(session.session_id, Math.max(4, sidebarWidth - 4))} />
                  </box>
                )
              })}
            </box>
          )}
        </Panel>
        <Panel
          title={`${view} · ${sessionLabel(currentSession)}`}
          active={activePane !== "sessions"}
          accent={colors.accent}
          activeBackground={colors.panel}
          onMouseDown={() => {
            if (view !== "Audit") setActivePane("content")
          }}
          style={{ flexGrow: 1, minWidth: 0, minHeight: 0, paddingTop: 1, overflow: "hidden" }}
        >
          {view === "Overview" ? overview : view === "Todos" ? todosView : auditView}
        </Panel>
      </box>
      <KeyHint
        accent={colors.accent}
        items={[
          { key: "m", label: "machine", onPress: cycleMachine, disabled: footerLocked || onlineMachines.length < 2 },
          { key: "i", label: "next session", onPress: cycleSession, disabled: footerLocked || sessions.length < 2 || saving },
          { key: "v", label: "view", onPress: cycleView, disabled: footerLocked },
          { key: "Tab", label: "pane", onPress: () => cycleActivePane(1), disabled: footerLocked },
          { key: "j", label: activePane.includes("request") || activePane.includes("result") || (view === "Overview" && activePane === "content") ? "scroll down" : "down", onPress: () => moveOrScroll({ name: "j" }), disabled: footerLocked || (activePane === "sessions" && sessions.length === 0) },
          { key: "k", label: activePane.includes("request") || activePane.includes("result") || (view === "Overview" && activePane === "content") ? "scroll up" : "up", onPress: () => moveOrScroll({ name: "k" }), disabled: footerLocked || (activePane === "sessions" && sessions.length === 0) },
          { key: "g", label: includeInactive ? "recent" : "show all", onPress: () => setIncludeInactive((value) => !value), disabled: footerLocked || loading },
          { key: "x", label: "terminate", onPress: () => currentSession && setDialog({ type: "terminate", session: currentSession }), disabled: footerLocked || !currentSession || terminated(currentSession) },
          { key: "r", label: loading ? "refreshing" : "refresh", onPress: () => void load(), disabled: footerLocked || loading || saving },
          ...(view === "Todos" ? [
            { key: "n", label: "add", onPress: () => setDialog({ type: "add" }), disabled: footerLocked || !currentSession },
            { key: "e", label: "edit", onPress: () => currentTodo && setDialog({ type: "edit", item: currentTodo }), disabled: footerLocked || !currentTodo },
            { key: "d", label: "delete", onPress: () => currentTodo && setDialog({ type: "delete", item: currentTodo }), disabled: footerLocked || !currentTodo },
            { key: "f", label: "filter", onPress: () => setTodoFilter((value) => value === "all" ? "open" : value === "open" ? "completed" : "all"), disabled: footerLocked },
          ] : []),
        ]}
      />
      {saving && (
        <box style={{ position: "absolute", right: 2, top: 4, width: 14, height: 3, border: true, borderColor: theme.yellow, backgroundColor: theme.panelAlt, alignItems: "center", justifyContent: "center" }}>
          <text fg={theme.yellow} content="Saving…" />
        </box>
      )}
      {dialog.type === "add" && (
        <Modal title="Add Session Todo" height={7}>
          <text fg={theme.muted} content="Describe the work item" />
          <box style={{ height: 3, border: true, borderColor: theme.borderBright, paddingLeft: 1, paddingRight: 1 }}>
            <input focused placeholder="What needs to be done?" onSubmit={(value: unknown) => addTodo(typeof value === "string" ? value : "")} />
          </box>
          <text fg={theme.faint} content="Enter add · Esc cancel" />
        </Modal>
      )}
      {dialog.type === "edit" && (
        <Modal title="Edit Session Todo" height={7}>
          <text fg={theme.muted} content="Update the description" />
          <box style={{ height: 3, border: true, borderColor: theme.borderBright, paddingLeft: 1, paddingRight: 1 }}>
            <input focused value={dialog.item.content} onSubmit={(value: unknown) => editTodo(typeof value === "string" ? value : "")} />
          </box>
          <text fg={theme.faint} content="Enter save · Esc cancel" />
        </Modal>
      )}
      {dialog.type === "delete" && (
        <Modal title="Delete Session Todo" height={7}>
          <text fg={theme.red} attributes={1} content="Delete this Todo?" />
          <text fg={theme.muted} content={dialog.item.content} />
          <text fg={theme.faint} content="y / Enter confirm · n / Esc cancel" />
        </Modal>
      )}
      {dialog.type === "terminate" && (
        <Modal title="Terminate Session Immediately" width={78} height={10}>
          <text fg={theme.red} attributes={1} content={`Terminate ${dialog.session.session_id}?`} />
          <text fg={theme.muted} content="This persists an irreversible stop request. Every later model tool call referencing this session will only receive instructions to stop all work and tell the user." />
          <text fg={theme.yellow} content="The session remains visible for Todo and Audit inspection." />
          <text fg={theme.faint} content="y / Enter confirm · n / Esc cancel" />
        </Modal>
      )}
    </box>
  )
}
