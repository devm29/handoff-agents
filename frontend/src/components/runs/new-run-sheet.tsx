"use client"

import { Plus } from "lucide-react"
import { useRouter } from "next/navigation"
import { useState, type FormEvent } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet"
import { Textarea } from "@/components/ui/textarea"
import { useCreateRun } from "@/lib/api/queries"
import { CreateRunInput } from "@/lib/api/schemas"

const SAMPLES = [
  { name: "Helios Components", country: "GB" },
  { name: "Corvane Trading", country: "AE" },
  { name: "Quantum Ledger", country: "EE" },
  { name: "Bluefin Analytics", country: "GB" },
  { name: "Northwind Logistics", country: "DE" },
] as const

type Form = {
  name: string
  country: string
  website: string
  registration: string
  notes: string
  maxTokens: string
  maxUsd: string
}

const EMPTY: Form = { name: "", country: "", website: "", registration: "", notes: "", maxTokens: "120000", maxUsd: "1.50" }

function optional(value: string): string | undefined {
  const trimmed = value.trim()
  return trimmed === "" ? undefined : trimmed
}

export function NewRunSheet() {
  const router = useRouter()
  const create = useCreateRun()
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState<Form>(EMPTY)
  const [errors, setErrors] = useState<Partial<Record<keyof Form, string>>>({})

  const set = (key: keyof Form) => (value: string) => setForm((current) => ({ ...current, [key]: value }))

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const vendor: Record<string, string> = { name: form.name, country: form.country }
    const website = optional(form.website)
    const registration = optional(form.registration)
    const notes = optional(form.notes)
    if (website) vendor.website = website
    if (registration) vendor.registration_number = registration
    if (notes) vendor.notes = notes
    const parsed = CreateRunInput.safeParse({
      vendor,
      budget: { max_tokens: Number(form.maxTokens), max_usd: Number(form.maxUsd) },
    })
    if (!parsed.success) {
      const next: Partial<Record<keyof Form, string>> = {}
      for (const issue of parsed.error.issues) {
        const path = issue.path.join(".")
        if (path === "vendor.name") next.name = issue.message
        else if (path === "vendor.country") next.country = issue.message
        else if (path === "budget.max_tokens") next.maxTokens = "Use a whole number between 1,000 and 2,000,000"
        else if (path === "budget.max_usd") next.maxUsd = "Use an amount above $0 and up to $50"
      }
      setErrors(next)
      return
    }
    setErrors({})
    create.mutate(parsed.data, {
      onSuccess: (run) => {
        toast.success(`Started due diligence for ${run.vendor_name}`)
        setOpen(false)
        setForm(EMPTY)
        router.push(`/runs/${run.id}`)
      },
      onError: (error) => toast.error(error.message),
    })
  }

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button>
          <Plus strokeWidth={1.75} aria-hidden data-icon="inline-start" />
          New run
        </Button>
      </SheetTrigger>
      <SheetContent className="w-full gap-0 sm:max-w-md">
        <form onSubmit={submit} className="flex h-full flex-col" noValidate>
          <SheetHeader className="border-b border-border/60 px-6 py-5">
            <SheetTitle className="text-[17px] font-semibold">New due-diligence run</SheetTitle>
            <SheetDescription>
              The supervisor researches the vendor, scores risk, screens sanctions and asks for sign-off when needed.
            </SheetDescription>
          </SheetHeader>
          <div className="flex-1 space-y-5 overflow-y-auto px-6 py-5">
            <div className="space-y-2">
              <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Try a sample</span>
              <div className="flex flex-wrap gap-1.5">
                {SAMPLES.map((sample) => (
                  <Button
                    key={sample.name}
                    type="button"
                    variant="secondary"
                    size="sm"
                    className="rounded-full"
                    onClick={() => setForm((current) => ({ ...current, name: sample.name, country: sample.country }))}
                  >
                    {sample.name}
                  </Button>
                ))}
              </div>
            </div>
            <Field id="vendor-name" label="Vendor name" error={errors.name}>
              <Input
                id="vendor-name"
                value={form.name}
                onChange={(e) => set("name")(e.target.value)}
                placeholder="Helios Components"
                autoComplete="off"
                {...describedBy("vendor-name", errors.name)}
              />
            </Field>
            <div className="grid grid-cols-2 gap-4">
              <Field id="vendor-country" label="Country" error={errors.country}>
                <Input
                  id="vendor-country"
                  value={form.country}
                  onChange={(e) => set("country")(e.target.value)}
                  placeholder="GB"
                  maxLength={2}
                  className="uppercase"
                  {...describedBy("vendor-country", errors.country)}
                />
              </Field>
              <Field id="vendor-registration" label="Registry number">
                <Input
                  id="vendor-registration"
                  value={form.registration}
                  onChange={(e) => set("registration")(e.target.value)}
                  placeholder="Optional"
                />
              </Field>
            </div>
            <Field id="vendor-website" label="Website">
              <Input
                id="vendor-website"
                value={form.website}
                onChange={(e) => set("website")(e.target.value)}
                placeholder="Optional"
              />
            </Field>
            <Field id="vendor-notes" label="Context for the reviewers">
              <Textarea
                id="vendor-notes"
                value={form.notes}
                onChange={(e) => set("notes")(e.target.value)}
                placeholder="What will this vendor supply?"
                rows={3}
              />
            </Field>
            <div className="space-y-3 rounded-xl bg-secondary/70 p-4">
              <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Budget</span>
              <div className="grid grid-cols-2 gap-4">
                <Field id="budget-tokens" label="Max tokens" error={errors.maxTokens}>
                  <Input
                    id="budget-tokens"
                    inputMode="numeric"
                    value={form.maxTokens}
                    onChange={(e) => set("maxTokens")(e.target.value)}
                    className="tabular-nums"
                    {...describedBy("budget-tokens", errors.maxTokens)}
                  />
                </Field>
                <Field id="budget-usd" label="Max spend (USD)" error={errors.maxUsd}>
                  <Input
                    id="budget-usd"
                    inputMode="decimal"
                    value={form.maxUsd}
                    onChange={(e) => set("maxUsd")(e.target.value)}
                    className="tabular-nums"
                    {...describedBy("budget-usd", errors.maxUsd)}
                  />
                </Field>
              </div>
            </div>
          </div>
          <SheetFooter className="flex-row justify-end gap-2 border-t border-border/60 px-6 py-4">
            <Button type="button" variant="secondary" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? "Starting…" : "Start run"}
            </Button>
          </SheetFooter>
        </form>
      </SheetContent>
    </Sheet>
  )
}

function errorId(id: string): string {
  return `${id}-error`
}

function describedBy(id: string, error: string | undefined): { "aria-invalid"?: true; "aria-describedby"?: string } {
  return error ? { "aria-invalid": true, "aria-describedby": errorId(id) } : {}
}

function Field({ id, label, error, children }: { id: string; label: string; error?: string | undefined; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id} className="text-[13px] font-medium">
        {label}
      </Label>
      {children}
      {error ? (
        <p id={errorId(id)} className="text-xs text-destructive" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  )
}
