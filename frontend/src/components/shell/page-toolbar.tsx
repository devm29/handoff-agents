import type { ReactNode } from "react"

import { Separator } from "@/components/ui/separator"
import { SidebarTrigger } from "@/components/ui/sidebar"

export function PageToolbar({ title, leading, actions }: { title: ReactNode; leading?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="material sticky top-0 z-30 flex h-13 shrink-0 items-center gap-2 border-b border-border/60 bg-background/72 px-4 backdrop-blur-xl backdrop-saturate-[1.8]">
      <SidebarTrigger className="-ml-1" aria-label="Toggle sidebar" />
      <Separator orientation="vertical" className="mx-1 data-[orientation=vertical]:h-4" />
      {leading}
      <h1 className="min-w-0 truncate text-[15px] font-semibold">{title}</h1>
      <div className="ml-auto flex items-center gap-2">{actions}</div>
    </header>
  )
}
