import { describe, expect, it } from "vitest"

import { CreateRunInput } from "@/lib/api/schemas"
import { formatDuration, formatRelative, formatUsd, nodeLabel } from "@/lib/format"

describe("format", () => {
  it("formats money with precision that fits the amount", () => {
    expect(formatUsd(0.1219)).toBe("$0.1219")
    expect(formatUsd(1.2743)).toBe("$1.27")
    expect(formatUsd(0)).toBe("$0.00")
  })

  it("formats relative times and durations", () => {
    const now = new Date("2026-10-04T12:00:00Z")
    expect(formatRelative("2026-10-04T10:00:00Z", now)).toBe("2 hours ago")
    expect(formatRelative("2026-10-04T12:45:00Z", now)).toBe("in 45 minutes")
    expect(formatDuration(850)).toBe("850 ms")
    expect(formatDuration(4_200)).toBe("4.2 s")
    expect(formatDuration(125_000)).toBe("2 min 5 s")
  })

  it("labels graph nodes", () => {
    expect(nodeLabel("compliance_checker")).toBe("Compliance checker")
    expect(nodeLabel("custom_node")).toBe("custom node")
    expect(nodeLabel(null)).toBe("Unknown")
  })
})

describe("CreateRunInput", () => {
  it("normalises the country code and rejects bad input with guidance", () => {
    const parsed = CreateRunInput.parse({ vendor: { name: "  Helios Components ", country: "gb" } })
    expect(parsed.vendor).toEqual({ name: "Helios Components", country: "GB" })
    const invalid = CreateRunInput.safeParse({ vendor: { name: "H", country: "GBR" } })
    expect(invalid.success).toBe(false)
    expect(invalid.error?.issues.map((i) => i.message)).toContain("Use a two-letter country code, like DE or US")
  })
})
