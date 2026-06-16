import type { Approval, Session } from "@/lib/api/schemas"

export function approvalFixture(overrides: { compliance?: string; level?: number } = {}): Approval {
  const tiers = ["analyst", "compliance-lead", "chief-risk-officer"]
  const level = overrides.level ?? 0
  return {
    id: "6f1c1a52-3d3a-4c55-9a59-0d7b8f7b8a01",
    run_id: "0b7f0c55-4d77-4a39-8a51-2f3e8c9d1e02",
    vendor_name: "Corvane Trading",
    status: "pending",
    request: {
      vendor: "Corvane Trading FZE",
      recommendation: overrides.compliance === "match" ? "reject" : "approve_with_conditions",
      risk_rating: "high",
      risk_score: 72,
      compliance_status: overrides.compliance ?? "clear",
      summary: "Majority owner appears on the OFAC SDN list.",
      conditions: [],
      key_findings: [],
    },
    assignee: tiers[level] ?? "analyst",
    escalation_level: level,
    due_at: "2026-10-05T12:00:00Z",
    decision: null,
    decided_by: null,
    decided_at: null,
    created_at: "2026-10-04T12:00:00Z",
  }
}

export const analyst: Session = { name: "Priya Raman", role: "analyst", tier: 0, top_tier: false }
export const cro: Session = { name: "James Whitaker", role: "chief-risk-officer", tier: 2, top_tier: true }
