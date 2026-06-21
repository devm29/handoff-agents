"use client"

import {
  Background,
  type Edge,
  Handle,
  MarkerType,
  type Node,
  type NodeProps,
  Position,
  ReactFlow,
  useReactFlow,
  useStore,
} from "@xyflow/react"
import {
  Check,
  FileText,
  Flag,
  Gauge,
  type LucideIcon,
  Network,
  Play,
  Search,
  ShieldCheck,
  UserCheck,
  X,
} from "lucide-react"
import { memo, useEffect, useMemo } from "react"

import { Skeleton } from "@/components/ui/skeleton"
import { usePrefersReducedMotion } from "@/hooks/use-reduced-motion"
import type { Topology } from "@/lib/api/schemas"
import { formatDuration } from "@/lib/format"
import { edgeId, type GraphActivity, type NodeActivity, type NodeStatus } from "@/lib/graph-status"
import { cn } from "@/lib/utils"

const POSITIONS: Record<string, { x: number; y: number }> = {
  __start__: { x: 0, y: 268 },
  supervisor: { x: 130, y: 244 },
  researcher: { x: 480, y: 0 },
  risk_analyst: { x: 480, y: 124 },
  compliance_checker: { x: 480, y: 248 },
  approval: { x: 480, y: 372 },
  report_writer: { x: 480, y: 496 },
  __end__: { x: 172, y: 460 },
}

const ICONS: Record<string, LucideIcon> = {
  __start__: Play,
  __end__: Flag,
  supervisor: Network,
  researcher: Search,
  risk_analyst: Gauge,
  compliance_checker: ShieldCheck,
  approval: UserCheck,
  report_writer: FileText,
}

const STATUS_TEXT: Record<NodeStatus, string> = {
  idle: "Not started",
  running: "Working",
  retrying: "Retrying",
  waiting: "Waiting for approval",
  done: "Done",
  failed: "Failed",
}

type AgentData = {
  label: string
  kind: Topology["nodes"][number]["kind"]
  tools: string[]
  activity: NodeActivity | undefined
  selected: boolean
}

type AgentNode = Node<AgentData, "agent">

const IDLE: NodeActivity = { status: "idle", executions: 0, attempt: 0, lastDurationMs: null, error: null }

const AgentCard = memo(function AgentCard({ id, data }: NodeProps<AgentNode>) {
  const activity = data.activity ?? IDLE
  const Icon = ICONS[id] ?? Network
  const terminal = data.kind === "start" || data.kind === "end"
  const status = activity.status

  if (terminal) {
    return (
      <div
        className={cn(
          "flex h-10 items-center gap-2 rounded-full border bg-card px-3.5 text-[13px] font-medium shadow-xs",
          status === "done" ? "border-success/50 text-foreground" : "border-border text-muted-foreground",
        )}
      >
        <Icon className="size-3.5" strokeWidth={1.75} aria-hidden />
        {data.label}
        <Handle type="source" position={Position.Right} />
        <Handle type="target" position={Position.Top} />
      </div>
    )
  }

  return (
    <div
      className={cn(
        "w-[214px] rounded-xl border bg-card px-3 py-2.5 shadow-xs transition-[border-color,box-shadow,opacity] duration-200",
        status === "idle" && "border-border/70",
        status === "running" && "border-primary shadow-[0_0_0_4px] shadow-primary/15",
        status === "retrying" && "border-warning shadow-[0_0_0_4px] shadow-warning/15",
        status === "waiting" && "border-warning shadow-[0_0_0_4px] shadow-warning/15",
        status === "done" && "border-border",
        status === "failed" && "border-destructive shadow-[0_0_0_4px] shadow-destructive/15",
        data.selected && "ring-2 ring-primary/60",
      )}
    >
      <Handle type="target" position={Position.Left} id="in" style={{ top: "38%" }} />
      <Handle type="source" position={Position.Left} id="back" style={{ top: "68%" }} />
      <Handle type="source" position={Position.Right} id="out" style={{ top: "38%" }} />
      <Handle type="target" position={Position.Right} id="return" style={{ top: "68%" }} />
      <Handle type="source" position={Position.Bottom} id="end" />
      <div className="flex items-center gap-2.5">
        <span
          className={cn(
            "flex size-7 shrink-0 items-center justify-center rounded-lg",
            data.kind === "gate" ? "bg-warning/15 text-warning" : "bg-primary/10 text-primary",
          )}
        >
          <Icon className="size-4" strokeWidth={1.75} aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] leading-4 font-semibold">{data.label}</div>
          <div className="mt-0.5 flex items-center gap-1.5 text-[11px] leading-4 text-muted-foreground">
            <StatusGlyph status={status} />
            <span className="truncate">
              {STATUS_TEXT[status]}
              {activity.attempt > 1 && status !== "done" ? ` · attempt ${activity.attempt}` : ""}
            </span>
          </div>
        </div>
        {activity.executions > 0 ? (
          <span className="text-[11px] text-muted-foreground tabular-nums" title="Completed executions">
            ×{activity.executions}
          </span>
        ) : null}
      </div>
      {data.tools.length > 0 ? (
        <div className="mt-2 flex gap-1 overflow-hidden">
          {data.tools.map((tool) => (
            <span key={tool} className="truncate rounded-md bg-secondary px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
              {tool}
            </span>
          ))}
        </div>
      ) : null}
      {activity.error && status !== "done" ? (
        <p className="mt-1.5 truncate text-[11px] text-destructive" title={activity.error.message}>
          {activity.error.kind}: {activity.error.message}
        </p>
      ) : activity.lastDurationMs !== null ? (
        <p className="mt-1.5 text-[11px] text-muted-foreground tabular-nums">Last run {formatDuration(activity.lastDurationMs)}</p>
      ) : null}
    </div>
  )
})

