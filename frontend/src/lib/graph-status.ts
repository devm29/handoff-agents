import type { RunEvent, RunStatus } from "@/lib/api/schemas"

export type NodeStatus = "idle" | "running" | "retrying" | "waiting" | "done" | "failed"

export type NodeActivity = {
  status: NodeStatus
  executions: number
  attempt: number
  lastDurationMs: number | null
  error: { kind: string; message: string } | null
}

export type GraphActivity = {
  nodes: Record<string, NodeActivity>
  traversed: Set<string>
  activeEdge: string | null
}

const TERMINAL: ReadonlySet<RunStatus> = new Set(["completed", "rejected", "failed", "cancelled"])

export function edgeId(source: string, target: string): string {
  return `${source}->${target}`
}

function blank(): NodeActivity {
  return { status: "idle", executions: 0, attempt: 0, lastDurationMs: null, error: null }
}

function str(value: unknown): string | null {
  return typeof value === "string" ? value : null
}

function num(value: unknown): number | null {
  return typeof value === "number" ? value : null
}

export function deriveActivity(events: readonly RunEvent[], runStatus: RunStatus): GraphActivity {
  const nodes: Record<string, NodeActivity> = {}
  const traversed = new Set<string>()
  let activeEdge: string | null = null
  const node = (name: string): NodeActivity => (nodes[name] ??= blank())

  for (const event of events) {
    const name = str(event.payload.node)
    switch (event.type) {
      case "node.started": {
        if (!name) break
        const target = node(name)
        target.attempt = num(event.payload.attempt) ?? 1
        target.status = target.attempt > 1 ? "retrying" : "running"
        if (name === "supervisor" && target.executions === 0) {
          traversed.add(edgeId("__start__", "supervisor"))
          node("__start__").status = "done"
        }
        break
      }
      case "node.completed": {
        if (!name) break
        const target = node(name)
        target.status = "done"
        target.executions += 1
        target.lastDurationMs = num(event.payload.duration_ms)
        target.error = null
        if (name !== "supervisor") {
          traversed.add(edgeId(name, "supervisor"))
          activeEdge = edgeId(name, "supervisor")
        }
        break
      }
      case "node.failed": {
        if (!name) break
        const target = node(name)
        const error = event.payload.error
        if (error && typeof error === "object") {
          const record = error as Record<string, unknown>
          target.error = { kind: str(record.kind) ?? "InternalError", message: str(record.message) ?? "" }
        }
        target.status = event.payload.will_retry === true ? "retrying" : "failed"
        break
      }
      case "handoff": {
        const goal = str(event.payload.target)
        if (!goal) break
        const destination = goal === "finish" ? "__end__" : goal
        traversed.add(edgeId("supervisor", destination))
        activeEdge = edgeId("supervisor", destination)
        break
      }
      case "approval.requested":
        node("approval").status = "waiting"
        break
      case "run.status": {
        const status = str(event.payload.status)
        if (status === "completed" || status === "rejected") node("__end__").status = "done"
        break
      }
      default:
        break
    }
  }

  if (TERMINAL.has(runStatus)) {
    for (const activity of Object.values(nodes)) {
      if (activity.status === "running" || activity.status === "retrying") {
        activity.status = runStatus === "failed" ? "failed" : "idle"
      }
    }
    activeEdge = null
  }
  return { nodes, traversed, activeEdge }
}

export type EventTone = "info" | "success" | "warning" | "destructive" | "neutral"

export function describeEvent(event: RunEvent): { title: string; detail: string | null; tone: EventTone } {
  const p = event.payload
  const node = str(p.node)
  switch (event.type) {
    case "run.status": {
      const status = str(p.status) ?? "unknown"
      const tone: EventTone =
        status === "completed" ? "success" : status === "failed" || status === "rejected" ? "destructive" : "neutral"
      const detail =
        p.recovered === true
          ? `Recovered from the last checkpoint (claim ${num(p.claims) ?? 1})`
          : p.resuming_approval === true
            ? "Resumed with the reviewer's decision"
            : null
      return { title: `Run ${status.replaceAll("_", " ")}`, detail, tone }
    }
    case "node.started":
      return {
        title: `${node ?? "Node"} started`,
        detail: (num(p.attempt) ?? 1) > 1 ? `Attempt ${num(p.attempt)}` : null,
        tone: "info",
      }
    case "node.completed":
      return { title: `${node ?? "Node"} completed`, detail: `${num(p.duration_ms) ?? 0} ms`, tone: "success" }
    case "node.failed": {
      const error = (p.error ?? {}) as Record<string, unknown>
      return {
        title: `${node ?? "Node"} failed: ${str(error.kind) ?? "error"}`,
        detail: `${str(error.message) ?? ""}${p.will_retry === true ? " (retrying)" : ""}`,
        tone: p.will_retry === true ? "warning" : "destructive",
      }
    }
    case "handoff":
      return { title: `Handoff to ${str(p.target) ?? "?"}`, detail: str(p.task), tone: "info" }
    case "tool.call":
      return {
        title: `${str(p.agent) ?? "agent"} called ${str(p.tool) ?? "tool"}`,
        detail: `${p.ok === true ? "ok" : "error"} in ${num(p.duration_ms) ?? 0} ms`,
        tone: p.ok === true ? "neutral" : "warning",
      }
    case "llm.call":
      return {
        title: `${str(p.agent) ?? "agent"} model call`,
        detail: `${num(p.input_tokens) ?? 0} in / ${num(p.output_tokens) ?? 0} out tokens, $${(num(p.cost_usd) ?? 0).toFixed(4)}`,
        tone: "neutral",
      }
    case "approval.requested":
      return { title: "Approval requested", detail: `Assigned to ${str(p.assignee) ?? "reviewer"}`, tone: "warning" }
    case "approval.escalated":
      return { title: "Approval escalated", detail: `${str(p.from) ?? "?"} to ${str(p.to) ?? "?"}`, tone: "warning" }
    case "approval.decided":
      return {
        title: `Reviewer chose ${str(p.action) ?? "?"}`,
        detail: str(p.reviewer),
        tone: p.action === "reject" ? "destructive" : "success",
      }
    default:
      return { title: event.type, detail: null, tone: "neutral" }
  }
}
