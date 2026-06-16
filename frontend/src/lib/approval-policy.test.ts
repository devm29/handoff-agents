import { describe, expect, it } from "vitest"

import { decisionGuard } from "@/lib/approval-policy"
import { analyst, approvalFixture, cro } from "@/test/fixtures"

describe("decisionGuard", () => {
  it("lets any reviewer at the assigned tier decide a clear vendor", () => {
    expect(decisionGuard(approvalFixture(), analyst)).toEqual({
      canDecide: true,
      canApprove: true,
      approveNeedsJustification: false,
      notice: null,
    })
  })

  it("locks reviewers below the escalation tier out entirely", () => {
    const guard = decisionGuard(approvalFixture({ level: 1 }), analyst)
    expect(guard.canDecide).toBe(false)
    expect(guard.notice).toContain("Compliance lead")
  })

  it("only lets the top tier approve a confirmed sanctions match, with a justification", () => {
    expect(decisionGuard(approvalFixture({ compliance: "match" }), analyst)).toMatchObject({
      canDecide: true,
      canApprove: false,
    })
    expect(decisionGuard(approvalFixture({ compliance: "match" }), cro)).toMatchObject({
      canApprove: true,
      approveNeedsJustification: true,
    })
  })
})
