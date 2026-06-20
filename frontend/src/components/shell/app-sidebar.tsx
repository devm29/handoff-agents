"use client"

import { FlaskConical, Inbox, ListChecks, LogOut, Workflow } from "lucide-react"
import Link from "next/link"
import { usePathname } from "next/navigation"

import { ThemeToggle } from "@/components/shell/theme-toggle"
import { Button } from "@/components/ui/button"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useHealth, useSession, useSignOut, useStats } from "@/lib/api/queries"
import { sentenceCase } from "@/lib/format"
import { cn } from "@/lib/utils"

const NAV = [
  { href: "/", label: "Runs", icon: ListChecks, match: (path: string) => path === "/" || path.startsWith("/runs") },
  { href: "/approvals", label: "Approvals", icon: Inbox, match: (path: string) => path.startsWith("/approvals") },
  { href: "/evals", label: "Evals", icon: FlaskConical, match: (path: string) => path.startsWith("/evals") },
] as const

export function AppSidebar() {
  const pathname = usePathname()
  const stats = useStats()
  const health = useHealth()
  const session = useSession()
  const signOut = useSignOut()
  const pending = stats.data?.pending_approvals ?? 0
  const online = health.isSuccess

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="px-3 pt-4 pb-2">
        <Link href="/" className="flex items-center gap-2.5 rounded-md outline-none focus-visible:ring-4 focus-visible:ring-ring">
          <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <Workflow className="size-[18px]" strokeWidth={1.75} aria-hidden />
          </span>
          <span className="flex min-w-0 flex-col group-data-[collapsible=icon]:hidden">
            <span className="text-[15px] leading-5 font-semibold">Handoff</span>
            <span className="truncate text-xs text-muted-foreground">Vendor due diligence</span>
          </span>
        </Link>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel className="text-[11px] font-medium tracking-wide uppercase">Workspace</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {NAV.map((item) => (
                <SidebarMenuItem key={item.href}>
                  <SidebarMenuButton asChild isActive={item.match(pathname)} tooltip={item.label}>
                    <Link href={item.href}>
                      <item.icon strokeWidth={1.75} aria-hidden />
                      <span>{item.label}</span>
                    </Link>
                  </SidebarMenuButton>
                  {item.href === "/approvals" && pending > 0 ? (
                    <SidebarMenuBadge className="tabular-nums" aria-label={`${pending} pending approvals`}>
                      {pending}
                    </SidebarMenuBadge>
                  ) : null}
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter className="gap-3 px-3 pb-3">
        {session.data ? (
          <div className="flex items-center gap-2.5 group-data-[collapsible=icon]:hidden">
            <span
              className="flex size-8 shrink-0 items-center justify-center rounded-full bg-secondary text-[12px] font-semibold"
              aria-hidden
            >
              {initials(session.data.name)}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[13px] font-medium">{session.data.name}</span>
              <span className="block truncate text-xs text-muted-foreground">{sentenceCase(session.data.role)}</span>
            </span>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label="Sign out"
                  disabled={signOut.isPending}
                  onClick={() => signOut.mutate()}
                >
                  <LogOut strokeWidth={1.75} aria-hidden />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Sign out</TooltipContent>
            </Tooltip>
          </div>
        ) : null}
        <div className="flex items-center justify-between gap-2 group-data-[collapsible=icon]:flex-col">
          <div className="flex items-center gap-2 text-xs text-muted-foreground group-data-[collapsible=icon]:hidden">
            <span
              className={cn("size-2 rounded-full", online ? "bg-success" : "bg-destructive")}
              aria-hidden
            />
            <span>{online ? "API connected" : "API unreachable"}</span>
          </div>
          <ThemeToggle />
        </div>
      </SidebarFooter>
    </Sidebar>
  )
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part.charAt(0).toUpperCase())
    .join("")
}
