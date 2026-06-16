import { z } from "zod"

export const riskLevels = ["low", "medium", "high", "critical"] as const
export const RiskLevel = z.enum(riskLevels)
export type RiskLevel = z.infer<typeof RiskLevel>

export const runStatuses = [
  "queued",
  "running",
  "awaiting_approval",
  "completed",
  "rejected",
  "failed",
  "cancelled",
] as const
export const RunStatus = z.enum(runStatuses)
export type RunStatus = z.infer<typeof RunStatus>

export const ErrorKind = z.enum(["ToolError", "ModelError", "PolicyViolation", "BudgetExceeded", "InternalError"])
export type ErrorKind = z.infer<typeof ErrorKind>

export const ErrorInfo = z.object({
  kind: ErrorKind,
  message: z.string(),
  node: z.string().nullable(),
  retryable: z.boolean(),
  attempt: z.number().nullable(),
  details: z.record(z.string(), z.unknown()),
  occurred_at: z.string(),
})
export type ErrorInfo = z.infer<typeof ErrorInfo>

export const Vendor = z.object({
  name: z.string(),
  country: z.string(),
  website: z.string().nullable().optional(),
  registration_number: z.string().nullable().optional(),
  notes: z.string().nullable().optional(),
})
export type Vendor = z.infer<typeof Vendor>

export const Budget = z.object({ max_tokens: z.number(), max_usd: z.number() })
export type Budget = z.infer<typeof Budget>

export const UsageOut = z.object({
  input_tokens: z.number(),
  output_tokens: z.number(),
  total_tokens: z.number(),
  cost_usd: z.number(),
  llm_calls: z.number(),
  tool_calls: z.number(),
})

export const RunSummary = z.object({
  id: z.uuid(),
  vendor_name: z.string(),
  vendor_country: z.string(),
  status: RunStatus,
  current_node: z.string().nullable(),
  risk_rating: z.string().nullable(),
  decision: z.string().nullable(),
  usage: UsageOut,
  budget: Budget,
  parent_run_id: z.uuid().nullable(),
  forked_from_checkpoint: z.string().nullable(),
  error: ErrorInfo.nullable(),
  claims: z.number(),
  created_at: z.string(),
  updated_at: z.string(),
  started_at: z.string().nullable(),
  completed_at: z.string().nullable(),
})
export type RunSummary = z.infer<typeof RunSummary>

export const RunPage = z.object({ items: z.array(RunSummary), next_cursor: z.string().nullable() })
export type RunPage = z.infer<typeof RunPage>

const Evidence = z.object({
  source: z.enum(["company_registry", "sanctions", "news"]),
  reference: z.string(),
  summary: z.string(),
})
export type Evidence = z.infer<typeof Evidence>

const NewsItem = z.object({
  id: z.string(),
  published_on: z.string(),
  headline: z.string(),
  source: z.string(),
  sentiment: z.number(),
  topics: z.array(z.string()),
})

export const ResearchFindings = z.object({
  legal_name: z.string(),
  registration_number: z.string().nullable(),
  jurisdiction: z.string(),
  status: z.string(),
  incorporated_on: z.string().nullable(),
  industry: z.string().nullable(),
  address: z.string().nullable(),
  beneficial_owners: z.array(
    z.object({
      name: z.string(),
      role: z.string(),
      ownership_pct: z.number().nullable(),
      nationality: z.string().nullable(),
    }),
  ),
  news: z.array(NewsItem),
  summary: z.string(),
  evidence: z.array(Evidence),
})
export type ResearchFindings = z.infer<typeof ResearchFindings>

export const RiskAssessment = z.object({
  rating: RiskLevel,
  score: z.number(),
  factors: z.array(
    z.object({
      category: z.string(),
      description: z.string(),
      severity: RiskLevel,
      evidence: z.array(z.string()),
    }),
  ),
  rationale: z.string(),
})
export type RiskAssessment = z.infer<typeof RiskAssessment>

export const ComplianceResult = z.object({
  status: z.enum(["clear", "potential_match", "match"]),
  screened: z.array(
    z.object({
      name: z.string(),
      kind: z.enum(["company", "person"]),
      result: z.enum(["clear", "potential_match", "match"]),
      hits: z.array(
        z.object({
          list_name: z.string(),
          matched_name: z.string(),
          score: z.number(),
          program: z.string(),
          entry_id: z.string(),
        }),
      ),
    }),
  ),
  notes: z.string(),
})
export type ComplianceResult = z.infer<typeof ComplianceResult>

