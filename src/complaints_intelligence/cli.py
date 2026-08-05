"""Command-line entry point.

``ci run`` executes the whole pipeline offline against the committed fixture
and model recordings: no credentials, no network (invariant 5).
"""

from __future__ import annotations

import logging

import typer

from complaints_intelligence import __version__
from complaints_intelligence.brief import build_brief
from complaints_intelligence.config import Settings
from complaints_intelligence.fixtures import load_brief_spec
from complaints_intelligence.llm.client import CassetteMissError, build_client
from complaints_intelligence.runner import run_week, write_outputs
from complaints_intelligence.store import Store

app = typer.Typer(
    name="ci",
    help="Complaints intelligence: agentic weekly report generation.",
    no_args_is_help=True,
    add_completion=False,
)


@app.command()
def version() -> None:
    """Print the package version."""
    print(__version__)


@app.command()
def run(
    live: bool = typer.Option(
        False, "--live", help="Call Gemini instead of replaying recordings."
    ),
    record: bool = typer.Option(
        False, "--record", help="Call Gemini and write the recordings back."
    ),
    log_level: str = typer.Option("WARNING", help="Logging level."),
) -> None:
    """Run the agent for the reporting week and render the report."""
    logging.basicConfig(level=log_level.upper(), format="%(levelname)s %(message)s")

    settings = Settings()
    mode = "record" if record else "live" if live else "replay"
    settings = settings.model_copy(
        update={"llm": settings.llm.model_copy(update={"mode": mode})}
    )

    store = Store.open()
    brief = build_brief(store, load_brief_spec())

    try:
        llm = build_client(settings.llm)
        report, markdown = run_week(
            settings=settings, store=store, llm=llm, brief=brief
        )
    except CassetteMissError as exc:
        # A miss is expected and recoverable, not a crash. A stack trace here
        # would bury the one line that says what to do about it.
        print(f"\nNo recording for this prompt.\n\n{exc}")
        raise typer.Exit(1) from None
    except RuntimeError as exc:
        print(f"Cannot start in {mode!r} mode: {exc}")
        raise typer.Exit(1) from None

    markdown_path, json_path = write_outputs(report, markdown, settings.output_dir)

    print(f"\nreport:  {markdown_path}")
    print(f"record:  {json_path}")
    print(f"\nMode: {llm.mode} · model {llm.model}")
    print(
        f"Findings: {len(report.drivers)} driver, {len(report.emerging)} emerging, "
        f"{len(report.remediations)} remediation"
    )
    verdicts = ", ".join(
        f"{a.theme_id}={a.verdict.value}" for a in report.adjudications
    )
    print(f"Adjudications: {verdicts or 'none'}")
    print("\nVerification:")
    for check in report.critic.checks:
        status = "pass" if check.passed else "FAIL"
        print(f"  [{status:>4}] {check.name:<20} {check.detail}")

    if not report.critic.passed:
        print("\nDraft did NOT pass verification and must not be published.")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
