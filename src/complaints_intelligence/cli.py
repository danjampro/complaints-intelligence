"""Command-line entry point.

The demo path is ``ci demo``: generate fixtures, derive facts, run the agent
offline against committed cassettes, render the report. No credentials, no
network (invariant 5).
"""

from __future__ import annotations

import typer

from complaints_intelligence import __version__
from complaints_intelligence.config import (
    BASELINE_WEEK,
    REPORTING_WEEK,
    TAXONOMY_VERSION,
    load_settings,
)
from complaints_intelligence.errors import (
    CassetteMissError,
    ComplaintsIntelligenceError,
)
from complaints_intelligence.logging import configure_logging

app = typer.Typer(
    name="ci",
    help="Complaints intelligence: agentic weekly report generation.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def main(
    log_level: str = typer.Option("INFO", help="Logging level."),
    json_logs: bool = typer.Option(
        False, "--json-logs", help="Emit JSON log records instead of console output."
    ),
) -> None:
    """Configure logging before any subcommand runs."""
    configure_logging(level=log_level, json_output=json_logs)


@app.command()
def version() -> None:
    """Print the package version."""
    print(__version__)


@app.command("generate-data")
def generate_data(
    seed: int = typer.Option(42, help="Generation seed. Fixes the entire corpus."),
) -> None:
    """Generate the synthetic complaint corpus and resolution notes.

    Deterministic: the same seed always produces byte-identical Parquet.
    """
    from complaints_intelligence.store.persistence import (
        write_complaints,
        write_resolutions,
    )
    from complaints_intelligence.synth.generator import generate

    settings = load_settings()
    config = settings.synth.model_copy(update={"seed": seed})
    dataset = generate(config)

    write_complaints(dataset.complaints, settings.complaints_path)
    write_resolutions(dataset.resolutions, settings.resolutions_path)

    print(f"complaints:  {len(dataset.complaints):>5}  -> {settings.complaints_path}")
    print(f"resolutions: {len(dataset.resolutions):>5}  -> {settings.resolutions_path}")


@app.command("build-facts")
def build_facts(
    week: str = typer.Option(REPORTING_WEEK, help="Reporting week."),
    baseline: str = typer.Option(BASELINE_WEEK, help="Comparison week."),
) -> None:
    """Derive the fact store and the metrics brief.

    Everything below this point is deterministic. Everything above it is
    generative. This is the trust boundary.
    """
    from complaints_intelligence.metrics.brief import build_brief
    from complaints_intelligence.metrics.facts import derive_facts
    from complaints_intelligence.metrics.statistics import minimum_detectable_effect
    from complaints_intelligence.store.duckdb_store import DuckDBStore
    from complaints_intelligence.store.persistence import write_facts
    from complaints_intelligence.synth.signals import THEME_SIGNALS

    settings = load_settings()
    with DuckDBStore.open(settings, with_facts=False) as store:
        facts, tests = derive_facts(
            store,
            run_id=week,
            week=week,
            baseline_week=baseline,
            taxonomy_version=TAXONOMY_VERSION,
            thresholds=settings.brief,
        )
        write_facts(facts.as_tuple(), settings.facts_path)

        brief = build_brief(
            store,
            facts,
            tests,
            run_id=week,
            week=week,
            baseline_week=baseline,
            taxonomy_version=TAXONOMY_VERSION,
            thresholds=settings.brief,
            # Cluster-linking history, supplied upstream. Only two weeks are
            # generated here, so this stands in for the linking service.
            persistence={t.theme_id: t.persistence_weeks for t in THEME_SIGNALS},
        )
        settings.brief_path.write_text(
            brief.model_dump_json(indent=2), encoding="utf-8"
        )

    print(f"facts: {len(facts):>4}  -> {settings.facts_path}")
    print(f"brief:       -> {settings.brief_path}")
    print()
    print(f"Flagged categories ({len(brief.flagged_categories)}):")
    for flag in brief.flagged_categories:
        mark = "significant" if flag.significant else "not significant"
        channel = flag.concentrated_in_channel
        suffix = f"  [{channel}]" if channel else ""
        print(
            f"  {flag.category:<30} {flag.direction.value:<5} "
            f"q={flag.adjusted_p_value:.4f}  {mark:<15}{suffix}"
        )
    print()
    print(f"Candidate themes ({len(brief.candidate_themes)}):")
    for theme in brief.candidate_themes:
        print(
            f"  {theme.theme_id}  coherence={theme.coherence:.2f} "
            f"persistence={theme.persistence_weeks}w "
            f"concentration={theme.channel_concentration:.2f} "
            f"duplicates={theme.duplicate_ratio:.2f}"
        )
    print()
    print(f"Sentiment signals ({len(brief.sentiment_signals)}):")
    for signal in brief.sentiment_signals:
        print(f"  {signal.scope} / {signal.channel}: {signal.direction.value}")
    print()
    print("Minimum detectable effect (rise), by baseline volume:")
    for baseline_n in (20, 50, 100, 500):
        mde = minimum_detectable_effect(baseline_n, alpha=settings.brief.fdr_alpha)
        print(f"  baseline {baseline_n:>4}: {mde:+.0%}")
    if brief.skipped:
        print()
        print(f"Considered but not carried ({len(brief.skipped)}):")
        for item in brief.skipped:
            print(f"  {item.kind} {item.identifier}: {item.reason}")


