import { AlertTriangle } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"

export function ErrorNotice({ title, error }: { title: string; error: unknown }) {
  const message = error instanceof Error ? error.message : "Something went wrong."
  return (
    <Alert variant="destructive" role="alert">
      <AlertTriangle strokeWidth={1.75} aria-hidden />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>{message} Check that the API is running on port 8104, then try again.</AlertDescription>
    </Alert>
  )
}