export const Report = z.object({
  title: z.string(),
  decision: z.enum(["approved", "approved_with_conditions", "rejected"]),
  risk_rating: RiskLevel,
  executive_summary: z.string(),
  sections: z.array(z.object({ title: z.string(), body: z.string() })),
  conditions: z.array(z.string()),
  evidence: z.array(Evidence),
})
export type Report = z.infer<typeof Report>

export const Handoff = z.object({
  id: z.string(),
  source: z.string(),
  target: z.string(),
  task: z.string(),
  rationale: z.string(),
  created_at: z.string(),
})

export const TrajectoryStep = z.object({
  kind: z.enum(["handoff", "tool_call", "llm_call", "approval", "submit"]),
  agent: z.string(),
  name: z.string(),
  ok: z.boolean(),
  detail: z.string().nullable(),
  arguments: z.record(z.string(), z.unknown()),
  tokens: z.number(),
  at: z.string(),
})
export type TrajectoryStep = z.infer<typeof TrajectoryStep>

export const ApprovalOutcome = z.object({
  approved: z.boolean(),
  edited: z.boolean(),
  automatic: z.boolean(),
  reviewer: z.string(),
  comment: z.string().nullable(),
  risk_rating: RiskLevel,
  conditions: z.array(z.string()),
  summary: z.string(),
  decided_at: z.string(),
})

export const RunState = z.object({
  vendor: Vendor,
  budget: Budget,
  usage: z.object({
    input_tokens: z.number(),
    output_tokens: z.number(),
    cost_usd: z.number(),
    llm_calls: z.number(),
    tool_calls: z.number(),
  }),
  handoffs: z.array(Handoff),
  trajectory: z.array(TrajectoryStep),
  active_handoff: Handoff.nullable(),
  research: ResearchFindings.nullable(),
  risk: RiskAssessment.nullable(),
  compliance: ComplianceResult.nullable(),
  approval: ApprovalOutcome.nullable(),
  report: Report.nullable(),
})
export type RunState = z.infer<typeof RunState>

export const ApprovalRequest = z.object({
  vendor: z.string(),
  recommendation: z.enum(["approve", "approve_with_conditions", "reject"]),
  risk_rating: RiskLevel,
  risk_score: z.number(),
  compliance_status: z.string(),
  summary: z.string(),
  conditions: z.array(z.string()),
  key_findings: z.array(z.string()),
})
export type ApprovalRequest = z.infer<typeof ApprovalRequest>

export const ApprovalEdits = z.object({
  risk_rating: RiskLevel.nullable().optional(),
  conditions: z.array(z.string()).nullable().optional(),
  summary: z.string().nullable().optional(),
})

export const ApprovalDecision = z.object({
  action: z.enum(["approve", "reject", "edit"]),
  reviewer: z.string(),
  reviewer_role: z.string().nullable().optional(),
  comment: z.string().nullable(),
  edits: ApprovalEdits.nullable(),
  automatic: z.boolean(),
})

export const ApprovalStatus = z.enum(["pending", "approved", "rejected", "expired"])
export type ApprovalStatus = z.infer<typeof ApprovalStatus>

export const Approval = z.object({
  id: z.uuid(),
  run_id: z.uuid(),
  vendor_name: z.string(),
  status: ApprovalStatus,
  request: ApprovalRequest,
  assignee: z.string(),
  escalation_level: z.number(),
  due_at: z.string(),
  decision: ApprovalDecision.nullable(),
  decided_by: z.string().nullable(),
  decided_at: z.string().nullable(),
  created_at: z.string(),
})
export type Approval = z.infer<typeof Approval>

export const ApprovalPage = z.object({ items: z.array(Approval) })

export const RunDetail = RunSummary.extend({
  vendor: Vendor,
  state: RunState.nullable(),
  report: Report.nullable(),
  approvals: z.array(Approval),
})
export type RunDetail = z.infer<typeof RunDetail>

