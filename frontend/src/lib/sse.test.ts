import { afterEach, describe, expect, it, vi } from "vitest"

import { parseEventFrame, throttle } from "@/lib/sse"

describe("parseEventFrame", () => {
  it("returns the event for a valid frame", () => {
    const frame = JSON.stringify({ id: 4, run_id: "r", type: "run.status", payload: { status: "running" }, created_at: "2026-10-04T12:00:00Z" })
    expect(parseEventFrame(frame)?.payload).toEqual({ status: "running" })
  })

  it("ignores malformed JSON and frames of the wrong shape instead of throwing", () => {
    expect(parseEventFrame("{not json")).toBeNull()
    expect(parseEventFrame(JSON.stringify({ id: "x" }))).toBeNull()
  })
})

describe("throttle", () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it("coalesces calls and can be cancelled before it fires", () => {
    vi.useFakeTimers()
    const fn = vi.fn()
    const throttled = throttle(fn, 100)
    throttled()
    throttled()
    vi.advanceTimersByTime(100)
    expect(fn).toHaveBeenCalledTimes(1)

    throttled()
    throttled.cancel()
    vi.advanceTimersByTime(500)
    expect(fn).toHaveBeenCalledTimes(1)
  })
})
