import { Badge } from "@/components/ui/badge"
import type { RunStatus } from "@/lib/api/schemas"
import { DECISION_LABELS, RISK_TONE, RUN_STATUS_META, sentenceCase } from "@/lib/format"
import { cn } from "@/lib/utils"

type Tone = "info" | "success" | "warning" | "destructive" | "neutral"

const DOT: Record<Tone, string> = {
  info: "bg-primary",
  success: "bg-success",
  warning: "bg-warning",
  destructive: "bg-destructive",
  neutral: "bg-muted-foreground",
}

export function ToneBadge({ tone, children, pulse = false }: { tone: Tone; children: React.ReactNode; pulse?: boolean }) {
  return (
    <Badge variant={tone}>
      <span className={cn("size-1.5 rounded-full", DOT[tone], pulse && "status-pulse")} aria-hidden />
      {children}
    </Badge>
  )
}

export function RunStatusBadge({ status }: { status: RunStatus }) {
  const meta = RUN_STATUS_META[status]
  return (
    <ToneBadge tone={meta.tone} pulse={status === "running"}>
      {meta.label}
    </ToneBadge>
  )
}

export function RiskBadge({ rating }: { rating: string | null | undefined }) {
  if (!rating) return <span className="text-muted-foreground">—</span>
  return <ToneBadge tone={RISK_TONE[rating] ?? "neutral"}>{sentenceCase(rating)} risk</ToneBadge>
}

export function DecisionText({ decision }: { decision: string | null | undefined }) {
  if (!decision) return <span className="text-muted-foreground">—</span>
  return <span>{DECISION_LABELS[decision] ?? sentenceCase(decision)}</span>
}
