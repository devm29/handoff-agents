import { FileText } from "lucide-react"

import { RiskBadge, ToneBadge } from "@/components/common/badges"
import { EmptyState } from "@/components/common/empty-state"
import type { Report } from "@/lib/api/schemas"
import { DECISION_LABELS } from "@/lib/format"

const SOURCE_LABEL = { company_registry: "Registry", sanctions: "Sanctions", news: "News" } as const

export function ReportView({ report, waitingOnApproval }: { report: Report | null; waitingOnApproval: boolean }) {
  if (!report) {
    return (
      <EmptyState
        icon={FileText}
        title="No report yet"
        description={
          waitingOnApproval
            ? "The report writer runs after a reviewer signs off on the recommendation."
            : "The report writer produces the memo once research, risk and sanctions screening are approved."
        }
      />
    )
  }
  const tone = report.decision === "rejected" ? "destructive" : report.decision === "approved" ? "success" : "warning"
  return (
    <article className="mx-auto max-w-3xl space-y-6 px-1 py-2">
      <header className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <ToneBadge tone={tone}>{DECISION_LABELS[report.decision]}</ToneBadge>
          <RiskBadge rating={report.risk_rating} />
        </div>
        <h3 className="text-[22px] leading-7 font-semibold tracking-tight">{report.title}</h3>
        <p className="text-[15px] leading-[22px] text-muted-foreground">{report.executive_summary}</p>
      </header>
      {report.conditions.length > 0 ? (
        <section className="rounded-xl bg-warning/10 p-4">
          <h4 className="mb-2 text-[13px] font-semibold">Conditions</h4>
          <ul className="list-disc space-y-1 pl-5 text-[13px] leading-5">
            {report.conditions.map((condition) => (
              <li key={condition}>{condition}</li>
            ))}
          </ul>
        </section>
      ) : null}
      {report.sections.map((section) => (
        <section key={section.title} className="space-y-1.5">
          <h4 className="text-[15px] font-semibold">{section.title}</h4>
          <p className="text-[14px] leading-[22px] whitespace-pre-line text-foreground/90">{section.body}</p>
        </section>
      ))}
      {report.evidence.length > 0 ? (
        <section className="space-y-2">
          <h4 className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Evidence</h4>
          <ul className="divide-y divide-border rounded-xl bg-secondary/60">
            {report.evidence.map((item) => (
              <li key={`${item.source}-${item.reference}`} className="flex items-start gap-3 px-4 py-2.5 text-[13px]">
                <span className="w-20 shrink-0 text-muted-foreground">{SOURCE_LABEL[item.source]}</span>
                <span className="min-w-0 flex-1">{item.summary}</span>
                <code className="shrink-0 font-mono text-[11px] text-muted-foreground">{item.reference}</code>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </article>
  )
}
