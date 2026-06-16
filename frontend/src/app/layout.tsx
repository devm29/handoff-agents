import type { Metadata } from "next"
import { Inter } from "next/font/google"
import type { ReactNode } from "react"

import { AuthGate } from "@/components/auth/auth-gate"
import { LiveUpdates, Providers } from "@/components/providers"
import { AppSidebar } from "@/components/shell/app-sidebar"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"

import "./globals.css"

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" })

export const metadata: Metadata = {
  title: { default: "Handoff", template: "%s · Handoff" },
  description: "Durable multi-agent vendor due diligence with human approval gates.",
}

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={inter.variable} suppressHydrationWarning>
      <body>
        <Providers>
          <AuthGate>
            <LiveUpdates />
            <SidebarProvider>
              <AppSidebar />
              <SidebarInset className="min-w-0 bg-secondary/60 dark:bg-background">{children}</SidebarInset>
            </SidebarProvider>
          </AuthGate>
        </Providers>
      </body>
    </html>
  )
}
