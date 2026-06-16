import type { RunEvent } from "@/lib/api/schemas"
import { describeEvent, type EventTone } from "@/lib/graph-status"
import { cn } from "@/lib/utils"

const DOT: Record<EventTone, string> = {
  info: "bg-primary",
  success: "bg-success",
  warning: "bg-warning",
  destructive: "bg-destructive",
  neutral: "bg-muted-foreground/50",
}

const time = new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit", second: "2-digit" })

export function ActivityFeed({ events, filter }: { events: RunEvent[]; filter: string | null }) {
  const visible = events
    .filter((event) => {
      if (filter === null) return true
      const { node, agent } = event.payload
      return node === filter || agent === filter || (event.type === "handoff" && event.payload.target === filter)
    })
    .slice()
    .reverse()
  if (visible.length === 0) {
    return <p className="px-2 py-8 text-center text-[13px] text-muted-foreground">Events appear here as the worker runs.</p>
  }
  return (
    <ol className="divide-y divide-border/70" aria-label="Run activity, newest first">
      {visible.slice(0, 300).map((event) => {
        const { title, detail, tone } = describeEvent(event)
        return (
          <li key={event.id} className="flex items-start gap-3 px-1 py-2">
            <span className={cn("mt-[7px] size-1.5 shrink-0 rounded-full", DOT[tone])} aria-hidden />
            <div className="min-w-0 flex-1">
              <p className="text-[13px] leading-5">{title}</p>
              {detail ? <p className="truncate text-xs text-muted-foreground" title={detail}>{detail}</p> : null}
            </div>
            <time className="shrink-0 text-[11px] text-muted-foreground tabular-nums" dateTime={event.created_at}>
              {time.format(new Date(event.created_at))}
            </time>
          </li>
        )
      })}
    </ol>
  )
}

const ANNOUNCED = new Set(["run.status", "approval.requested", "approval.decided", "approval.escalated"])

/** Screen readers hear status changes and approvals, not every model call. */
export function RunAnnouncer({ events }: { events: RunEvent[] }) {
  const latest = events.findLast((event) => ANNOUNCED.has(event.type))
  const message = latest ? describeEvent(latest).title : ""
  return (
    <p className="sr-only" aria-live="polite" aria-atomic="true">
      {message}
    </p>
  )
}
