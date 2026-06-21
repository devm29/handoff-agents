import { Progress } from "@/components/ui/progress"
import type { RunSummary } from "@/lib/api/schemas"
import { formatTokens, formatUsd } from "@/lib/format"
import { cn } from "@/lib/utils"

function Meter({ label, used, limit, display }: { label: string; used: number; limit: number; display: string }) {
  const ratio = limit > 0 ? Math.min(1, used / limit) : 0
  return (
    <div className="min-w-40 space-y-1.5">
      <div className="flex items-baseline justify-between gap-3 text-[13px]">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-medium tabular-nums">{display}</span>
      </div>
      <Progress
        value={ratio * 100}
        aria-label={`${label} ${Math.round(ratio * 100)} percent of budget`}
        className={cn("h-1.5", ratio >= 1 ? "[&>div]:bg-destructive" : ratio > 0.8 ? "[&>div]:bg-warning" : "[&>div]:bg-primary")}
      />
    </div>
  )
}

export function UsageMeters({ run }: { run: RunSummary }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Meter
        label="Tokens"
        used={run.usage.total_tokens}
        limit={run.budget.max_tokens}
        display={`${formatTokens(run.usage.total_tokens)} / ${formatTokens(run.budget.max_tokens)}`}
      />
      <Meter
        label="Spend"
        used={run.usage.cost_usd}
        limit={run.budget.max_usd}
        display={`${formatUsd(run.usage.cost_usd)} / ${formatUsd(run.budget.max_usd)}`}
      />
    </div>
  )
}
