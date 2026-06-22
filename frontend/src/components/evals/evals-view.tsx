"use client"

import { ChevronRight, FlaskConical } from "lucide-react"
import { Fragment, useState } from "react"

import { ToneBadge } from "@/components/common/badges"
import { EmptyState } from "@/components/common/empty-state"
import { ErrorNotice } from "@/components/common/error-notice"
import { KpiTile } from "@/components/common/kpi-tile"
import { PageToolbar } from "@/components/shell/page-toolbar"
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useEvalReports } from "@/lib/api/queries"
import type { EvalReport, ScenarioResult } from "@/lib/api/schemas"
import { formatDateTime, formatPercent, formatUsd } from "@/lib/format"
import { cn } from "@/lib/utils"

const METRICS = [
  { key: "tool_sequence", label: "Tool sequence" },
  { key: "handoff_order", label: "Handoffs" },
  { key: "efficiency", label: "Efficiency" },
  { key: "outcome", label: "Outcome" },
  { key: "reasoning", label: "Reasoning" },
] as const

function Metric({ value }: { value: number }) {
  return (
    <div className="flex items-center justify-end gap-2">
      <div className="hidden h-1.5 w-12 overflow-hidden rounded-full bg-secondary 2xl:block" aria-hidden>
        <div
          className={cn("h-full rounded-full", value >= 0.95 ? "bg-success" : value >= 0.8 ? "bg-primary" : "bg-warning")}
          style={{ width: `${Math.round(value * 100)}%` }}
        />
      </div>
      <span className="w-10 text-right tabular-nums">{formatPercent(value)}</span>
    </div>
  )
}

export function EvalsView() {
  const reports = useEvalReports()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const list = reports.data ?? []
  const report = list.find((r) => r.id === selectedId) ?? list[0] ?? null

  return (
    <>
      <PageToolbar title="Evals" />
      <div className="mx-auto w-full max-w-7xl space-y-8 px-4 py-8 md:px-8">
        <div>
          <h2 className="text-[28px] leading-[34px] font-semibold tracking-tight">Trajectory evals</h2>
          <p className="max-w-2xl text-[13px] text-muted-foreground">
            Scores how the agents worked, not just what they concluded: expected tool sequences, handoff order, wasted
            steps, the final outcome, and a judge&apos;s read on reasoning quality. Run{" "}
            <code className="rounded bg-secondary px-1 py-0.5 font-mono text-xs">handoff eval run</code> to add a report.
          </p>
        </div>
        {reports.isError ? (
          <ErrorNotice title="Eval reports could not be loaded" error={reports.error} />
        ) : reports.isPending ? (
          <Skeleton className="h-96 w-full rounded-xl" />
        ) : report === null ? (
          <Card>
            <EmptyState
              icon={FlaskConical}
              title="No eval reports yet"
              description="Run the scenario suite from the CLI. Results are stored here so you can compare runs over time."
            />
          </Card>
        ) : (
          <ReportBody report={report} history={list} onSelect={setSelectedId} />
        )}
      </div>
    </>
  )
}

