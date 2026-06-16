"use client"

import { ArrowLeft, GitFork, Inbox, SearchX, XCircle } from "lucide-react"
import Link from "next/link"
import { useMemo, useState } from "react"
import { toast } from "sonner"

import { RiskBadge, RunStatusBadge } from "@/components/common/badges"
import { EmptyState } from "@/components/common/empty-state"
import { ErrorNotice } from "@/components/common/error-notice"
import { ActivityFeed, RunAnnouncer } from "@/components/inspector/activity-feed"
import { AgentGraph } from "@/components/inspector/agent-graph"
import { CheckpointSheet } from "@/components/inspector/checkpoint-sheet"
import { CheckpointTimeline } from "@/components/inspector/checkpoint-timeline"
import { RetryList, RunErrorAlert } from "@/components/inspector/failure-panel"
import { ReportView } from "@/components/inspector/report-view"
import { TrajectoryList } from "@/components/inspector/trajectory-list"
import { UsageMeters } from "@/components/inspector/usage-meters"
import { PageToolbar } from "@/components/shell/page-toolbar"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { ApiRequestError } from "@/lib/api/client"
import { useCancelRun, useCheckpoints, useRun, useTopology } from "@/lib/api/queries"
import type { CheckpointSummary, Topology } from "@/lib/api/schemas"
import { formatDateTime, nodeLabel } from "@/lib/format"
import { deriveActivity } from "@/lib/graph-status"
import { useRunEvents } from "@/lib/sse"

const TERMINAL = new Set(["completed", "rejected", "failed", "cancelled"])
const ALL_NODES = "all"

