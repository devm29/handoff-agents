import { Compass } from "lucide-react"
import Link from "next/link"

import { EmptyState } from "@/components/common/empty-state"
import { Button } from "@/components/ui/button"

export default function NotFound() {
  return (
    <EmptyState
      icon={Compass}
      title="This page does not exist"
      description="The link may be out of date."
      action={
        <Button asChild>
          <Link href="/">Back to runs</Link>
        </Button>
      }
    />
  )
}