function StatusGlyph({ status }: { status: NodeStatus }) {
  if (status === "done") return <Check className="size-3 text-success" strokeWidth={2.5} aria-hidden />
  if (status === "failed") return <X className="size-3 text-destructive" strokeWidth={2.5} aria-hidden />
  const tone =
    status === "running" ? "bg-primary" : status === "idle" ? "bg-muted-foreground/40" : "bg-warning"
  return (
    <span
      className={cn("size-1.5 rounded-full", tone, (status === "running" || status === "retrying") && "status-pulse")}
      aria-hidden
    />
  )
}

const nodeTypes = { agent: AgentCard }

const FIT_PADDING = 0.12

function FitOnResize() {
  const { fitView } = useReactFlow()
  const width = useStore((store) => store.width)
  useEffect(() => {
    if (width > 0) void fitView({ padding: FIT_PADDING })
  }, [width, fitView])
  return null
}

function handlesFor(source: string, target: string): { sourceHandle?: string; targetHandle?: string } {
  if (source === "__start__") return { targetHandle: "in" }
  if (target === "__end__") return { sourceHandle: "end" }
  if (source === "supervisor") return { sourceHandle: "out", targetHandle: "in" }
  if (target === "supervisor") return { sourceHandle: "back", targetHandle: "return" }
  return {}
}

export function AgentGraph({
  topology,
  activity,
  selected,
  onSelect,
}: {
  topology: Topology | undefined
  activity: GraphActivity
  selected: string | null
  onSelect: (node: string | null) => void
}) {
  const reducedMotion = usePrefersReducedMotion()
  const nodes = useMemo<AgentNode[]>(
    () =>
      (topology?.nodes ?? []).map((node) => ({
        id: node.id,
        type: "agent",
        position: POSITIONS[node.id] ?? { x: 0, y: 0 },
        data: {
          label: node.label,
          kind: node.kind,
          tools: node.tools,
          activity: activity.nodes[node.id],
          selected: selected === node.id,
        },
        draggable: false,
        connectable: false,
      })),
    [topology, activity, selected],
  )

  const edges = useMemo<Edge[]>(
    () =>
      (topology?.edges ?? []).flatMap((edge) => {
        const id = edgeId(edge.source, edge.target)
        const isReturn = edge.target === "supervisor" && edge.source !== "__start__"
        const traversed = activity.traversed.has(id)
        const active = activity.activeEdge === id
        if (isReturn && !active) return []
        return {
          id,
          source: edge.source,
          target: edge.target,
          ...handlesFor(edge.source, edge.target),
          type: "default",
          animated: active && !reducedMotion,
          markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
          style: {
            stroke: active ? "var(--color-primary)" : traversed ? "var(--color-muted-foreground)" : "var(--color-border)",
            strokeWidth: active ? 2 : 1.5,
            strokeDasharray: traversed || active ? undefined : "4 4",
          },
        }
      }),
    [topology, activity, reducedMotion],
  )

  if (!topology) return <Skeleton className="h-[480px] w-full rounded-xl" />

  return (
    <div className="h-[340px] w-full sm:h-[480px]" role="group" aria-label="Agent graph with live node status">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: FIT_PADDING }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable
        zoomOnScroll={false}
        panOnScroll={false}
        preventScrolling={false}
        minZoom={0.4}
        maxZoom={1.4}
        onNodeClick={(_, node) => onSelect(selected === node.id ? null : node.id)}
        onPaneClick={() => onSelect(null)}
      >
        <Background gap={20} size={1} color="var(--color-border)" />
        <FitOnResize />
      </ReactFlow>
    </div>
  )
}
