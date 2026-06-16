"use client"

import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { ThemeProvider } from "next-themes"
import { useState, type ReactNode } from "react"

import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { isUnauthenticated } from "@/lib/api/client"
import { keys } from "@/lib/api/queries"
import { useLiveInvalidation } from "@/lib/sse"

export function LiveUpdates() {
  useLiveInvalidation()
  return null
}

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(() => {
    const queryClient: QueryClient = new QueryClient({
      queryCache: new QueryCache({
        // An expired or revoked session surfaces on whichever query runs first; send everyone to sign-in.
        onError: (error, query) => {
          if (isUnauthenticated(error) && query.queryKey[0] !== "session") {
            void queryClient.invalidateQueries({ queryKey: keys.session })
          }
        },
      }),
      defaultOptions: {
        queries: {
          staleTime: 5_000,
          refetchOnWindowFocus: true,
          retry: (failures, error) => !isUnauthenticated(error) && failures < 1,
        },
      },
    })
    return queryClient
  })
  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
      <QueryClientProvider client={client}>
        <TooltipProvider delayDuration={300}>
          {children}
          <Toaster />
        </TooltipProvider>
      </QueryClientProvider>
    </ThemeProvider>
  )
}
