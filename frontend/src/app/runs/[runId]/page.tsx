import type { Metadata } from "next"
import { notFound } from "next/navigation"
import { z } from "zod"

import { RunInspector } from "@/components/inspector/run-inspector"

export const metadata: Metadata = { title: "Run inspector" }

export default async function RunPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params
  const parsed = z.uuid().safeParse(runId)
  if (!parsed.success) notFound()
  return <RunInspector runId={parsed.data} />
}
