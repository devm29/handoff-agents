"use client"

import { AlertTriangle, Check, PenLine, X } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

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
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet"
import { Textarea } from "@/components/ui/textarea"
import { useDecide } from "@/lib/api/queries"
import { type Approval, type DecisionInput, RiskLevel, riskLevels, type Session } from "@/lib/api/schemas"
import { decisionGuard } from "@/lib/approval-policy"
import { sentenceCase } from "@/lib/format"

export function DecisionDialogs({ approval, session }: { approval: Approval; session: Session }) {
  const decide = useDecide()
  const guard = decisionGuard(approval, session)
  const [comment, setComment] = useState("")
  const [editOpen, setEditOpen] = useState(false)
  const [rating, setRating] = useState<RiskLevel>(approval.request.risk_rating)
  const [conditions, setConditions] = useState(approval.request.conditions.join("\n"))
  const [summary, setSummary] = useState(approval.request.summary)

  const justification = comment.trim()
  const justificationMissing = guard.approveNeedsJustification && justification === ""
  const summaryMissing = summary.trim() === ""
  const busy = decide.isPending

  const send = (decision: DecisionInput, success: string) => {
    const payload: DecisionInput = justification ? { ...decision, comment: justification } : decision
    decide.mutate(
      { approvalId: approval.id, decision: payload },
      {
        onSuccess: () => {
          toast.success(success)
          setEditOpen(false)
        },
        onError: (error) => toast.error(error.message),
      },
    )
  }

  const submitEdit = () => {
    const lines = conditions
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)
    send(
      { action: "edit", edits: { risk_rating: rating, conditions: lines, summary: summary.trim() } },
      `Approved ${approval.vendor_name} with your edits. The run is resuming.`,
    )
  }

  const approve = () => send({ action: "approve" }, `Approved ${approval.vendor_name}. The run is resuming.`)

  return (
    <section className="space-y-4 rounded-xl border border-border/60 bg-card p-5" aria-labelledby="decision-heading">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id="decision-heading" className="text-[15px] font-semibold">
          Your decision
        </h3>
        <p className="text-[13px] text-muted-foreground">
          Signing as <span className="font-medium text-foreground">{session.name}</span> · {sentenceCase(session.role)}
        </p>
      </div>

      {guard.notice ? (
        <p className="flex gap-2 rounded-lg bg-warning/10 px-3 py-2.5 text-[13px] leading-5" id="decision-notice">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" strokeWidth={1.75} aria-hidden />
          {guard.notice}
        </p>
      ) : null}

      <div className="space-y-1.5">
        <Label htmlFor="comment" className="text-[13px] font-medium">
          {guard.approveNeedsJustification ? "Justification" : "Comment"}
        </Label>
        <Textarea
          id="comment"
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder={
            guard.approveNeedsJustification
              ? "Required to approve: cite the licence or exemption that permits this vendor"
              : "Optional note for the report and audit log"
          }
          rows={2}
          disabled={!guard.canDecide}
          aria-describedby={guard.approveNeedsJustification ? "comment-hint" : undefined}
        />
        {guard.approveNeedsJustification ? (
          <p id="comment-hint" className="text-xs text-muted-foreground">
            Recorded in the report and the audit log. Not needed to reject.
          </p>
        ) : null}
      </div>

      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:items-center sm:justify-between">
        <AlertDialog>
          <AlertDialogTrigger asChild>
            <Button variant="destructive" disabled={!guard.canDecide || busy}>
              <X strokeWidth={1.75} aria-hidden data-icon="inline-start" />
              Reject
            </Button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Reject {approval.vendor_name}?</AlertDialogTitle>
              <AlertDialogDescription>
                The run resumes and the report writer records a rejection signed by {session.name}.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Cancel</AlertDialogCancel>
              <AlertDialogAction
                className="bg-destructive text-white hover:bg-destructive/90"
                onClick={() => send({ action: "reject" }, `Rejected ${approval.vendor_name}.`)}
              >
                Reject vendor
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Sheet open={editOpen} onOpenChange={setEditOpen}>
            <SheetTrigger asChild>
              <Button
                variant="secondary"
                disabled={!guard.canApprove || justificationMissing || busy}
                aria-describedby={justificationMissing ? "comment-hint" : undefined}
              >
                <PenLine strokeWidth={1.75} aria-hidden data-icon="inline-start" />
                Edit and approve
              </Button>
            </SheetTrigger>
            <SheetContent className="w-full gap-0 sm:max-w-md">
              <SheetHeader className="border-b border-border/60 px-6 py-5">
                <SheetTitle className="text-[17px] font-semibold">Edit before approving</SheetTitle>
                <SheetDescription>Your edits replace the agents&apos; proposal in the final report.</SheetDescription>
              </SheetHeader>
              <div className="flex-1 space-y-5 overflow-y-auto px-6 py-5">
                <div className="space-y-1.5">
                  <Label htmlFor="edit-rating" className="text-[13px] font-medium">
                    Risk rating
                  </Label>
                  <Select value={rating} onValueChange={(value) => setRating(RiskLevel.parse(value))}>
                    <SelectTrigger id="edit-rating" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {riskLevels.map((level) => (
                        <SelectItem key={level} value={level}>
                          {sentenceCase(level)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="edit-conditions" className="text-[13px] font-medium">
                    Conditions
                  </Label>
                  <Textarea
                    id="edit-conditions"
                    value={conditions}
                    onChange={(e) => setConditions(e.target.value)}
                    rows={5}
                    placeholder="One condition per line"
                    aria-describedby="edit-conditions-hint"
                  />
                  <p id="edit-conditions-hint" className="text-xs text-muted-foreground">
                    One per line. Leave empty to approve without conditions.
                  </p>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="edit-summary" className="text-[13px] font-medium">
                    Summary
                  </Label>
                  <Textarea
                    id="edit-summary"
                    value={summary}
                    onChange={(e) => setSummary(e.target.value)}
                    rows={5}
                    aria-invalid={summaryMissing ? true : undefined}
                    aria-describedby={summaryMissing ? "edit-summary-error" : undefined}
                  />
                  {summaryMissing ? (
                    <p id="edit-summary-error" className="text-xs text-destructive">
                      Add a summary. It opens the final report.
                    </p>
                  ) : null}
                </div>
              </div>
              <SheetFooter className="flex-row justify-end gap-2 border-t border-border/60 px-6 py-4">
                <Button variant="secondary" onClick={() => setEditOpen(false)}>
                  Cancel
                </Button>
                <Button onClick={submitEdit} disabled={busy || summaryMissing}>
                  {busy ? "Saving…" : "Approve with edits"}
                </Button>
              </SheetFooter>
            </SheetContent>
          </Sheet>
          {guard.approveNeedsJustification ? (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button
                  disabled={justificationMissing || busy}
                  aria-describedby={justificationMissing ? "comment-hint" : undefined}
                >
                  <Check strokeWidth={1.75} aria-hidden data-icon="inline-start" />
                  Approve
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Override the sanctions match?</AlertDialogTitle>
                  <AlertDialogDescription>
                    {approval.vendor_name} has a confirmed sanctions match. Approving signs the override as {session.name} with
                    your justification: “{justification}”
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction className="bg-destructive text-white hover:bg-destructive/90" onClick={approve}>
                    Approve anyway
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          ) : (
            <Button onClick={approve} disabled={!guard.canApprove || busy}>
              <Check strokeWidth={1.75} aria-hidden data-icon="inline-start" />
              Approve
            </Button>
          )}
        </div>
      </div>
    </section>
  )
}
