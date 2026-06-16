// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it } from "vitest"

import { DecisionDialogs } from "@/components/approvals/decision-dialogs"
import type { Approval, Session } from "@/lib/api/schemas"
import { analyst, approvalFixture, cro } from "@/test/fixtures"

function renderDialogs(approval: Approval, session: Session) {
  const client = new QueryClient()
  return render(
    <QueryClientProvider client={client}>
      <DecisionDialogs approval={approval} session={session} />
    </QueryClientProvider>,
  )
}

const button = (name: string) => screen.getByRole("button", { name }) as HTMLButtonElement

afterEach(cleanup)

describe("DecisionDialogs", () => {
  it("signs as the session reviewer instead of asking for a name", () => {
    renderDialogs(approvalFixture(), analyst)
    expect(screen.getByText("Priya Raman")).toBeTruthy()
    expect(screen.queryByLabelText(/signing as/i)).toBeNull()
    expect(button("Approve").disabled).toBe(false)
  })

  it("does not offer approval of a confirmed sanctions match below the top tier", () => {
    renderDialogs(approvalFixture({ compliance: "match" }), analyst)
    expect(button("Approve").disabled).toBe(true)
    expect(button("Edit and approve").disabled).toBe(true)
    expect(button("Reject").disabled).toBe(false)
    expect(screen.getByText(/only the top escalation tier/i)).toBeTruthy()
  })

  it("requires a justification before the top tier can override a match", () => {
    renderDialogs(approvalFixture({ compliance: "match" }), cro)
    expect(button("Approve").disabled).toBe(true)
    fireEvent.change(screen.getByLabelText("Justification"), { target: { value: "OFAC licence GL-2026-14" } })
    expect(button("Approve").disabled).toBe(false)
  })

  it("leaves an escalated approval read-only for a junior reviewer", () => {
    renderDialogs(approvalFixture({ level: 2 }), analyst)
    for (const name of ["Approve", "Edit and approve", "Reject"]) expect(button(name).disabled).toBe(true)
  })
})
