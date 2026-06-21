import { AlertTriangle, RotateCcw } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import type { ErrorInfo, RunEvent } from "@/lib/api/schemas"
import { nodeLabel } from "@/lib/format"

const KIND_COPY: Record<ErrorInfo["kind"], string> = {
  ToolError: "A tool call failed at the transport level. These are retried automatically.",
  ModelError: "The model call failed or returned something unusable.",
  PolicyViolation: "An agent tried something its handoff contract or tool allowlist does not permit. Not retried.",
  BudgetExceeded: "The run hit its token or spend cap. Fork from an earlier checkpoint with a larger budget to continue.",
  InternalError: "An unexpected error. Check the worker logs.",
}

type Retry = { node: string; attempt: number; kind: string; message: string }

function retries(events: RunEvent[]): Retry[] {
  return events
    .filter((event) => event.type === "node.failed" && event.payload.will_retry === true)
    .map((event) => {
      const error = (event.payload.error ?? {}) as Record<string, unknown>
      return {
        node: String(event.payload.node ?? "unknown"),
        attempt: Number(event.payload.attempt ?? 1),
        kind: String(error.kind ?? "Error"),
        message: String(error.message ?? ""),
      }
    })
}

export function RunErrorAlert({ error }: { error: ErrorInfo | null }) {
  if (!error) return null
  return (
    <div role="alert" className="flex gap-3 rounded-xl border border-destructive/30 bg-destructive/5 p-4">
      <AlertTriangle className="mt-0.5 size-[18px] shrink-0 text-destructive" strokeWidth={1.75} aria-hidden />
      <div className="space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="destructive">{error.kind}</Badge>
          {error.node ? <span className="text-[13px] text-muted-foreground">in {nodeLabel(error.node)}</span> : null}
        </div>
        <p className="text-[14px] font-medium">{error.message}</p>
        <p className="text-[13px] text-muted-foreground">{KIND_COPY[error.kind]}</p>
      </div>
    </div>
  )
}

export function RetryList({ events }: { events: RunEvent[] }) {
  const retried = retries(events)
  if (retried.length === 0) return null
  return (
    <section className="rounded-xl border border-border/60 bg-card p-5 shadow-xs" aria-label="Retries">
      <h3 className="mb-1 flex items-center gap-2 text-[15px] font-semibold">
        <RotateCcw className="size-4 text-warning" strokeWidth={1.75} aria-hidden />
        Retried within budget
      </h3>
      <p className="mb-3 text-[13px] text-muted-foreground">Transient failures the node retry policy absorbed.</p>
      <ul className="divide-y divide-border/70 text-[13px]">
        {retried.map((retry, index) => (
          <li key={`${retry.node}-${retry.attempt}-${index}`} className="py-2">
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium">{nodeLabel(retry.node)}</span>
              <span className="text-xs text-muted-foreground tabular-nums">attempt {retry.attempt}</span>
            </div>
            <p className="truncate text-xs text-muted-foreground" title={retry.message}>
              {retry.kind}: {retry.message}
            </p>
          </li>
        ))}
      </ul>
    </section>
  )
}
