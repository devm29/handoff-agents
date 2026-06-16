"use client"

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { api } from "./client"
import type { CreateRunInput, DecisionInput, RunStatus } from "./schemas"

export const keys = {
  runs: (filter: { status: readonly RunStatus[]; q: string }) => ["runs", filter] as const,
  allRuns: ["runs"] as const,
  run: (runId: string) => ["run", runId] as const,
  checkpoints: (runId: string) => ["run", runId, "checkpoints"] as const,
  checkpoint: (runId: string, checkpointId: string) => ["run", runId, "checkpoint", checkpointId] as const,
  approvals: ["approvals"] as const,
  stats: ["stats"] as const,
  topology: ["topology"] as const,
  evals: ["evals"] as const,
  health: ["health"] as const,
  session: ["session"] as const,
  demoAccounts: ["session", "demo-accounts"] as const,
}

export function useRuns(filter: { status: readonly RunStatus[]; q: string }) {
  return useInfiniteQuery({
    queryKey: keys.runs(filter),
    queryFn: ({ pageParam }) => api.runs({ cursor: pageParam, status: filter.status, q: filter.q }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  })
}

export function useRun(runId: string) {
  return useQuery({ queryKey: keys.run(runId), queryFn: () => api.run(runId) })
}

export function useCheckpoints(runId: string) {
  return useQuery({ queryKey: keys.checkpoints(runId), queryFn: () => api.checkpoints(runId) })
}

export function useCheckpoint(runId: string, checkpointId: string | null) {
  return useQuery({
    queryKey: keys.checkpoint(runId, checkpointId ?? ""),
    queryFn: () => api.checkpoint(runId, checkpointId ?? ""),
    enabled: checkpointId !== null,
  })
}

export function useApprovals() {
  return useQuery({ queryKey: keys.approvals, queryFn: () => api.approvals() })
}

export function useStats() {
  return useQuery({ queryKey: keys.stats, queryFn: api.stats })
}

export function useTopology() {
  return useQuery({ queryKey: keys.topology, queryFn: api.topology, staleTime: Infinity })
}

export function useEvalReports() {
  return useQuery({ queryKey: keys.evals, queryFn: api.evalReports })
}

export function useHealth() {
  return useQuery({ queryKey: keys.health, queryFn: api.health, refetchInterval: 15_000, retry: false })
}

export function useCreateRun() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: CreateRunInput) => api.createRun(input),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.allRuns })
      void client.invalidateQueries({ queryKey: keys.stats })
    },
  })
}

export function useCancelRun(runId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api.cancelRun(runId),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.run(runId) })
      void client.invalidateQueries({ queryKey: keys.allRuns })
    },
  })
}

export function useFork(runId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ checkpointId, patch }: { checkpointId: string; patch: Record<string, unknown> }) =>
      api.fork(runId, checkpointId, patch),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.allRuns })
    },
  })
}

export function useDecide() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ approvalId, decision }: { approvalId: string; decision: DecisionInput }) =>
      api.decide(approvalId, decision),
    onSuccess: (approval) => {
      void client.invalidateQueries({ queryKey: keys.approvals })
      void client.invalidateQueries({ queryKey: keys.run(approval.run_id) })
      void client.invalidateQueries({ queryKey: keys.stats })
    },
  })
}

export function useSession() {
  return useQuery({ queryKey: keys.session, queryFn: api.session, retry: false, staleTime: 60_000 })
}

export function useDemoAccounts() {
  return useQuery({ queryKey: keys.demoAccounts, queryFn: api.demoAccounts, staleTime: Infinity })
}

export function useSignIn() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (token: string) => api.signIn(token),
    onSuccess: (session) => {
      client.setQueryData(keys.session, session)
      void client.invalidateQueries({ predicate: (query) => query.queryKey[0] !== "session" })
    },
  })
}

export function useSignOut() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: api.signOut,
    onSuccess: () => {
      client.removeQueries({ predicate: (query) => query.queryKey[0] !== "session" })
      void client.resetQueries({ queryKey: keys.session })
    },
  })
}
