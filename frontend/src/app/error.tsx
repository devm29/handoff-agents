"use client"

import { AlertTriangle } from "lucide-react"

import { EmptyState } from "@/components/common/empty-state"
import { Button } from "@/components/ui/button"

export default function ErrorPage({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <EmptyState
      icon={AlertTriangle}
      title="Something went wrong"
      description="The page hit an unexpected error. Try again, and check the API logs if it keeps happening."
      action={<Button onClick={reset}>Try again</Button>}
    />
  )
}
