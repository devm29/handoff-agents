import type { ReactNode } from "react"

import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

export function KpiTile({ label, value, hint, loading }: { label: string; value: ReactNode; hint?: ReactNode; loading?: boolean }) {
  return (
    <Card className="gap-1 px-5">
      <span className="text-[13px] text-muted-foreground">{label}</span>
      {loading ? (
        <Skeleton className="h-[34px] w-24" />
      ) : (
        <span className="text-[28px] leading-[34px] font-semibold tracking-tight tabular-nums">{value}</span>
      )}
      {hint ? <span className="text-[13px] text-muted-foreground">{hint}</span> : null}
    </Card>
  )
}
