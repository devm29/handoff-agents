import { describe, expect, it } from "vitest"

import type { RunEvent } from "@/lib/api/schemas"
import { deriveActivity, describeEvent, edgeId } from "@/lib/graph-status"

let id = 0
function event(type: string, payload: Record<string, unknown>): RunEvent {
  id += 1
  return { id, run_id: "run", type, payload, created_at: new Date(2026, 0, 1, 0, 0, id).toISOString() }
}

describe("deriveActivity", () => {
  it("tracks a node through retry and completion", () => {
    const events = [
      event("node.started", { node: "supervisor", attempt: 1 }),
      event("node.completed", { node: "supervisor", attempt: 1, duration_ms: 12 }),
      event("handoff", { target: "researcher" }),
      event("node.started", { node: "researcher", attempt: 1 }),
      event("node.failed", { node: "researcher", attempt: 1, will_retry: true, error: { kind: "ModelError", message: "529" } }),
      event("node.started", { node: "researcher", attempt: 2 }),
    ]
    const mid = deriveActivity(events, "running")
    expect(mid.nodes.researcher?.status).toBe("retrying")
    expect(mid.nodes.researcher?.attempt).toBe(2)
    expect(mid.activeEdge).toBe(edgeId("supervisor", "researcher"))
    expect(mid.traversed.has(edgeId("__start__", "supervisor"))).toBe(true)

    const done = deriveActivity([...events, event("node.completed", { node: "researcher", duration_ms: 40 })], "running")
    expect(done.nodes.researcher).toMatchObject({ status: "done", executions: 1, lastDurationMs: 40, error: null })
    expect(done.activeEdge).toBe(edgeId("researcher", "supervisor"))
  })

  it("marks the approval gate as waiting and maps finish to the end node", () => {
    const activity = deriveActivity(
      [event("approval.requested", { assignee: "analyst" }), event("handoff", { target: "finish" })],
      "awaiting_approval",
    )
    expect(activity.nodes.approval?.status).toBe("waiting")
    expect(activity.traversed.has(edgeId("supervisor", "__end__"))).toBe(true)
  })

  it("settles in-flight nodes once the run is terminal", () => {
    const events = [event("node.started", { node: "risk_analyst", attempt: 1 })]
    expect(deriveActivity(events, "failed").nodes.risk_analyst?.status).toBe("failed")
    expect(deriveActivity(events, "cancelled").nodes.risk_analyst?.status).toBe("idle")
    expect(deriveActivity(events, "failed").activeEdge).toBeNull()
  })
})

describe("describeEvent", () => {
  it("summarises tool calls and failures", () => {
    expect(describeEvent(event("tool.call", { agent: "researcher", tool: "news_search", ok: true, duration_ms: 8 }))).toEqual({
      title: "researcher called news_search",
      detail: "ok in 8 ms",
      tone: "neutral",
    })
    const failure = describeEvent(
      event("node.failed", { node: "compliance_checker", will_retry: false, error: { kind: "BudgetExceeded", message: "cap" } }),
    )
    expect(failure.tone).toBe("destructive")
    expect(failure.title).toContain("BudgetExceeded")
  })

  it("explains recovery after a crash", () => {
    const recovered = describeEvent(event("run.status", { status: "running", recovered: true, claims: 2 }))
    expect(recovered.detail).toBe("Recovered from the last checkpoint (claim 2)")
  })
})
