"use client"

import { GitBranch, PauseCircle } from "lucide-react"

import { Skeleton } from "@/components/ui/skeleton"
import type { CheckpointSummary } from "@/lib/api/schemas"
import { formatUsd, nodeLabel } from "@/lib/format"
import { cn } from "@/lib/utils"

function offset(first: string | null, current: string | null): string {
  if (!first || !current) return ""
  const ms = new Date(current).getTime() - new Date(first).getTime()
  return ms < 1000 ? `+${Math.max(0, ms)} ms` : `+${(ms / 1000).toFixed(1)} s`
}

export function CheckpointTimeline({
  checkpoints,
  loading,
  onOpen,
}: {
  checkpoints: CheckpointSummary[] | undefined
  loading: boolean
  onOpen: (checkpoint: CheckpointSummary) => void
}) {
  if (loading) {
    return (
      <div className="space-y-2 p-4">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    )
  }
  if (!checkpoints || checkpoints.length === 0) {
    return <p className="px-5 py-8 text-center text-[13px] text-muted-foreground">No checkpoints yet. The worker writes one after every step.</p>
  }
  const first = checkpoints[0]?.created_at ?? null
  return (
    <ol className="relative px-2 py-2" aria-label="Checkpoints">
      {checkpoints.map((checkpoint, index) => {
        const last = index === checkpoints.length - 1
        const title =
          checkpoint.produced_by === "input"
            ? "Run input"
            : checkpoint.produced_by === "fork"
              ? "Forked state"
              : `After ${nodeLabel(checkpoint.produced_by)}`
        return (
          <li key={checkpoint.checkpoint_id} className="relative">
            {!last ? <span className="absolute top-8 bottom-0 left-[23px] w-px bg-border" aria-hidden /> : null}
            <button
              type="button"
              onClick={() => onOpen(checkpoint)}
              className="group flex w-full items-start gap-3 rounded-lg px-2.5 py-2 text-left transition-colors duration-150 outline-none hover:bg-accent/60 focus-visible:ring-4 focus-visible:ring-ring"
            >
              <span
                className={cn(
                  "relative z-10 mt-0.5 flex size-[22px] shrink-0 items-center justify-center rounded-full border bg-card text-[10px] font-semibold tabular-nums",
                  checkpoint.interrupted ? "border-warning text-warning" : last ? "border-primary text-primary" : "border-border text-muted-foreground",
                )}
              >
                {checkpoint.interrupted ? <PauseCircle className="size-3.5" strokeWidth={2} aria-hidden /> : checkpoint.step < 0 ? "in" : checkpoint.step}
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center justify-between gap-2">
                  <span className="truncate text-[13px] font-medium">{title}</span>
                  <span className="shrink-0 text-[11px] text-muted-foreground tabular-nums">
                    {offset(first, checkpoint.created_at)}
                  </span>
                </span>
                <span className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
                  <span className="truncate">
                    {checkpoint.interrupted
                      ? "Paused for approval"
                      : checkpoint.next.length > 0
                        ? `Next: ${checkpoint.next.map(nodeLabel).join(", ")}`
                        : "Finished"}
                  </span>
                  <span className="shrink-0 tabular-nums">{formatUsd(checkpoint.cost_usd)}</span>
                </span>
              </span>
              <GitBranch
                className="mt-1 size-3.5 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100"
                strokeWidth={1.75}
                aria-hidden
              />
            </button>
          </li>
        )
      })}
    </ol>
  )
}
