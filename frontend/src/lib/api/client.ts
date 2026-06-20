import { z } from "zod"

import { env } from "@/lib/env"
import {
  ApiError,
  Approval,
  ApprovalPage,
  CheckpointDetail,
  CheckpointSummary,
  CreateRunInput,
  type DecisionInput,
  DemoAccount,
  EvalReport,
  RunDetail,
  RunEvent,
  RunPage,
  RunSummary,
  type RunStatus,
  Session,
  Stats,
  Topology,
} from "./schemas"

export class ApiRequestError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
  ) {
    super(message)
    this.name = "ApiRequestError"
  }
}

type Query = Record<string, string | number | readonly string[] | undefined>

const LOOPBACK = new Set(["localhost", "127.0.0.1"])

// The session cookie is SameSite=Lax, so the API must be same-site with the page. Locally that
// means matching whichever loopback name the browser used rather than the one baked in at build.
function apiBase(): string {
  const base = new URL(env.NEXT_PUBLIC_API_URL)
  if (typeof window !== "undefined" && LOOPBACK.has(base.hostname) && LOOPBACK.has(window.location.hostname)) {
    base.hostname = window.location.hostname
  }
  return base.toString().replace(/\/$/, "")
}

export function apiUrl(path: string, query?: Query): string {
  const url = new URL(`${apiBase()}${path}`)
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value === undefined) continue
    if (Array.isArray(value)) {
      for (const item of value) url.searchParams.append(key, item)
    } else {
      url.searchParams.set(key, String(value))
    }
  }
  return url.toString()
}

async function request<T>(schema: z.ZodType<T>, path: string, init?: RequestInit & { query?: Query }): Promise<T> {
  const { query, ...rest } = init ?? {}
  const response = await fetch(apiUrl(path, query), {
    ...rest,
    headers: { "content-type": "application/json", ...rest.headers },
    cache: "no-store",
    credentials: "include",
  })
  if (response.status === 204) return schema.parse(undefined)
  const body: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    const parsed = ApiError.safeParse(body)
    const message = parsed.success ? parsed.data.error.message : `Request failed with status ${response.status}`
    throw new ApiRequestError(message, response.status, parsed.success ? parsed.data.error.code : "http_error")
  }
  return schema.parse(body)
}

export const api = {
  runs: (params: { cursor?: string | undefined; status?: readonly RunStatus[]; q?: string; limit?: number }) =>
    request(RunPage, "/runs", {
      query: { cursor: params.cursor, status: params.status, q: params.q || undefined, limit: params.limit ?? 20 },
    }),
  run: (runId: string) => request(RunDetail, `/runs/${runId}`),
  createRun: (input: CreateRunInput) =>
    request(RunSummary, "/runs", { method: "POST", body: JSON.stringify(CreateRunInput.parse(input)) }),
  cancelRun: (runId: string) => request(RunSummary, `/runs/${runId}/cancel`, { method: "POST" }),
  checkpoints: (runId: string) => request(z.array(CheckpointSummary), `/runs/${runId}/checkpoints`),
  checkpoint: (runId: string, checkpointId: string) =>
    request(CheckpointDetail, `/runs/${runId}/checkpoints/${checkpointId}`),
  fork: (runId: string, checkpointId: string, statePatch: Record<string, unknown>) =>
    request(RunSummary, `/runs/${runId}/fork`, {
      method: "POST",
      body: JSON.stringify({ checkpoint_id: checkpointId, state_patch: statePatch }),
    }),
  eventHistory: (runId: string) => request(z.array(RunEvent), `/runs/${runId}/events/history`, { query: { limit: 1000 } }),
  approvals: (status?: readonly string[]) => request(ApprovalPage, "/approvals", { query: { status, limit: 100 } }),
  decide: (approvalId: string, decision: DecisionInput) =>
    request(Approval, `/approvals/${approvalId}/decision`, { method: "POST", body: JSON.stringify(decision) }),
  topology: () => request(Topology, "/graph"),
  stats: () => request(Stats, "/stats"),
  evalReports: () => request(z.array(EvalReport), "/evals/reports", { query: { limit: 10 } }),
  health: () => request(z.object({ status: z.string(), events: z.string() }), "/healthz"),
  session: () => request(Session, "/session"),
  signIn: (token: string) => request(Session, "/session", { method: "POST", body: JSON.stringify({ token }) }),
  signOut: () => request(z.undefined(), "/session", { method: "DELETE" }),
  demoAccounts: () => request(z.array(DemoAccount), "/session/demo-accounts"),
}

export function isUnauthenticated(error: unknown): boolean {
  return error instanceof ApiRequestError && error.status === 401
}
