import { ArrowRight, Check, Cpu, Send, UserCheck, Wrench, X } from "lucide-react"

import type { TrajectoryStep } from "@/lib/api/schemas"
import { nodeLabel } from "@/lib/format"
import { cn } from "@/lib/utils"

const ICON = { handoff: ArrowRight, tool_call: Wrench, llm_call: Cpu, approval: UserCheck, submit: Send } as const

function summarize(step: TrajectoryStep): string {
  switch (step.kind) {
    case "handoff":
      return `Handed off to ${nodeLabel(step.name)}`
    case "tool_call": {
      const args = Object.entries(step.arguments)
        .filter(([, value]) => value !== null && value !== undefined)
        .map(([key, value]) => `${key}=${typeof value === "string" ? value : JSON.stringify(value)}`)
        .join(", ")
      return `${step.name}(${args})`
    }
    case "llm_call":
      return `Model call · ${step.tokens.toLocaleString()} tokens`
    case "approval":
      return `Approval: ${step.name} by ${step.detail ?? "reviewer"}`
    case "submit":
      return `Submitted ${step.name.replace("submit_", "").replaceAll("_", " ")}`
  }
}

export function TrajectoryList({ steps, filter }: { steps: TrajectoryStep[]; filter: string | null }) {
  const visible = steps.filter((step) => step.kind !== "llm_call" && (filter === null || step.agent === filter))
  if (visible.length === 0) {
    return <p className="px-2 py-8 text-center text-[13px] text-muted-foreground">No steps recorded for this selection yet.</p>
  }
  return (
    <ol className="divide-y divide-border/70">
      {visible.map((step, index) => {
        const Icon = ICON[step.kind]
        return (
          <li key={`${step.at}-${index}`} className="flex items-start gap-3 px-1 py-2.5">
            <span
              className={cn(
                "mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-md",
                step.ok ? "bg-secondary text-muted-foreground" : "bg-destructive/10 text-destructive",
              )}
            >
              <Icon className="size-3.5" strokeWidth={1.75} aria-hidden />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <span className="font-medium text-foreground/80">{nodeLabel(step.agent)}</span>
                {step.ok ? <Check className="size-3 text-success" strokeWidth={2.5} aria-label="succeeded" /> : <X className="size-3 text-destructive" strokeWidth={2.5} aria-label="failed" />}
              </div>
              <p className="truncate font-mono text-[12px] leading-5" title={summarize(step)}>
                {summarize(step)}
              </p>
              {step.kind === "handoff" && step.detail ? (
                <p className="text-xs text-muted-foreground">{step.detail}</p>
              ) : null}
            </div>
          </li>
        )
      })}
    </ol>
  )
}
