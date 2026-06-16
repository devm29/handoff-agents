"use client"

import { ArrowUpRight, CheckCircle2, Clock, Inbox, PenLine } from "lucide-react"
import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"
import { useEffect, useMemo, useState } from "react"

import { DecisionDialogs } from "@/components/approvals/decision-dialogs"
import { RiskBadge, ToneBadge } from "@/components/common/badges"
import { EmptyState } from "@/components/common/empty-state"
import { ErrorNotice } from "@/components/common/error-notice"
import { PageToolbar } from "@/components/shell/page-toolbar"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { useApprovals, useSession } from "@/lib/api/queries"
import type { Approval } from "@/lib/api/schemas"
import { DECISION_LABELS, formatDateTime, formatRelative, sentenceCase } from "@/lib/format"
import { cn } from "@/lib/utils"

type View = "pending" | "decided"

const RECOMMENDATION_TONE = { approve: "success", approve_with_conditions: "warning", reject: "destructive" } as const

function useNow(intervalMs: number): Date {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), intervalMs)
    return () => clearInterval(timer)
  }, [intervalMs])
  return now
}

function Deadline({ approval, now }: { approval: Approval; now: Date }) {
  const overdue = new Date(approval.due_at).getTime() <= now.getTime()
  return (
    <span className={cn("inline-flex items-center gap-1", overdue && "text-destructive")}>
      <Clock className="size-3" strokeWidth={1.75} aria-hidden />
      {overdue ? "Overdue, escalating" : `Due ${formatRelative(approval.due_at, now)}`}
    </span>
  )
}

