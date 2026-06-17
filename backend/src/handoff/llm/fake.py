"""Deterministic stand-in for the model, used offline, in tests and in evals.

Each agent gets a scripted policy that reads the handoff input and the tool results so
far and decides the next tool call or the final submission, the same way the real model
is prompted to. Token usage is estimated from message sizes so budgets still bite.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, Literal

from handoff.agents.briefing import parse_briefing
from handoff.agents.schemas import (
    RISK_ORDER,
    BeneficialOwner,
    ComplianceResult,
    DueDiligenceReport,
    Evidence,
    NewsItem,
    ReportSection,
    ResearchFindings,
    RiskAssessment,
    RiskCategory,
    RiskFactor,
    RiskLevel,
    RouteTarget,
    ScreenedEntity,
    ScreeningHit,
    ScreeningResult,
    SupervisorDecision,
)
from handoff.errors import ModelError
from handoff.llm.types import (
    AssistantMessage,
    ChatRequest,
    ChatResponse,
    StopReason,
    TokenUsage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)

FAKE_MODEL = "scripted-fake"
ADVERSE_QUERY = "lawsuit litigation fine breach investigation recall bankruptcy sanctions fraud aml export"
_COMPANY_MARKERS = ("ltd", "llc", "inc", "lp", "holdings", "group", "ventures", "gmbh", "s.a.")
_SEVERITY_POINTS: dict[RiskLevel, int] = {"low": 10, "medium": 25, "high": 45, "critical": 80}
_TOPIC_CATEGORY: dict[str, RiskCategory] = {
    "cyber": "cyber",
    "data breach": "cyber",
    "regulatory": "legal",
    "fine": "legal",
    "investigation": "legal",
    "aml": "legal",
    "litigation": "legal",
    "labor": "legal",
    "recall": "operational",
    "quality": "operational",
    "bankruptcy": "financial",
    "financial": "financial",
    "sanctions": "reputational",
    "export controls": "legal",
    "ownership": "reputational",
}


class ToolExchange:
    def __init__(self, call: ToolCall, content: str, is_error: bool) -> None:
        self.call = call
        self.is_error = is_error
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = None
        self.result: dict[str, Any] = parsed if isinstance(parsed, dict) else {}


class Transcript:
    def __init__(self, request: ChatRequest) -> None:
        first = next((m for m in request.messages if isinstance(m, UserMessage)), None)
        self.briefing = first.text if first else ""
        self.payload = parse_briefing(self.briefing)
        self.exchanges: list[ToolExchange] = []
        pending: dict[str, ToolCall] = {}
        for message in request.messages:
            if isinstance(message, AssistantMessage):
                pending.update({c.id: c for c in message.tool_calls})
            elif isinstance(message, ToolResultMessage):
                for result in message.results:
                    call = pending.pop(result.call_id, None)
                    if call is not None:
                        self.exchanges.append(ToolExchange(call, result.content, result.is_error))

    def calls(self, tool: str) -> list[ToolExchange]:
        return [e for e in self.exchanges if e.call.name == tool]


Decision = ToolCall | str
Script = Callable[[Transcript], Decision]


class ScriptedFakeProvider:
    def __init__(self, *, latency_ms: int = 0, today: date | None = None) -> None:
        self._latency = latency_ms / 1000
        self._today = today
        self._calls = 0
        self._tripped: set[str] = set()
        self._scripts: dict[str, Script] = {
            "supervisor": self._supervisor,
            "researcher": self._researcher,
            "risk_analyst": self._risk_analyst,
            "compliance_checker": self._compliance_checker,
            "report_writer": self._report_writer,
            "judge": self._judge,
        }

    @property
    def provider_name(self) -> str:
        return "fake"

    @property
    def default_model(self) -> str:
        return FAKE_MODEL

    async def chat(self, request: ChatRequest) -> ChatResponse:
        if self._latency:
            await asyncio.sleep(self._latency)
        script = self._scripts.get(request.agent)
        if script is None:
            raise ModelError(f"no scripted policy for agent {request.agent}", retryable=False)

        transcript = Transcript(request)
        self._maybe_fail(request, transcript)
        decision = script(transcript)
        self._calls += 1
        stop: StopReason
        if isinstance(decision, str):
            message = AssistantMessage(text=decision)
            stop = "end_turn"
        else:
            message = AssistantMessage(text="", tool_calls=[decision])
            stop = "tool_use"

        prompt_chars = len(request.system) + sum(len(m.model_dump_json()) for m in request.messages)
        prompt_chars += sum(len(json.dumps(t.input_schema)) for t in request.tools)
        output_chars = len(message.model_dump_json())
        return ChatResponse(
            message=message,
            stop_reason=stop,
            usage=TokenUsage(input_tokens=prompt_chars // 4, output_tokens=output_chars // 4 + 60),
            model=FAKE_MODEL,
            response_id=f"fake_{self._calls:06d}",
        )

    def _maybe_fail(self, request: ChatRequest, transcript: Transcript) -> None:
        """`simulate:flaky-model` in the vendor notes makes each specialist's first call fail once."""
        vendor = transcript.payload.get("vendor", {})
        notes = str(vendor.get("notes") or "")
        if "simulate:flaky-model" not in notes or request.agent == "supervisor" or transcript.exchanges:
            return
        key = hashlib.sha1(f"{request.agent}:{transcript.briefing}".encode()).hexdigest()
        if key not in self._tripped:
            self._tripped.add(key)
            raise ModelError("Simulated upstream overload (529)", retryable=True, details={"status": 529})

    def _call(self, tool: str, **arguments: Any) -> ToolCall:
        self._calls += 1
        return ToolCall(id=f"toolu_fake_{self._calls:06d}", name=tool, arguments=arguments)

    def _supervisor(self, t: Transcript) -> Decision:
        done: list[str] = t.payload.get("completed", [])
        plan: list[tuple[RouteTarget, str]] = [
            ("researcher", "Identify the legal entity, its ownership and recent news coverage."),
            ("risk_analyst", "Assess adverse media and corporate risk; score and rate the vendor."),
            ("compliance_checker", "Screen the entity and every beneficial owner against sanctions lists."),
            ("approval", "Request sign-off on the recommendation."),
            ("report_writer", "Write the due-diligence memo reflecting the reviewer decision."),
        ]
        for target, task in plan:
            if target not in done:
                decision = SupervisorDecision(
                    next=target, task=task, rationale=f"{target.replace('_', ' ')} has not run yet"
                )
                return self._call("handoff", **decision.model_dump(mode="json"))
        finish = SupervisorDecision(next="finish", task="Close the review.", rationale="Report is complete")
        return self._call("handoff", **finish.model_dump(mode="json"))

    def _researcher(self, t: Transcript) -> Decision:
        vendor = t.payload["vendor"]
        lookups = t.calls("company_registry_lookup")
        if not lookups:
            return self._call("company_registry_lookup", name=vendor["name"], country=vendor["country"])

        last = lookups[-1].result
        matches: list[dict[str, Any]] = last.get("matches", [])
        if last.get("ambiguous") and len(lookups) == 1:
            wanted = vendor.get("registration_number")
            chosen = next((m for m in matches if m["registration_number"] == wanted), None)
            chosen = chosen or next((m for m in matches if m["status"] == "active"), matches[0])
            return self._call(
                "company_registry_lookup",
                name=vendor["name"],
                registration_number=chosen["registration_number"],
            )

        record = matches[0] if matches else None
        legal_name = record["legal_name"] if record else vendor["name"]
        news_calls = t.calls("news_search")
        if not news_calls:
            return self._call("news_search", query=legal_name)

        news = [NewsItem.model_validate(item) for item in news_calls[-1].result.get("items", [])]
        evidence = [Evidence(source="news", reference=n.id, summary=n.headline) for n in news]
        if record is None:
            findings = ResearchFindings(
                legal_name=vendor["name"],
                registration_number=None,
                jurisdiction=vendor["country"],
                status="unknown",
                incorporated_on=None,
                industry=None,
                address=None,
                summary=f"No registry record found for {vendor['name']} in {vendor['country']}.",
                news=news,
                evidence=evidence,
            )
        else:
            owners = [BeneficialOwner.model_validate(o) for o in record["beneficial_owners"]]
            evidence.insert(
                0,
                Evidence(
                    source="company_registry",
                    reference=record["registration_number"],
                    summary=f"{record['legal_name']} is {record['status']} in {record['jurisdiction']}",
                ),
            )
            findings = ResearchFindings(
                legal_name=record["legal_name"],
                registration_number=record["registration_number"],
                jurisdiction=record["jurisdiction"],
                status=record["status"],
                incorporated_on=record["incorporated_on"],
                industry=record["industry"],
                address=record["address"],
                beneficial_owners=owners,
                news=news,
                summary=(
                    f"{record['legal_name']} ({record['registration_number']}) is an {record['status']} "
                    f"{record['industry'].lower()} business incorporated on {record['incorporated_on']}, "
                    f"owned by {', '.join(o.name for o in owners)}. {len(news)} news item(s) found."
                ),
                evidence=evidence,
            )
        return self._call("submit_research", **findings.model_dump(mode="json"))

    def _risk_analyst(self, t: Transcript) -> Decision:
        research = ResearchFindings.model_validate(t.payload["research"])
        searches = t.calls("news_search")
        if not searches:
            return self._call("news_search", query=ADVERSE_QUERY, company=research.legal_name)
        if len(searches) == 1 and searches[0].result.get("total", 0) == 0:
            return self._call("news_search", query=research.legal_name)

        adverse = [
            NewsItem.model_validate(item)
            for search in searches
            for item in search.result.get("items", [])
            if item["sentiment"] <= -0.3
        ]
        unique = {n.id: n for n in adverse}.values()
        factors: list[RiskFactor] = []
        if research.status in ("dissolved", "suspended", "unknown"):
            factors.append(
                RiskFactor(
                    category="corporate",
                    description=f"Registry status is {research.status}; the entity cannot reliably contract.",
                    severity="critical" if research.status == "dissolved" else "high",
                    evidence=[research.registration_number or "registry:none"],
                )
            )
        if research.incorporated_on is not None:
            age_days = ((self._today or datetime.now(UTC).date()) - research.incorporated_on).days
            if age_days < 548:
                factors.append(
                    RiskFactor(
                        category="corporate",
                        description=f"Incorporated {age_days // 30} months ago; limited operating history.",
                        severity="medium",
                        evidence=[research.registration_number or "registry"],
                    )
                )
        for item in unique:
            severity: RiskLevel = (
                "high" if item.sentiment <= -0.75 else "medium" if item.sentiment <= -0.5 else "low"
            )
            category: RiskCategory = next(
                (_TOPIC_CATEGORY[tp] for tp in item.topics if tp in _TOPIC_CATEGORY), "reputational"
            )
            factors.append(
                RiskFactor(
                    category=category, description=item.headline, severity=severity, evidence=[item.id]
                )
            )

        score = min(100, sum(_SEVERITY_POINTS[f.severity] for f in factors))
        by_score: RiskLevel = (
            "low" if score < 20 else "medium" if score < 45 else "high" if score < 75 else "critical"
        )
        worst: RiskLevel = max((f.severity for f in factors), key=lambda s: RISK_ORDER[s], default="low")
        rating: RiskLevel = by_score if RISK_ORDER[by_score] >= RISK_ORDER[worst] else worst
        rationale = (
            "No adverse media or corporate red flags were found."
            if not factors
            else f"{len(factors)} risk factor(s) identified; the most severe is rated {worst}."
        )
        assessment = RiskAssessment(rating=rating, score=score, factors=factors, rationale=rationale)
        return self._call("submit_risk_assessment", **assessment.model_dump(mode="json"))

    def _compliance_checker(self, t: Transcript) -> Decision:
        research = ResearchFindings.model_validate(t.payload["research"])
        entities: list[tuple[str, str]] = [(research.legal_name, "company")]
        for owner in research.beneficial_owners:
            lowered = owner.name.lower()
            kind = "company" if any(marker in lowered for marker in _COMPANY_MARKERS) else "person"
            entities.append((owner.name, kind))

        done = {e.call.arguments.get("name") for e in t.calls("sanctions_check")}
        for name, kind in entities:
            if name not in done:
                return self._call("sanctions_check", name=name, kind=kind)

        screened: list[ScreenedEntity] = []
        for exchange in t.calls("sanctions_check"):
            r = exchange.result
            hits = [
                ScreeningHit(
                    list_name=m["list_name"],
                    matched_name=m["matched_name"],
                    score=m["score"],
                    program=m["program"],
                    entry_id=m["entry_id"],
                )
                for m in r.get("matches", [])
            ]
            screened.append(ScreenedEntity(name=r["name"], kind=r["kind"], result=r["result"], hits=hits))
        status: ScreeningResult = "clear"
        if any(s.result == "match" for s in screened):
            status = "match"
        elif any(s.result == "potential_match" for s in screened):
            status = "potential_match"
        flagged = [s for s in screened if s.result != "clear"]
        lists_checked = {
            name for e in t.calls("sanctions_check") for name in e.result.get("lists_checked", [])
        }
        notes = (
            f"Screened {len(screened)} entities against {len(lists_checked)} lists; no hits."
            if not flagged
            else "; ".join(
                f"{s.name}: {s.result.replace('_', ' ')} with {s.hits[0].matched_name} "
                f"({s.hits[0].list_name}, {s.hits[0].entry_id}, score {s.hits[0].score:.2f})"
                for s in flagged
            )
        )
        result = ComplianceResult(status=status, screened=screened, notes=notes)
        return self._call("submit_compliance", **result.model_dump(mode="json"))

    def _report_writer(self, t: Transcript) -> Decision:
        p = t.payload
        research = ResearchFindings.model_validate(p["research"])
        risk = RiskAssessment.model_validate(p["risk"])
        compliance = ComplianceResult.model_validate(p["compliance"])
        approval: dict[str, Any] = p["approval"]
        rating: RiskLevel = approval["risk_rating"]
        conditions: list[str] = approval.get("conditions", [])
        decision: Literal["approved", "approved_with_conditions", "rejected"]
        if not approval["approved"]:
            decision = "rejected"
        elif conditions:
            decision = "approved_with_conditions"
        else:
            decision = "approved"

        owners = (
            ", ".join(
                f"{o.name} ({o.ownership_pct:g}%)" if o.ownership_pct is not None else o.name
                for o in research.beneficial_owners
            )
            or "No ownership data on file."
        )
        factor_lines = "\n".join(
            f"- [{f.severity}] {f.description} ({', '.join(f.evidence)})" for f in risk.factors
        )
        reviewer = "the automatic approval policy" if approval.get("automatic") else approval["reviewer"]
        decision_text = {
            "approved": "approved for onboarding",
            "approved_with_conditions": "approved for onboarding subject to the conditions below",
            "rejected": "rejected",
        }[decision]
        sections = [
            ReportSection(title="Entity overview", body=research.summary),
            ReportSection(title="Ownership", body=owners),
            ReportSection(
                title="Risk assessment",
                body=f"Rated {rating} (score {risk.score}/100). {risk.rationale}"
                + (f"\n{factor_lines}" if factor_lines else ""),
            ),
            ReportSection(
                title="Sanctions screening",
                body=f"Overall result: {compliance.status.replace('_', ' ')}. {compliance.notes}",
            ),
            ReportSection(
                title="Decision",
                body=f"The vendor was {decision_text} by {reviewer}."
                + (f" Reviewer note: {approval['comment']}" if approval.get("comment") else ""),
            ),
        ]
        evidence = list(research.evidence)
        evidence.extend(
            Evidence(
                source="sanctions",
                reference=h.entry_id,
                summary=f"{s.name} vs {h.matched_name} ({h.score:.2f})",
            )
            for s in compliance.screened
            for h in s.hits
        )
        report = DueDiligenceReport(
            title=f"Vendor due diligence: {research.legal_name}",
            decision=decision,
            risk_rating=rating,
            executive_summary=(
                f"{research.legal_name} is rated {rating} risk with sanctions screening "
                f"{compliance.status.replace('_', ' ')}. The vendor was {decision_text}."
            ),
            sections=sections,
            conditions=conditions,
            evidence=evidence,
        )
        return self._call("submit_report", **report.model_dump(mode="json"))

    def _judge(self, t: Transcript) -> Decision:
        """Heuristic rubric that mirrors the judge prompt: evidence, consistency, coverage."""
        p = t.payload
        report: dict[str, Any] = p.get("report") or {}
        risk: dict[str, Any] = p.get("risk") or {}
        compliance: dict[str, Any] = p.get("compliance") or {}
        score = 5
        notes: list[str] = []
        if not report:
            return self._call("submit_judgement", score=1, rationale="No report was produced.")
        if any(not f.get("evidence") for f in risk.get("factors", [])):
            score -= 1
            notes.append("some risk factors lack evidence")
        if compliance.get("status") == "match" and report.get("decision") != "rejected":
            score -= 2
            notes.append("a confirmed sanctions match did not lead to rejection")
        cited = {e["reference"] for e in report.get("evidence", [])}
        uncited = [
            r
            for f in risk.get("factors", [])
            for r in f.get("evidence", [])
            if r not in cited and r.startswith("news")
        ]
        if uncited:
            score -= 1
            notes.append(f"{len(uncited)} risk evidence reference(s) missing from the report")
        if risk.get("rating") in ("high", "critical") and len(risk.get("factors", [])) < 2:
            score -= 1
            notes.append("high rating rests on a single factor")
        rationale = (
            "Reasoning is consistent and fully evidenced."
            if not notes
            else "; ".join(notes).capitalize() + "."
        )
        return self._call("submit_judgement", score=max(1, score), rationale=rationale)
