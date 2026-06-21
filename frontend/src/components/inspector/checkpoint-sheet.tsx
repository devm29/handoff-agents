"use client"

import { GitFork } from "lucide-react"
import { useRouter } from "next/navigation"
import { useState } from "react"
import { toast } from "sonner"
import { z } from "zod"

import { RiskBadge } from "@/components/common/badges"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import { useCheckpoint, useFork } from "@/lib/api/queries"
import {
  Budget,
  ComplianceResult,
  ResearchFindings,
  RiskAssessment,
  type CheckpointSummary,
  type RunState,
  Vendor,
} from "@/lib/api/schemas"
import { formatTokens, formatUsd, nodeLabel, sentenceCase } from "@/lib/format"

const ForkPatch = z.strictObject({
  vendor: Vendor.optional(),
  budget: Budget.optional(),
  research: ResearchFindings.optional(),
  risk: RiskAssessment.optional(),
  compliance: ComplianceResult.optional(),
})

function initialPatch(state: RunState): string {
  const patch: Record<string, unknown> = { vendor: state.vendor, budget: state.budget }
  if (state.risk) patch.risk = state.risk
  return JSON.stringify(patch, null, 2)
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex min-h-11 items-center justify-between gap-4 px-4 py-2 text-[13px]">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right font-medium">{children}</span>
    </div>
  )
}

export function CheckpointSheet({
  runId,
  checkpoint,
  onClose,
}: {
  runId: string
  checkpoint: CheckpointSummary | null
  onClose: () => void
}) {
  const detail = useCheckpoint(runId, checkpoint?.checkpoint_id ?? null)
  const fork = useFork(runId)
  const state = detail.data?.state ?? null
  const canFork = checkpoint !== null && checkpoint.step >= 0 && state !== null

  return (
    <Sheet open={checkpoint !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full gap-0 sm:max-w-lg">
        <SheetHeader className="border-b border-border/60 px-6 py-5">
          <SheetTitle className="text-[17px] font-semibold">
            {checkpoint ? (checkpoint.step < 0 ? "Run input" : `Step ${checkpoint.step}`) : "Checkpoint"}
          </SheetTitle>
          <SheetDescription>
            {checkpoint?.produced_by && checkpoint.produced_by !== "input"
              ? `State saved after ${nodeLabel(checkpoint.produced_by)}. Fork to replay from here with edits.`
              : "State as it entered the graph."}
          </SheetDescription>
        </SheetHeader>
        <div className="flex-1 space-y-6 overflow-y-auto px-6 py-5">
          {detail.isPending ? (
            <Skeleton className="h-48 w-full" />
          ) : state === null ? (
            <p className="text-[13px] text-muted-foreground">The input checkpoint holds no state yet. Fork from a later step.</p>
          ) : (
            <>
              <Snapshot state={state} next={checkpoint?.next ?? []} />
              {canFork && checkpoint ? (
                <ForkEditor key={checkpoint.checkpoint_id} fork={fork} checkpoint={checkpoint} state={state} onForked={onClose} />
              ) : null}
            </>
          )}
        </div>
        <SheetFooter className="flex-row justify-end gap-2 border-t border-border/60 px-6 py-4">
          <Button variant="secondary" onClick={onClose}>
            Close
          </Button>
          <Button type="submit" form="fork-form" disabled={!canFork || fork.isPending}>
            <GitFork strokeWidth={1.75} aria-hidden data-icon="inline-start" />
            {fork.isPending ? "Forking…" : "Fork from here"}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}

function Snapshot({ state, next }: { state: RunState; next: string[] }) {
  return (
    <section className="space-y-2">
      <h3 className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Snapshot</h3>
      <div className="divide-y divide-border rounded-xl bg-secondary/60">
        <Row label="Next">{next.map(nodeLabel).join(", ") || "Finished"}</Row>
        <Row label="Spend so far">
          <span className="tabular-nums">
            {formatUsd(state.usage.cost_usd)} · {formatTokens(state.usage.input_tokens + state.usage.output_tokens)} tokens
          </span>
        </Row>
        <Row label="Entity">{state.research ? `${state.research.legal_name} (${state.research.status})` : "Not researched"}</Row>
        <Row label="Risk">{state.risk ? <RiskBadge rating={state.risk.rating} /> : "Not assessed"}</Row>
        <Row label="Sanctions">{state.compliance ? sentenceCase(state.compliance.status) : "Not screened"}</Row>
        <Row label="Approval">
          {state.approval
            ? `${state.approval.approved ? "Approved" : "Rejected"} by ${state.approval.reviewer}`
            : "Not decided"}
        </Row>
      </div>
    </section>
  )
}

function ForkEditor({
  fork,
  checkpoint,
  state,
  onForked,
}: {
  fork: ReturnType<typeof useFork>
  checkpoint: CheckpointSummary
  state: RunState
  onForked: () => void
}) {
  const router = useRouter()
  const [patch, setPatch] = useState(() => initialPatch(state))
  const [patchError, setPatchError] = useState<string | null>(null)

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    let raw: unknown
    try {
      raw = JSON.parse(patch)
    } catch {
      setPatchError("This is not valid JSON. Check for trailing commas or missing quotes.")
      return
    }
    const parsed = ForkPatch.safeParse(raw)
    if (!parsed.success) {
      const issue = parsed.error.issues[0]
      setPatchError(issue ? `${issue.path.join(".") || "patch"}: ${issue.message}` : "The patch does not match the state schema.")
      return
    }
    setPatchError(null)
    fork.mutate(
      { checkpointId: checkpoint.checkpoint_id, patch: parsed.data },
      {
        onSuccess: (run) => {
          toast.success(`Forked into a new run from step ${checkpoint.step}`)
          onForked()
          router.push(`/runs/${run.id}`)
        },
        onError: (error) => setPatchError(error.message),
      },
    )
  }

  return (
    <form id="fork-form" onSubmit={submit} className="space-y-2" noValidate>
      <Label htmlFor="fork-patch" className="text-[13px] font-medium">
        State edits for the fork
      </Label>
      <p className="text-xs text-muted-foreground">
        Change vendor, budget, research, risk or compliance. The new run continues from this step with your edits.
      </p>
      <Textarea
        id="fork-patch"
        value={patch}
        onChange={(e) => setPatch(e.target.value)}
        rows={14}
        spellCheck={false}
        className="font-mono text-xs leading-5"
        aria-invalid={patchError ? true : undefined}
        aria-describedby={patchError ? "fork-error" : undefined}
      />
      {patchError ? (
        <p id="fork-error" className="text-xs text-destructive" role="alert">
          {patchError}
        </p>
      ) : null}
    </form>
  )
}
