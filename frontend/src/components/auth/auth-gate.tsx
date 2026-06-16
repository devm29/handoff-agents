"use client"

import { ChevronRight, KeyRound, Workflow } from "lucide-react"
import { type FormEvent, type ReactNode, useState } from "react"

import { ErrorNotice } from "@/components/common/error-notice"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { isUnauthenticated } from "@/lib/api/client"
import { useDemoAccounts, useSession, useSignIn } from "@/lib/api/queries"
import { sentenceCase } from "@/lib/format"

export function AuthGate({ children }: { children: ReactNode }) {
  const session = useSession()
  if (session.isPending) {
    return (
      <div className="flex min-h-dvh items-center justify-center" aria-busy="true" aria-label="Checking your session">
        <Skeleton className="h-10 w-48" />
      </div>
    )
  }
  if (session.isError && !isUnauthenticated(session.error)) {
    return (
      <main className="mx-auto flex min-h-dvh w-full max-w-md items-center px-4">
        <ErrorNotice title="Handoff could not reach its API" error={session.error} />
      </main>
    )
  }
  if (session.isError) return <SignIn />
  return children
}

function SignIn() {
  const demo = useDemoAccounts()
  const signIn = useSignIn()
  const [token, setToken] = useState("")
  const accounts = demo.data ?? []
  const failed = signIn.isError ? signIn.error.message : null

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (token.trim()) signIn.mutate(token.trim())
  }

  return (
    <main className="flex min-h-dvh items-center justify-center bg-secondary/60 px-4 py-12 dark:bg-background">
      <div className="w-full max-w-sm space-y-8">
        <header className="flex flex-col items-center gap-3 text-center">
          <span className="flex size-12 items-center justify-center rounded-2xl bg-primary text-primary-foreground shadow-xs">
            <Workflow className="size-6" strokeWidth={1.75} aria-hidden />
          </span>
          <h1 className="text-[28px] leading-[34px] font-semibold tracking-tight">Sign in to Handoff</h1>
          <p className="text-[15px] leading-[22px] text-muted-foreground">
            Decisions are signed with your reviewer account, so the audit trail shows who approved what.
          </p>
        </header>

        {accounts.length > 0 ? (
          <section className="space-y-2" aria-labelledby="demo-accounts">
            <h2 id="demo-accounts" className="px-4 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
              Demo reviewers
            </h2>
            <ul className="divide-y divide-border overflow-hidden rounded-xl border border-border/60 bg-card">
              {accounts.map((account) => (
                <li key={account.token}>
                  <button
                    type="button"
                    disabled={signIn.isPending}
                    onClick={() => signIn.mutate(account.token)}
                    className="flex min-h-11 w-full items-center justify-between gap-3 px-4 py-2 text-left transition-colors duration-150 outline-none hover:bg-accent/60 focus-visible:bg-accent/60 focus-visible:ring-4 focus-visible:ring-ring focus-visible:ring-inset disabled:opacity-60"
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-[14px] font-medium">{account.name}</span>
                      <span className="block text-xs text-muted-foreground">{sentenceCase(account.role)}</span>
                    </span>
                    <ChevronRight className="size-4 shrink-0 text-muted-foreground" strokeWidth={1.75} aria-hidden />
                  </button>
                </li>
              ))}
            </ul>
            <p className="px-4 text-xs text-muted-foreground">
              Shown only in local development. Each role can decide approvals up to its escalation tier.
            </p>
          </section>
        ) : null}

        <form onSubmit={submit} className="space-y-3 rounded-xl border border-border/60 bg-card p-5" noValidate>
          <div className="space-y-1.5">
            <Label htmlFor="token" className="text-[13px] font-medium">
              Access token
            </Label>
            <Input
              id="token"
              type="password"
              autoComplete="current-password"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              aria-invalid={failed ? true : undefined}
              aria-describedby={failed ? "token-error" : undefined}
            />
            {failed ? (
              <p id="token-error" role="alert" className="text-xs text-destructive">
                {failed} Check the token and try again.
              </p>
            ) : null}
          </div>
          <Button type="submit" className="w-full" disabled={signIn.isPending || token.trim() === ""}>
            <KeyRound strokeWidth={1.75} aria-hidden data-icon="inline-start" />
            {signIn.isPending ? "Signing in…" : "Sign in"}
          </Button>
        </form>
      </div>
    </main>
  )
}
