"""Orchestrating one weekly run.

The only place that knows how the pieces fit together, so the CLI stays a thin
wrapper and tests can drive a full run with a fake client.
"""

from __future__ import annotations

from pathlib import Path

from complaints_intelligence.agent.graph import run_graph
from complaints_intelligence.agent.state import (
    BudgetLedger,
    RunContext,
    RunState,
)
from complaints_intelligence.agent.tools import ToolBelt
from complaints_intelligence.config import Settings
from complaints_intelligence.inputs import MetricsBrief
from complaints_intelligence.llm.client import LLMClient
from complaints_intelligence.outputs import (
    FindingKind,
    Report,
    ReportStatus,
    RunTrace,
)
from complaints_intelligence.render import render_markdown, utc_now
from complaints_intelligence.store import Store


def run_week(
    *, settings: Settings, store: Store, llm: LLMClient, brief: MetricsBrief
) -> tuple[Report, str]:
    """Run the agent for one week and render its report.

    Returns the report object and its Markdown rendering: the object is the
    record, and the Markdown is a projection of it.
    """
    ledger = BudgetLedger(config=settings.budget)
    tools = ToolBelt(store, ledger)
    context = RunContext(
        settings=settings, store=store, llm=llm, ledger=ledger, tools=tools
    )

    started = utc_now()
    final = run_graph(context, RunState(brief=brief))
    if final.critic is None:  # pragma: no cover - the graph always runs critic
        msg = "the run completed without verification; refusing to emit a report"
        raise RuntimeError(msg)

    report = Report(
        run_id=brief.run_id,
        week=brief.week,
        baseline_week=brief.baseline_week,
        generated_at=started,
        status=ReportStatus.DRAFT,
        drivers=tuple(f for f in final.findings if f.kind is FindingKind.DRIVER),
        # Straight from the brief, untouched by the graph: every figure was
        # computed by the metrics layer and is referenced by fact ID.
        sentiment=brief.sentiment_signals,
        emerging=tuple(
            f for f in final.findings if f.kind is FindingKind.EMERGING_THEME
        ),
        adjudications=tuple(final.adjudications),
        remediations=tuple(final.remediations),
        critic=final.critic,
        trace=RunTrace(
            model=llm.model,
            llm_mode=llm.mode,
            prompt_version=settings.llm.prompt_version,
            taxonomy_version=brief.taxonomy_version,
            node_sequence=tuple(context.node_sequence),
            llm_calls=ledger.llm_calls,
            tool_calls=ledger.tool_calls,
            notes=tuple(ledger.notes),
        ),
    )
    return report, render_markdown(report, store)


def write_outputs(report: Report, markdown: str, output_dir: Path) -> tuple[Path, Path]:
    """Write the rendering a person reads and the JSON record a later run would
    be reconstructed from."""
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / "report.md"
    json_path = output_dir / "report.json"
    markdown_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return markdown_path, json_path
