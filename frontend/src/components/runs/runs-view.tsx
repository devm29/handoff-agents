"use client"

import { GitFork, ListChecks, Search } from "lucide-react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { useDeferredValue, useMemo, useState } from "react"

import { DecisionText, RiskBadge, RunStatusBadge } from "@/components/common/badges"
import { EmptyState } from "@/components/common/empty-state"
import { ErrorNotice } from "@/components/common/error-notice"
import { KpiTile } from "@/components/common/kpi-tile"
import { NewRunSheet } from "@/components/runs/new-run-sheet"
import { PageToolbar } from "@/components/shell/page-toolbar"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { useRuns, useStats } from "@/lib/api/queries"
import type { RunStatus, RunSummary } from "@/lib/api/schemas"
import { formatRelative, formatTokens, formatUsd, nodeLabel } from "@/lib/format"

const FILTERS = {
  all: { label: "All", statuses: [] },
  active: { label: "Active", statuses: ["queued", "running"] },
  approval: { label: "Needs approval", statuses: ["awaiting_approval"] },
  done: { label: "Completed", statuses: ["completed", "rejected"] },
  failed: { label: "Failed", statuses: ["failed", "cancelled"] },
} as const satisfies Record<string, { label: string; statuses: readonly RunStatus[] }>

type FilterKey = keyof typeof FILTERS

function isFilterKey(value: string): value is FilterKey {
  return value in FILTERS
}

