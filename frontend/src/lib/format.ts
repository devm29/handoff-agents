import type { RunStatus } from "@/lib/api/schemas"

const usdSmall = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 4 })
const usdLarge = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 })
const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 })
const relative = new Intl.RelativeTimeFormat("en", { numeric: "auto" })
const dateTime = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })

export function formatUsd(value: number): string {
  return (Math.abs(value) >= 1 ? usdLarge : usdSmall).format(value)
}

export function formatTokens(value: number): string {
  return compact.format(value)
}

export function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`
}

export function formatDateTime(iso: string): string {
  return dateTime.format(new Date(iso))
}

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["day", 86_400],
  ["hour", 3_600],
  ["minute", 60],
  ["second", 1],
]

export function formatRelative(iso: string, now: Date = new Date()): string {
  const seconds = Math.round((new Date(iso).getTime() - now.getTime()) / 1000)
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size || unit === "second") {
      return relative.format(Math.round(seconds / size), unit)
    }
  }
  return relative.format(0, "second")
}

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`
  const seconds = ms / 1000
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} s`
  const minutes = Math.floor(seconds / 60)
  return `${minutes} min ${Math.round(seconds % 60)} s`
}

export const NODE_LABELS: Record<string, string> = {
  __start__: "Start",
  __end__: "End",
  supervisor: "Supervisor",
  researcher: "Researcher",
  risk_analyst: "Risk analyst",
  compliance_checker: "Compliance checker",
  approval: "Human approval",
  report_writer: "Report writer",
  finish: "Finish",
  input: "Input",
  fork: "Fork",
}

export function nodeLabel(node: string | null | undefined): string {
  if (!node) return "Unknown"
  return NODE_LABELS[node] ?? node.replaceAll("_", " ")
}

type Tone = "info" | "success" | "warning" | "destructive" | "neutral"

export const RUN_STATUS_META: Record<RunStatus, { label: string; tone: Tone }> = {
  queued: { label: "Queued", tone: "neutral" },
  running: { label: "Running", tone: "info" },
  awaiting_approval: { label: "Needs approval", tone: "warning" },
  completed: { label: "Completed", tone: "success" },
  rejected: { label: "Rejected", tone: "destructive" },
  failed: { label: "Failed", tone: "destructive" },
  cancelled: { label: "Cancelled", tone: "neutral" },
}

export const RISK_TONE: Record<string, Tone> = {
  low: "success",
  medium: "warning",
  high: "destructive",
  critical: "destructive",
}

export const DECISION_LABELS: Record<string, string> = {
  approved: "Approved",
  approved_with_conditions: "Approved with conditions",
  rejected: "Rejected",
  approve: "Approve",
  approve_with_conditions: "Approve with conditions",
  reject: "Reject",
}

export function sentenceCase(value: string): string {
  const text = value.replaceAll(/[_-]/g, " ")
  return text.charAt(0).toUpperCase() + text.slice(1)
}