@app.command()
def run(
    week: str = typer.Option(REPORTING_WEEK, help="Reporting week."),
    live: bool = typer.Option(
        False, "--live", help="Call Gemini instead of replaying cassettes."
    ),
    record: bool = typer.Option(
        False, "--record", help="Call Gemini and write cassettes back."
    ),
) -> None:
    """Run the agent and render the weekly report.

    The default replays committed cassettes: offline, deterministic, no
    credentials. ``--live`` and ``--record`` need GEMINI_API_KEY and the
    'live' extra.
    """
    from complaints_intelligence.domain.brief import MetricsBrief
    from complaints_intelligence.llm.factory import build_client
    from complaints_intelligence.runner import run_week, write_outputs
    from complaints_intelligence.store.duckdb_store import DuckDBStore

    if live and record:
        print("--live and --record are mutually exclusive; --record implies live.")
        raise typer.Exit(2)

    settings = load_settings()
    if not settings.brief_path.exists():
        print(f"No metrics brief at {settings.brief_path}. Run `ci build-facts` first.")
        raise typer.Exit(1)

    mode = "record" if record else "live" if live else "replay"
    settings = settings.model_copy(
        update={"llm": settings.llm.model_copy(update={"mode": mode})}
    )
    brief = MetricsBrief.model_validate_json(
        settings.brief_path.read_text(encoding="utf-8")
    )
    if brief.week != week:
        print(f"Brief is for {brief.week}, not {week}. Rebuild it for that week.")
        raise typer.Exit(1)

    try:
        llm = build_client(settings.llm)
    except ComplaintsIntelligenceError as exc:
        print(f"Cannot start in {mode!r} mode: {exc}")
        raise typer.Exit(1) from None

    try:
        with DuckDBStore.open(settings) as store:
            report, markdown = run_week(
                settings=settings, store=store, llm=llm, brief=brief
            )
            markdown_path, json_path = write_outputs(
                report, markdown, settings.output_dir
            )
    except CassetteMissError as exc:
        # A miss is expected and recoverable, not a crash. A stack trace here
        # would bury the one line that says what to do about it.
        print()
        print("No recording for this prompt.")
        print()
        print(str(exc))
        raise typer.Exit(1) from None

    print()
    print(f"report:  {markdown_path}")
    print(f"record:  {json_path}")
    print()
    print(f"Mode: {llm.mode} · model {llm.model}")
    print(
        f"Findings: {len(report.drivers)} driver, {len(report.emerging)} emerging, "
        f"{len(report.remediations)} remediation"
    )
    verdicts = ", ".join(
        f"{a.theme_id}={a.verdict.value}" for a in report.adjudications
    )
    print(f"Adjudications: {verdicts or 'none'}")
    print()
    print("Verification:")
    for check in report.critic.checks:
        status = "pass" if check.passed else "FAIL"
        print(f"  [{status:>4}] {check.name:<26} {check.detail}")
    if not report.critic.passed:
        print()
        print("Draft did NOT pass verification and must not be published.")
        raise typer.Exit(1)


@app.command()
def demo() -> None:
    """Generate data, derive facts, run the agent, render the report.

    The whole pipeline, offline, no credentials. This is the acceptance test
    for invariant 5.
    """
    generate_data(seed=42)
    print()
    build_facts(week=REPORTING_WEEK, baseline=BASELINE_WEEK)
    print()
    run(week=REPORTING_WEEK, live=False, record=False)


if __name__ == "__main__":
    app()