export function ApprovalsView() {
  const approvals = useApprovals()
  const params = useSearchParams()
  const router = useRouter()
  const now = useNow(30_000)
  const [chosenView, setChosenView] = useState<View>("pending")
  const items = useMemo(() => approvals.data?.items ?? [], [approvals.data])
  const requested = items.find((a) => a.id === params.get("id")) ?? null
  const view: View = requested ? (requested.status === "pending" ? "pending" : "decided") : chosenView
  const visible = items.filter((a) => (view === "pending" ? a.status === "pending" : a.status !== "pending"))
  const selected = requested ?? visible[0] ?? null

  const select = (id: string) => router.replace(`/approvals?id=${id}`, { scroll: false })
  const changeView = (next: View) => {
    setChosenView(next)
    if (requested) router.replace("/approvals", { scroll: false })
  }

  return (
    <>
      <PageToolbar title="Approvals" />
      {approvals.isError ? (
        <div className="mx-auto w-full max-w-3xl p-8">
          <ErrorNotice title="Approvals could not be loaded" error={approvals.error} />
        </div>
      ) : (
        <div className="grid min-h-[calc(100dvh-52px)] grid-cols-1 md:grid-cols-[340px_minmax(0,1fr)]">
          <aside className="border-b border-border/60 bg-background md:border-r md:border-b-0" aria-label="Approval requests">
            <div className="border-b border-border/60 p-3">
              <ToggleGroup
                type="single"
                value={view}
                onValueChange={(value) => (value === "pending" || value === "decided") && changeView(value)}
                className="h-8 w-full rounded-lg bg-secondary p-0.5"
                aria-label="Show pending or decided approvals"
              >
                <ToggleGroupItem value="pending" className="h-7 flex-1 rounded-md text-[13px] data-[state=on]:bg-background data-[state=on]:shadow-sm">
                  Pending
                </ToggleGroupItem>
                <ToggleGroupItem value="decided" className="h-7 flex-1 rounded-md text-[13px] data-[state=on]:bg-background data-[state=on]:shadow-sm">
                  Decided
                </ToggleGroupItem>
              </ToggleGroup>
            </div>
            {approvals.isPending ? (
              <div className="space-y-2 p-3">
                {Array.from({ length: 4 }, (_, i) => (
                  <Skeleton key={i} className="h-16 w-full" />
                ))}
              </div>
            ) : visible.length === 0 ? (
              <p className="px-4 py-10 text-center text-[13px] text-muted-foreground">
                {view === "pending" ? "Nothing waiting on you." : "No decisions yet."}
              </p>
            ) : (
              <ul className="max-h-[calc(100dvh-110px)] space-y-0.5 overflow-y-auto p-2">
                {visible.map((approval) => (
                  <li key={approval.id}>
                    <button
                      type="button"
                      onClick={() => select(approval.id)}
                      aria-current={selected?.id === approval.id ? "true" : undefined}
                      className={cn(
                        "w-full rounded-lg px-3 py-2.5 text-left transition-colors duration-150 outline-none focus-visible:ring-4 focus-visible:ring-ring",
                        selected?.id === approval.id ? "bg-primary/10" : "hover:bg-accent/60",
                      )}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-[14px] font-semibold">{approval.vendor_name}</span>
                        <ToneBadge tone={RECOMMENDATION_TONE[approval.request.recommendation]}>
                          {DECISION_LABELS[approval.request.recommendation]}
                        </ToneBadge>
                      </div>
                      <div className="mt-1 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                        <span className="truncate">
                          {approval.status === "pending"
                            ? `${sentenceCase(approval.assignee)}${approval.escalation_level > 0 ? " · escalated" : ""}`
                            : `${sentenceCase(approval.status)} by ${approval.decided_by ?? "policy"}`}
                        </span>
                        {approval.status === "pending" ? <Deadline approval={approval} now={now} /> : null}
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </aside>
          <section className="min-w-0">
            {selected ? (
              <ApprovalDetail approval={selected} now={now} />
            ) : approvals.isPending ? null : (
              <EmptyState
                icon={Inbox}
                title="Inbox zero"
                description="Runs pause here when the policy needs a human. Low-risk, sanctions-clear vendors are approved automatically."
              />
            )}
          </section>
        </div>
      )}
    </>
  )
}

function ApprovalDetail({ approval, now }: { approval: Approval; now: Date }) {
  const session = useSession()
  const request = approval.request
  return (
    <div className="mx-auto max-w-3xl space-y-8 px-4 py-8 md:px-8">
      <header className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <ToneBadge tone={RECOMMENDATION_TONE[request.recommendation]}>
            Recommends: {DECISION_LABELS[request.recommendation]}
          </ToneBadge>
          <RiskBadge rating={request.risk_rating} />
          <ToneBadge tone={request.compliance_status === "clear" ? "success" : request.compliance_status === "match" ? "destructive" : "warning"}>
            Sanctions {request.compliance_status.replaceAll("_", " ")}
          </ToneBadge>
        </div>
        <h2 className="text-[28px] leading-[34px] font-semibold tracking-tight">{request.vendor}</h2>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-muted-foreground">
          <span>Requested {formatDateTime(approval.created_at)}</span>
          {approval.status === "pending" ? (
            <>
              <span>
                Assigned to {sentenceCase(approval.assignee)}
                {approval.escalation_level > 0 ? ` (escalation level ${approval.escalation_level})` : ""}
              </span>
              <Deadline approval={approval} now={now} />
            </>
          ) : null}
          <Link href={`/runs/${approval.run_id}`} className="inline-flex items-center gap-1 text-primary hover:underline">
            Open run <ArrowUpRight className="size-3.5" strokeWidth={1.75} aria-hidden />
          </Link>
        </div>
      </header>

      <section className="space-y-2">
        <h3 className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Assessment</h3>
        <div className="divide-y divide-border rounded-xl border border-border/60 bg-card">
          <div className="flex min-h-11 items-center justify-between px-4 text-[14px]">
            <span className="text-muted-foreground">Risk score</span>
            <span className="font-semibold tabular-nums">{request.risk_score} / 100</span>
          </div>
          <p className="px-4 py-3 text-[14px] leading-[22px]">{request.summary}</p>
        </div>
      </section>

      {request.key_findings.length > 0 ? (
        <section className="space-y-2">
          <h3 className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Key findings</h3>
          <ul className="divide-y divide-border rounded-xl border border-border/60 bg-card">
            {request.key_findings.map((finding) => (
              <li key={finding} className="px-4 py-2.5 text-[14px] leading-[22px]">
                {finding}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {request.conditions.length > 0 ? (
        <section className="space-y-2">
          <h3 className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Proposed conditions</h3>
          <ul className="space-y-1.5 rounded-xl bg-warning/10 p-4 text-[14px] leading-[22px]">
            {request.conditions.map((condition) => (
              <li key={condition} className="flex gap-2">
                <PenLine className="mt-1 size-3.5 shrink-0 text-warning" strokeWidth={1.75} aria-hidden />
                {condition}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {approval.status === "pending" ? (
        session.data ? <DecisionDialogs key={approval.id} approval={approval} session={session.data} /> : null
      ) : (
        <section className="flex items-start gap-3 rounded-xl border border-border/60 bg-card p-4">
          <CheckCircle2 className="mt-0.5 size-[18px] shrink-0 text-success" strokeWidth={1.75} aria-hidden />
          <div className="space-y-1 text-[14px]">
            <p className="font-semibold">
              {sentenceCase(approval.status)} by {approval.decided_by}
              {approval.decision?.reviewer_role ? ` (${sentenceCase(approval.decision.reviewer_role)})` : ""}
              {approval.decided_at ? ` on ${formatDateTime(approval.decided_at)}` : ""}
            </p>
            {approval.decision?.comment ? <p className="text-muted-foreground">{approval.decision.comment}</p> : null}
            {approval.decision?.edits?.conditions ? (
              <p className="text-muted-foreground">Conditions set: {approval.decision.edits.conditions.join("; ")}</p>
            ) : null}
          </div>
        </section>
      )}
      {approval.status === "pending" ? null : (
        <Button variant="secondary" asChild>
          <Link href={`/runs/${approval.run_id}`}>View the run</Link>
        </Button>
      )}
    </div>
  )
}