export const CheckpointSummary = z.object({
  checkpoint_id: z.string(),
  parent_checkpoint_id: z.string().nullable(),
  step: z.number(),
  source: z.string(),
  produced_by: z.string().nullable(),
  next: z.array(z.string()),
  interrupted: z.boolean(),
  created_at: z.string().nullable(),
  cost_usd: z.number(),
  total_tokens: z.number(),
})
export type CheckpointSummary = z.infer<typeof CheckpointSummary>

export const CheckpointDetail = CheckpointSummary.extend({ state: RunState.nullable() })
export type CheckpointDetail = z.infer<typeof CheckpointDetail>

export const TopologyNode = z.object({
  id: z.string(),
  label: z.string(),
  kind: z.enum(["start", "end", "supervisor", "specialist", "gate"]),
  tools: z.array(z.string()),
})
export type TopologyNode = z.infer<typeof TopologyNode>

export const Topology = z.object({
  nodes: z.array(TopologyNode),
  edges: z.array(z.object({ source: z.string(), target: z.string(), conditional: z.boolean() })),
})
export type Topology = z.infer<typeof Topology>

export const Stats = z.object({
  runs_by_status: z.record(z.string(), z.number()),
  total_runs: z.number(),
  pending_approvals: z.number(),
  total_cost_usd: z.number(),
  avg_cost_usd: z.number(),
})
export type Stats = z.infer<typeof Stats>

export const RunEvent = z.object({
  id: z.number(),
  run_id: z.string(),
  type: z.string(),
  payload: z.record(z.string(), z.unknown()),
  created_at: z.string(),
})
export type RunEvent = z.infer<typeof RunEvent>

const ScenarioScore = z.object({
  tool_sequence: z.number(),
  exact_tool_match: z.boolean(),
  handoff_order: z.number(),
  efficiency: z.number(),
  outcome: z.number(),
  reasoning: z.number(),
  overall: z.number(),
  passed: z.boolean(),
  actual_tools: z.record(z.string(), z.array(z.string())),
  actual_handoffs: z.array(z.string()),
  mismatches: z.array(z.string()),
})

export const ScenarioResult = z.object({
  scenario_id: z.string(),
  description: z.string(),
  status: z.string(),
  score: ScenarioScore.nullable(),
  judge_rationale: z.string().nullable(),
  usage: z.object({ cost_usd: z.number(), input_tokens: z.number(), output_tokens: z.number() }),
  duration_ms: z.number(),
  error: z.string().nullable(),
})
export type ScenarioResult = z.infer<typeof ScenarioResult>

export const EvalReport = z.object({
  id: z.uuid(),
  suite: z.string(),
  provider: z.string(),
  summary: z.object({
    suite: z.string(),
    provider: z.string(),
    scenarios: z.number(),
    passed: z.number(),
    pass_rate: z.number(),
    mean: z.record(z.string(), z.number()),
    total_cost_usd: z.number(),
    total_tokens: z.number(),
  }),
  results: z.object({ scenarios: z.array(ScenarioResult) }),
  created_at: z.string(),
})
export type EvalReport = z.infer<typeof EvalReport>

export const ApiError = z.object({ error: z.object({ code: z.string(), message: z.string() }) })

export const CreateRunInput = z.object({
  vendor: z.object({
    name: z.string().trim().min(2, "Enter at least two characters").max(200),
    country: z
      .string()
      .trim()
      .regex(/^[A-Za-z]{2}$/, "Use a two-letter country code, like DE or US")
      .transform((value) => value.toUpperCase()),
    website: z.string().trim().max(300).optional(),
    registration_number: z.string().trim().max(64).optional(),
    notes: z.string().trim().max(2000).optional(),
  }),
  budget: z
    .object({
      max_tokens: z.number().int().min(1000).max(2_000_000),
      max_usd: z.number().gt(0).max(50),
    })
    .optional(),
})
export type CreateRunInput = z.input<typeof CreateRunInput>

export const Session = z.object({
  name: z.string(),
  role: z.string(),
  tier: z.number().int(),
  top_tier: z.boolean(),
})
export type Session = z.infer<typeof Session>

export const DemoAccount = z.object({ name: z.string(), role: z.string(), token: z.string() })
export type DemoAccount = z.infer<typeof DemoAccount>

export type DecisionInput = {
  action: "approve" | "reject" | "edit"
  comment?: string
  edits?: { risk_rating?: RiskLevel; conditions?: string[]; summary?: string }
}
