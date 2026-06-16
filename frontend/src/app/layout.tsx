import type { Metadata } from "next"
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google"
import type { ReactNode } from "react"

import { AuthGate } from "@/components/auth/auth-gate"
import { LiveUpdates, Providers } from "@/components/providers"
import { AppSidebar } from "@/components/shell/app-sidebar"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"

import "./globals.css"

const plexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-plex-sans",
  display: "swap",
})
const plexMono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-plex-mono", display: "swap" })

export const metadata: Metadata = {
  title: { default: "Handoff", template: "%s · Handoff" },
  description: "Durable multi-agent vendor due diligence with human approval gates.",
}

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${plexSans.variable} ${plexMono.variable}`} suppressHydrationWarning>
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
