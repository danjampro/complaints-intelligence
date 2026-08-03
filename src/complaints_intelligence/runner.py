"""Orchestrating one weekly run.

Assembles the collaborators, runs the graph, assembles the report object, and
renders it. This is the only place that knows how the pieces fit together, so
the CLI stays a thin wrapper and tests can drive a run with a fake client.
"""

from __future__ import annotations

from pathlib import Path

from complaints_intelligence import __version__
from complaints_intelligence.agent.budgets import BudgetLedger
from complaints_intelligence.agent.graph import run_graph
from complaints_intelligence.agent.state import RunContext, RunState
from complaints_intelligence.agent.tools import ToolBelt
from complaints_intelligence.config import Settings
from complaints_intelligence.domain.brief import MetricsBrief
from complaints_intelligence.domain.finding import FindingKind
from complaints_intelligence.domain.report import Report, ReportStatus
from complaints_intelligence.domain.trace import PinnedVersions, RunTrace
from complaints_intelligence.llm.protocol import LLMClient
from complaints_intelligence.logging import bind_run_context, get_logger
from complaints_intelligence.prompts.loader import prompt_hashes
from complaints_intelligence.render.renderer import render_markdown, utc_now
from complaints_intelligence.store.duckdb_store import DuckDBStore

log = get_logger(__name__)


def run_week(
    *,
    settings: Settings,
    store: DuckDBStore,
    llm: LLMClient,
    brief: MetricsBrief,
) -> tuple[Report, str]:
    """Run the agent for one week and render its report.

    Returns the report object and its Markdown rendering. The object is the
    record; the Markdown is a projection of it.
    """
    versions = PinnedVersions(
        taxonomy_version=brief.taxonomy_version,
        prompt_version=settings.llm.prompt_version,
        prompt_hashes=prompt_hashes(settings.llm.prompt_version),
        model=llm.model,
        llm_mode=llm.mode,
        package_version=__version__,
        synth_seed=settings.synth.seed,
    )
    bind_run_context(
        run_id=brief.run_id,
        taxonomy_version=versions.taxonomy_version,
        prompt_version=versions.prompt_version,
        model=versions.model,
        llm_mode=versions.llm_mode,
    )

    ledger = BudgetLedger(config=settings.budget)
    context = RunContext(
        settings=settings,
        store=store,
        tools=ToolBelt(store, ledger),
        llm=llm,
        ledger=ledger,
    )

    started = utc_now()
    final = run_graph(context, RunState(brief=brief))

    trace = RunTrace(
        run_id=brief.run_id,
        started_at=started,
        versions=versions,
        tool_calls=context.tools.calls,
        llm_calls=tuple(context.llm_calls),
        node_sequence=tuple(context.node_sequence),
        notes=tuple(ledger.notes),
    )

    if final.critic is None:  # pragma: no cover - the graph always runs critic
        msg = "the run completed without verification; refusing to emit a report"
        raise RuntimeError(msg)

    report = Report(
        run_id=brief.run_id,
        week=brief.week,
        baseline_week=brief.baseline_week,
        generated_at=started,
        # Always a draft. The system drafts; a named human publishes. Nothing
        # in this package performs that transition.
        status=ReportStatus.DRAFT,
        drivers=tuple(f for f in final.findings if f.kind is FindingKind.DRIVER),
        sentiment=tuple(f for f in final.findings if f.kind is FindingKind.SENTIMENT),
        emerging=tuple(
            f for f in final.findings if f.kind is FindingKind.EMERGING_THEME
        ),
        adjudications=tuple(final.adjudications),
        remediations=tuple(final.remediations),
        critic=final.critic,
        trace=trace,
    )

    markdown = render_markdown(report, facts=store, complaints=store)
    return report, markdown


def write_outputs(report: Report, markdown: str, output_dir: Path) -> tuple[Path, Path]:
    """Write the report object and its rendering.

    Both are written. The Markdown is what a person reads; the JSON is the
    immutable record, and it is what a later run would be reconstructed from.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / "report.md"
    json_path = output_dir / "report.json"

    markdown_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return markdown_path, json_path