export function RunsView() {
  const [filter, setFilter] = useState<FilterKey>("all")
  const [query, setQuery] = useState("")
  const deferredQuery = useDeferredValue(query.trim())
  const runs = useRuns({ status: FILTERS[filter].statuses, q: deferredQuery })
  const stats = useStats()
  const items = useMemo(() => runs.data?.pages.flatMap((page) => page.items) ?? [], [runs.data])

  const s = stats.data
  const completed = (s?.runs_by_status.completed ?? 0) + (s?.runs_by_status.rejected ?? 0)
  const active = (s?.runs_by_status.running ?? 0) + (s?.runs_by_status.queued ?? 0)

  return (
    <>
      <PageToolbar title="Runs" actions={<NewRunSheet />} />
      <div className="mx-auto w-full max-w-7xl space-y-8 px-4 py-8 md:px-8">
        <div>
          <h2 className="text-[28px] leading-[34px] font-semibold tracking-tight">Due-diligence runs</h2>
          <p className="text-[13px] text-muted-foreground">
            Every run is a durable LangGraph thread. Open one to watch the agents, rewind to a checkpoint, or fork it.
          </p>
        </div>

        <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4" aria-label="Summary">
          <KpiTile label="Total runs" value={s?.total_runs ?? 0} hint={`${active} in progress`} loading={stats.isPending} />
          <KpiTile
            label="Waiting on a human"
            value={s?.pending_approvals ?? 0}
            hint={<Link href="/approvals" className="text-primary hover:underline">Open approvals</Link>}
            loading={stats.isPending}
          />
          <KpiTile label="Finished" value={completed} hint={`${s?.runs_by_status.failed ?? 0} failed`} loading={stats.isPending} />
          <KpiTile
            label="Model spend"
            value={formatUsd(s?.total_cost_usd ?? 0)}
            hint={`${formatUsd(s?.avg_cost_usd ?? 0)} per run`}
            loading={stats.isPending}
          />
        </section>

        <Card className="gap-0 p-0">
          <div className="flex flex-col gap-3 border-b border-border/60 p-4 md:flex-row md:items-center md:justify-between">
            <div className="-mx-1 overflow-x-auto px-1">
              <ToggleGroup
                type="single"
                value={filter}
                onValueChange={(value) => isFilterKey(value) && setFilter(value)}
                className="h-8 w-max rounded-lg bg-secondary p-0.5"
                aria-label="Filter runs by status"
              >
                {Object.entries(FILTERS).map(([key, value]) => (
                  <ToggleGroupItem
                    key={key}
                    value={key}
                    className="h-7 rounded-md px-3 text-[13px] data-[state=on]:bg-background data-[state=on]:shadow-sm"
                  >
                    {value.label}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            </div>
            <div className="relative w-full md:w-64">
              <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" strokeWidth={1.75} aria-hidden />
              <Input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search vendors"
                aria-label="Search vendors"
                className="rounded-full border-transparent bg-secondary pl-9"
              />
            </div>
          </div>
          {runs.isError ? (
            <div className="p-4">
              <ErrorNotice title="Runs could not be loaded" error={runs.error} />
            </div>
          ) : runs.isPending ? (
            <RunsSkeleton />
          ) : items.length === 0 ? (
            <EmptyState
              icon={ListChecks}
              title={query || filter !== "all" ? "No runs match" : "No runs yet"}
              description={
                query || filter !== "all"
                  ? "Try a different filter or search term."
                  : "Start a run to watch the supervisor hand work to the specialists."
              }
              action={query || filter !== "all" ? undefined : <NewRunSheet />}
            />
          ) : (
            <RunsTable runs={items} />
          )}
          {runs.hasNextPage ? (
            <div className="flex justify-center border-t border-border/60 p-3">
              <Button variant="ghost" size="sm" onClick={() => void runs.fetchNextPage()} disabled={runs.isFetchingNextPage}>
                {runs.isFetchingNextPage ? "Loading…" : "Show more"}
              </Button>
            </div>
          ) : null}
        </Card>
      </div>
    </>
  )
}

function Progress({ run }: { run: RunSummary }) {
  if (run.status === "running") return <span>{nodeLabel(run.current_node)}</span>
  if (run.status === "failed" && run.error) {
    return <span className="text-destructive">{run.error.kind}</span>
  }
  if (run.status === "awaiting_approval") return <span className="text-muted-foreground">Waiting for sign-off</span>
  return <DecisionText decision={run.decision} />
}

function RunsTable({ runs }: { runs: RunSummary[] }) {
  const router = useRouter()
  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className="pl-5 text-xs font-medium text-muted-foreground">Vendor</TableHead>
          <TableHead className="text-xs font-medium text-muted-foreground">Status</TableHead>
          <TableHead className="hidden text-xs font-medium text-muted-foreground md:table-cell">Step or outcome</TableHead>
          <TableHead className="hidden text-xs font-medium text-muted-foreground lg:table-cell">Risk</TableHead>
          <TableHead className="hidden text-right text-xs font-medium text-muted-foreground sm:table-cell">Tokens</TableHead>
          <TableHead className="text-right text-xs font-medium text-muted-foreground">Cost</TableHead>
          <TableHead className="hidden pr-5 text-right text-xs font-medium text-muted-foreground md:table-cell">Started</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {runs.map((run) => (
          <TableRow
            key={run.id}
            className="h-12 cursor-pointer hover:bg-accent/50"
            onClick={() => router.push(`/runs/${run.id}`)}
          >
            <TableCell className="pl-5">
              <Link
                href={`/runs/${run.id}`}
                className="flex items-center gap-2 rounded-sm font-medium outline-none focus-visible:ring-4 focus-visible:ring-ring"
                onClick={(e) => e.stopPropagation()}
              >
                <span className="truncate">{run.vendor_name}</span>
                <span className="text-xs font-normal text-muted-foreground">{run.vendor_country}</span>
                {run.parent_run_id ? (
                  <GitFork className="size-3.5 text-muted-foreground" strokeWidth={1.75} aria-label="Forked run" />
                ) : null}
              </Link>
            </TableCell>
            <TableCell>
              <RunStatusBadge status={run.status} />
            </TableCell>
            <TableCell className="hidden text-[13px] md:table-cell">
              <Progress run={run} />
            </TableCell>
            <TableCell className="hidden lg:table-cell">
              <RiskBadge rating={run.risk_rating} />
            </TableCell>
            <TableCell className="hidden text-right text-[13px] tabular-nums sm:table-cell">
              {formatTokens(run.usage.total_tokens)}
            </TableCell>
            <TableCell className="text-right text-[13px] tabular-nums">{formatUsd(run.usage.cost_usd)}</TableCell>
            <TableCell className="hidden pr-5 text-right text-[13px] text-muted-foreground md:table-cell">
              <time dateTime={run.created_at}>{formatRelative(run.created_at)}</time>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function RunsSkeleton() {
  return (
    <div className="space-y-3 p-5" aria-busy="true" aria-label="Loading runs">
      {Array.from({ length: 6 }, (_, i) => (
        <Skeleton key={i} className="h-8 w-full" />
      ))}
    </div>
  )
}
