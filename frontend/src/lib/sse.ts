"use client"

import { useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef, useState } from "react"

import { keys } from "@/lib/api/queries"
import { apiUrl } from "@/lib/api/client"
import { RunEvent } from "@/lib/api/schemas"

export const EVENT_TYPES = [
  "run.status",
  "node.started",
  "node.completed",
  "node.failed",
  "handoff",
  "llm.call",
  "tool.call",
  "approval.requested",
  "approval.decided",
  "approval.escalated",
] as const

const REFRESHING = new Set(["run.status", "node.completed", "node.failed", "approval.requested", "approval.decided"])

type Throttled = { (): void; cancel: () => void }

export function throttle(fn: () => void, waitMs: number): Throttled {
  let timer: ReturnType<typeof setTimeout> | null = null
  const run = () => {
    if (timer !== null) return
    timer = setTimeout(() => {
      timer = null
      fn()
    }, waitMs)
  }
  return Object.assign(run, {
    cancel: () => {
      if (timer !== null) clearTimeout(timer)
      timer = null
    },
  })
}

export function parseEventFrame(data: string): RunEvent | null {
  let raw: unknown
  try {
    raw = JSON.parse(data)
  } catch {
    return null
  }
  const parsed = RunEvent.safeParse(raw)
  return parsed.success ? parsed.data : null
}

export function useRunEvents(runId: string): { events: RunEvent[]; connected: boolean } {
  const client = useQueryClient()
  const [stream, setStream] = useState<{ runId: string; events: RunEvent[] }>({ runId, events: [] })
  const [connected, setConnected] = useState(false)
  const buffer = useRef<RunEvent[]>([])

  useEffect(() => {
    buffer.current = []
    const source = new EventSource(apiUrl(`/runs/${runId}/events`), { withCredentials: true })
    let frame = 0
    const refresh = throttle(() => {
      void client.invalidateQueries({ queryKey: keys.run(runId) })
      void client.invalidateQueries({ queryKey: keys.checkpoints(runId) })
    }, 400)

    const flush = () => {
      frame = 0
      const batch = buffer.current
      buffer.current = []
      setStream((current) => {
        const existing = current.runId === runId ? current.events : []
        const seen = new Set(existing.map((e) => e.id))
        return { runId, events: [...existing, ...batch.filter((e) => !seen.has(e.id))] }
      })
    }

    const onMessage = (message: MessageEvent<string>) => {
      const event = parseEventFrame(message.data)
      if (event === null) return
      buffer.current.push(event)
      if (frame === 0) frame = requestAnimationFrame(flush)
      if (REFRESHING.has(event.type)) refresh()
    }

    for (const type of EVENT_TYPES) source.addEventListener(type, onMessage)
    source.onopen = () => setConnected(true)
    source.onerror = () => setConnected(false)
    return () => {
      if (frame !== 0) cancelAnimationFrame(frame)
      refresh.cancel()
      source.close()
    }
  }, [client, runId])

  return { events: stream.runId === runId ? stream.events : [], connected }
}

export function useLiveInvalidation(): void {
  const client = useQueryClient()
  useEffect(() => {
    const source = new EventSource(apiUrl("/events"), { withCredentials: true })
    const refresh = throttle(() => {
      void client.invalidateQueries({ queryKey: keys.allRuns })
      void client.invalidateQueries({ queryKey: keys.stats })
      void client.invalidateQueries({ queryKey: keys.approvals })
    }, 600)
    const types = ["run.status", "approval.requested", "approval.decided", "approval.escalated", "resync"]
    for (const type of types) source.addEventListener(type, refresh)
    return () => {
      refresh.cancel()
      source.close()
    }
  }, [client])
}
