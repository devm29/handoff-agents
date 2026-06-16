import type { LucideIcon } from "lucide-react"
import type { ReactNode } from "react"

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: LucideIcon
  title: string
  description: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-16 text-center">
      <Icon className="mb-2 size-10 text-muted-foreground/70" strokeWidth={1.5} aria-hidden />
      <h2 className="text-[17px] leading-[22px] font-semibold">{title}</h2>
      <p className="max-w-sm text-[13px] leading-[18px] text-muted-foreground">{description}</p>
      {action ? <div className="mt-3">{action}</div> : null}
    </div>
  )
}