function NodeFilter({
  topology,
  value,
  onChange,
}: {
  topology: Topology | undefined
  value: string | null
  onChange: (node: string | null) => void
}) {
  const agents = (topology?.nodes ?? []).filter((node) => node.kind !== "start" && node.kind !== "end")
  return (
    <Select value={value ?? ALL_NODES} onValueChange={(next) => onChange(next === ALL_NODES ? null : next)}>
      <SelectTrigger size="sm" className="w-[168px]" aria-label="Filter activity by agent">
        <SelectValue />
      </SelectTrigger>
      <SelectContent align="end">
        <SelectItem value={ALL_NODES}>All agents</SelectItem>
        {agents.map((node) => (
          <SelectItem key={node.id} value={node.id}>
            {node.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

export function RunInspector({ runId }: { runId: string }) {
  const run = useRun(runId)
  const topology = useTopology()
  const checkpoints = useCheckpoints(runId)
  const { events, connected } = useRunEvents(runId)
  const cancel = useCancelRun(runId)
  const [selected, setSelected] = useState<string | null>(null)
  const [openCheckpoint, setOpenCheckpoint] = useState<CheckpointSummary | null>(null)

  const status = run.data?.status ?? "queued"
  const activity = useMemo(() => deriveActivity(events, status), [events, status])
  const recoveries = useMemo(
    () =>
      events.filter(
        (event) => event.type === "run.status" && event.payload.recovered === true,
      ).length,
    [events],
  )

  const back = (
    <Button variant="ghost" size="icon" asChild>
      <Link href="/" aria-label="Back to runs">
        <ArrowLeft strokeWidth={1.75} aria-hidden />
      </Link>
    </Button>
  )

  if (run.isError) {
    const missing = run.error instanceof ApiRequestError && run.error.status === 404
    return (
      <>
        <PageToolbar title="Run" leading={back} />
        <div className="mx-auto w-full max-w-3xl px-4 py-12">
          {missing ? (
            <EmptyState icon={SearchX} title="Run not found" description="It may have been removed, or the link is incomplete." />
          ) : (
            <ErrorNotice title="This run could not be loaded" error={run.error} />
          )}
        </div>
      </>
    )
  }

  const data = run.data
  const state = data?.state ?? null
  const pendingApproval = data?.approvals.find((approval) => approval.status === "pending")

  return (
    <>
      <PageToolbar
        leading={back}
        title={data ? data.vendor_name : <Skeleton className="h-5 w-40" />}
        actions={
          data && !TERMINAL.has(data.status) ? (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="destructive" size="sm">
                  <XCircle strokeWidth={1.75} aria-hidden data-icon="inline-start" />
                  Cancel run
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Cancel this run?</AlertDialogTitle>
                  <AlertDialogDescription>
                    The worker stops after the current step. Checkpoints stay available, so you can fork from any of them later.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Keep running</AlertDialogCancel>
                  <AlertDialogAction
                    className="bg-destructive text-white hover:bg-destructive/90"
                    onClick={() =>
                      cancel.mutate(undefined, {
                        onSuccess: () => toast.success("Cancellation requested"),
                        onError: (error) => toast.error(error.message),
                      })
                    }
                  >
                    Cancel run
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          ) : null
        }
      />
      <div className="mx-auto w-full max-w-[1440px] space-y-6 px-4 py-6 md:px-8">
        <section className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div className="space-y-2">
            {data ? (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <RunStatusBadge status={data.status} />
                  {data.risk_rating ? <RiskBadge rating={data.risk_rating} /> : null}
                  <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    <span className={connected ? "size-1.5 rounded-full bg-success" : "size-1.5 rounded-full bg-muted-foreground/40"} aria-hidden />
                    {connected ? "Live" : "Reconnecting"}
                  </span>
                </div>
                <h2 className="text-[28px] leading-[34px] font-semibold tracking-tight">{data.vendor_name}</h2>
                <p className="text-[13px] text-muted-foreground">
                  {data.vendor_country} · started {formatDateTime(data.created_at)}
                  {data.status === "running" && data.current_node ? ` · working in ${nodeLabel(data.current_node)}` : ""}
                  {recoveries > 0 ? ` · recovered ${recoveries}× from a checkpoint after a worker stopped` : ""}
                </p>
                {data.parent_run_id ? (
                  <Link href={`/runs/${data.parent_run_id}`} className="inline-flex items-center gap-1.5 text-[13px] text-primary hover:underline">
                    <GitFork className="size-3.5" strokeWidth={1.75} aria-hidden />
                    Forked from an earlier run
                  </Link>
                ) : null}
              </>
            ) : (
              <>
                <Skeleton className="h-5 w-32" />
                <Skeleton className="h-8 w-64" />
              </>
            )}
          </div>
          {data ? (
            <div className="w-full lg:w-[440px]">
              <UsageMeters run={data} />
            </div>
          ) : null}
        </section>

        {pendingApproval ? (
          <div className="flex flex-col gap-3 rounded-xl border border-warning/40 bg-warning/10 p-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-[14px] font-semibold">Waiting for a decision from {pendingApproval.assignee}</p>
              <p className="text-[13px] text-muted-foreground">
                Recommendation: {pendingApproval.request.recommendation.replaceAll("_", " ")}. The run is paused at a checkpoint and costs nothing while it waits.
              </p>
            </div>
            <Button asChild>
              <Link href={`/approvals?id=${pendingApproval.id}`}>
                <Inbox strokeWidth={1.75} aria-hidden data-icon="inline-start" />
                Review
              </Link>
            </Button>
          </div>
        ) : null}

        <RunErrorAlert error={data?.error ?? null} />

        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="min-w-0 space-y-6">
            <Card className="gap-3 pb-2">
              <CardHeader>
                <CardTitle>Agent graph</CardTitle>
                <CardDescription>
                  Supervisor hands work to specialists over typed contracts. Select a node to filter its activity.
                </CardDescription>
                <CardAction>
                  <NodeFilter topology={topology.data} value={selected} onChange={setSelected} />
                </CardAction>
              </CardHeader>
              <CardContent className="px-2">
                <AgentGraph topology={topology.data} activity={activity} selected={selected} onSelect={setSelected} />
              </CardContent>
            </Card>

            <Card className="gap-4">
              <Tabs defaultValue="report" className="gap-4">
                <CardHeader>
                  <CardTitle>Run output</CardTitle>
                  <CardAction>
                    <TabsList className="h-8 bg-secondary p-0.5">
                      <TabsTrigger value="report" className="text-[13px]">Report</TabsTrigger>
                      <TabsTrigger value="trajectory" className="text-[13px]">Trajectory</TabsTrigger>
                      <TabsTrigger value="activity" className="text-[13px]">Activity</TabsTrigger>
                    </TabsList>
                  </CardAction>
                  {selected ? (
                    <CardDescription>
                      Showing {nodeLabel(selected)} only.{" "}
                      <button type="button" className="text-primary hover:underline" onClick={() => setSelected(null)}>
                        Show all
                      </button>
                    </CardDescription>
                  ) : null}
                </CardHeader>
                <CardContent>
                  <TabsContent value="report">
                    <ReportView report={data?.report ?? null} waitingOnApproval={data?.status === "awaiting_approval"} />
                  </TabsContent>
                  <TabsContent value="trajectory" className="max-h-[560px] overflow-y-auto">
                    <TrajectoryList steps={state?.trajectory ?? []} filter={selected} />
                  </TabsContent>
                  <TabsContent value="activity" className="max-h-[560px] overflow-y-auto">
                    <ActivityFeed events={events} filter={selected} />
                  </TabsContent>
                </CardContent>
              </Tabs>
            </Card>
          </div>

          <div className="h-fit space-y-6 xl:sticky xl:top-[68px]">
            <Card className="gap-2">
              <CardHeader>
                <CardTitle>Checkpoints</CardTitle>
                <CardDescription>Every step is saved to Postgres. Open one to inspect it or fork a new run.</CardDescription>
              </CardHeader>
              <CardContent className="max-h-[calc(100dvh-220px)] overflow-y-auto px-2">
                <CheckpointTimeline checkpoints={checkpoints.data} loading={checkpoints.isPending} onOpen={setOpenCheckpoint} />
              </CardContent>
            </Card>
            <RetryList events={events} />
          </div>
        </div>
      </div>
      <RunAnnouncer events={events} />
      <CheckpointSheet runId={runId} checkpoint={openCheckpoint} onClose={() => setOpenCheckpoint(null)} />
    </>
  )
}
