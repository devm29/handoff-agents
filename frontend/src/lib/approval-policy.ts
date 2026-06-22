import type { Approval, Session } from "@/lib/api/schemas"
import { sentenceCase } from "@/lib/format"

export type DecisionGuard = {
  canDecide: boolean
  canApprove: boolean
  approveNeedsJustification: boolean
  notice: string | null
}

/** Mirrors the API's rules so the UI never offers a decision the server will refuse. */
export function decisionGuard(approval: Approval, session: Session): DecisionGuard {
  if (session.tier < approval.escalation_level) {
    return {
      canDecide: false,
      canApprove: false,
      approveNeedsJustification: false,
      notice: `This approval has been escalated to ${sentenceCase(approval.assignee)}. As ${sentenceCase(session.role)} you can read it but not decide it.`,
    }
  }
  if (approval.request.compliance_status !== "match") {
    return { canDecide: true, canApprove: true, approveNeedsJustification: false, notice: null }
  }
  if (!session.top_tier) {
    return {
      canDecide: true,
      canApprove: false,
      approveNeedsJustification: false,
      notice: "The vendor has a confirmed sanctions match. Only the top escalation tier can approve it, so you can reject it or leave it for them.",
    }
  }
  return {
    canDecide: true,
    canApprove: true,
    approveNeedsJustification: true,
    notice: "The vendor has a confirmed sanctions match. Approving overrides the policy and needs a written justification.",
  }
}
