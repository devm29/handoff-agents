from __future__ import annotations

from rich.console import Console
from rich.table import Table

from handoff.evals.runner import EvalSummary, ScenarioResult


def _pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def render(console: Console, summary: EvalSummary, results: list[ScenarioResult]) -> None:
    table = Table(title=f"Trajectory evals: {summary.suite} ({summary.provider})", title_justify="left")
    table.add_column("Scenario", style="bold")
    table.add_column("Result")
    table.add_column("Tool seq", justify="right")
    table.add_column("Handoffs", justify="right")
    table.add_column("Efficiency", justify="right")
    table.add_column("Outcome", justify="right")
    table.add_column("Reasoning", justify="right")
    table.add_column("Overall", justify="right")
    table.add_column("Cost", justify="right")
    for r in results:
        s = r.score
        status = {"passed": "[green]pass[/]", "failed": "[yellow]fail[/]"}.get(r.status, "[red]error[/]")
        if s is None:
            table.add_row(r.scenario_id, status, *["-"] * 6, f"${r.usage.cost_usd:.3f}")
            continue
        table.add_row(
            r.scenario_id,
            status,
            _pct(s.tool_sequence),
            _pct(s.handoff_order),
            _pct(s.efficiency),
            _pct(s.outcome),
            _pct(s.reasoning),
            f"{s.overall:.2f}",
            f"${r.usage.cost_usd:.3f}",
        )
    m = summary.mean
    table.add_section()
    table.add_row(
        "mean",
        f"{summary.passed}/{summary.scenarios}",
        _pct(m["tool_sequence"]),
        _pct(m["handoff_order"]),
        _pct(m["efficiency"]),
        _pct(m["outcome"]),
        _pct(m["reasoning"]),
        f"{m['overall']:.2f}",
        f"${summary.total_cost_usd:.3f}",
        style="bold",
    )
    console.print(table)
    for r in results:
        if r.error:
            console.print(f"[red]{r.scenario_id}[/]: {r.error}")
        elif r.score and r.score.mismatches:
            console.print(f"[dim]{r.scenario_id}[/]: " + "; ".join(r.score.mismatches))