function ReportBody({ report, history, onSelect }: { report: EvalReport; history: EvalReport[]; onSelect: (id: string) => void }) {
  const s = report.summary
  const [expanded, setExpanded] = useState<string | null>(null)
  return (
    <>
      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4" aria-label="Eval summary">
        <KpiTile label="Scenarios passed" value={`${s.passed}/${s.scenarios}`} hint={`${formatPercent(s.pass_rate)} pass rate`} />
        <KpiTile label="Mean overall" value={(s.mean.overall ?? 0).toFixed(2)} hint="Weighted across five metrics" />
        <KpiTile label="Step efficiency" value={formatPercent(s.mean.efficiency ?? 0)} hint="Optimal tool calls / actual" />
        <KpiTile label="Suite cost" value={formatUsd(s.total_cost_usd)} hint={`${s.provider} provider`} />
      </section>
      <div className="grid gap-6 2xl:grid-cols-[minmax(0,1fr)_300px]">
        <Card className="gap-0 p-0">
          <CardHeader className="border-b border-border/60 py-5">
            <CardTitle>Scenarios</CardTitle>
            <CardDescription>
              Suite “{report.suite}” · {formatDateTime(report.created_at)}. Select a row to see mismatches and the judge&apos;s note.
            </CardDescription>
          </CardHeader>
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="pl-5 text-xs font-medium text-muted-foreground">Scenario</TableHead>
                {METRICS.map((m) => (
                  <TableHead key={m.key} className="hidden text-right text-xs font-medium text-muted-foreground md:table-cell">
                    {m.label}
                  </TableHead>
                ))}
                <TableHead className="pr-5 text-right text-xs font-medium text-muted-foreground">Overall</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {report.results.scenarios.map((result) => (
                <ScenarioRow
                  key={result.scenario_id}
                  result={result}
                  open={expanded === result.scenario_id}
                  onToggle={() => setExpanded(expanded === result.scenario_id ? null : result.scenario_id)}
                />
              ))}
            </TableBody>
          </Table>
        </Card>
        <Card className="h-fit gap-2">
          <CardHeader>
            <CardTitle>History</CardTitle>
            <CardDescription>The ten most recent reports.</CardDescription>
          </CardHeader>
          <ul className="space-y-0.5 px-2 pb-1">
            {history.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  onClick={() => onSelect(item.id)}
                  aria-current={item.id === report.id ? "true" : undefined}
                  className={cn(
                    "flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-[13px] outline-none focus-visible:ring-4 focus-visible:ring-ring",
                    item.id === report.id ? "bg-primary/10" : "hover:bg-accent/60",
                  )}
                >
                  <span>
                    <span className="block font-medium">{formatDateTime(item.created_at)}</span>
                    <span className="text-xs text-muted-foreground">
                      {item.suite} · {item.provider}
                    </span>
                  </span>
                  <span className="tabular-nums">
                    {item.summary.passed}/{item.summary.scenarios}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </>
  )
}

function ScenarioRow({ result, open, onToggle }: { result: ScenarioResult; open: boolean; onToggle: () => void }) {
  const score = result.score
  return (
    <Fragment>
      <TableRow className="h-12 cursor-pointer hover:bg-accent/50" onClick={onToggle}>
        <TableCell className="pl-5">
          <button
            type="button"
            className="flex items-center gap-2 rounded-sm text-left outline-none focus-visible:ring-4 focus-visible:ring-ring"
            aria-expanded={open}
            onClick={(e) => {
              e.stopPropagation()
              onToggle()
            }}
          >
            <ChevronRight
              className={cn("size-3.5 text-muted-foreground transition-transform duration-150", open && "rotate-90")}
              strokeWidth={1.75}
              aria-hidden
            />
            <span className="font-medium">{result.scenario_id}</span>
            <ToneBadge tone={result.status === "passed" ? "success" : result.status === "failed" ? "warning" : "destructive"}>
              {result.status}
            </ToneBadge>
          </button>
        </TableCell>
        {METRICS.map((m) => (
          <TableCell key={m.key} className="hidden text-[13px] md:table-cell">
            {score ? <Metric value={score[m.key]} /> : "—"}
          </TableCell>
        ))}
        <TableCell className="pr-5 text-right text-[13px] font-semibold tabular-nums">{score ? score.overall.toFixed(2) : "—"}</TableCell>
      </TableRow>
      {open ? (
        <TableRow className="hover:bg-transparent">
          <TableCell colSpan={METRICS.length + 2} className="bg-secondary/40 px-5 py-4 whitespace-normal">
            <div className="grid gap-4 text-[13px] md:grid-cols-2">
              <div className="space-y-1.5">
                <p className="text-muted-foreground">{result.description}</p>
                {result.judge_rationale ? (
                  <p>
                    <span className="font-medium">Judge:</span> {result.judge_rationale}
                  </p>
                ) : null}
                {result.error ? <p className="text-destructive">{result.error}</p> : null}
              </div>
              <div className="space-y-1.5">
                <p className="font-medium">{score && score.mismatches.length > 0 ? "Deviations from the expected trajectory" : "Matched the expected trajectory"}</p>
                {score?.mismatches.map((m) => (
                  <p key={m} className="font-mono text-xs text-muted-foreground">
                    {m}
                  </p>
                ))}
                <p className="text-xs text-muted-foreground tabular-nums">
                  {formatUsd(result.usage.cost_usd)} · {(result.duration_ms / 1000).toFixed(1)} s
                </p>
              </div>
            </div>
          </TableCell>
        </TableRow>
      ) : null}
    </Fragment>
  )
}
