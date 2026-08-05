"""Deterministic rendering. No model involvement.

This is where figures and quotations enter the report, and the reason numeric
hallucination and misquotation are structurally impossible rather than detected
afterwards: a claim's text contains ``{{f_0142}}`` and the value is looked up
here, and a citation is a complaint ID and a character range whose quote is
sliced out of the stored text here.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from complaints_intelligence.config import PACKAGE_ROOT
from complaints_intelligence.fixtures.taxonomy import display_name
from complaints_intelligence.outputs import (
    FACT_PLACEHOLDER_RE,
    Citation,
    Finding,
    Report,
)
from complaints_intelligence.store import Store

log = logging.getLogger(__name__)

_TEMPLATE_DIR = PACKAGE_ROOT / "templates"

#: Quotations longer than this are truncated in the rendered report. The full
#: span remains on the report object, so the drill-down is unaffected.
_MAX_QUOTE_CHARS = 220


def resolve_text(text: str, store: Store, *, strict: bool = True) -> str:
    """Substitute fact placeholders with their stored values.

    ``strict`` follows the critic's verdict. On a verified report every
    reference was checked moments earlier, so one that fails here means the
    fact store changed under the run and must stop the report. On a report that
    already failed, the unresolved placeholder is the *evidence* of what went
    wrong — and because it is left visible rather than substituted, no reader
    can mistake it for a figure.
    """

    def substitute(match: re.Match[str]) -> str:
        try:
            return store.get_fact(match.group(1)).render()
        except KeyError:
            if strict:
                raise
            return match.group(0)

    return FACT_PLACEHOLDER_RE.sub(substitute, text)


def snap_span(text: str, start: int, end: int) -> tuple[int, int]:
    """Widen a span to whole words, clamped to the text.

    Offsets are chosen by the model and land mid-word often enough to make the
    report read as broken. Widening only ever *adds* neighbouring characters, so
    the quote remains a slice of stored text and the misquotation guarantee is
    untouched. The critic snaps identically, so no character reaches the reader
    unscanned.
    """
    start = max(0, min(start, len(text)))
    end = max(start, min(end, len(text)))
    while start > 0 and (text[start - 1].isalnum() or text[start - 1] == "'"):
        start -= 1
    while end < len(text) and (text[end].isalnum() or text[end] == "'"):
        end += 1
    return start, end


def resolve_quote(citation: Citation, store: Store) -> dict[str, Any]:
    """Pull the quoted span out of the stored complaint text.

    The model never handles the words it quotes, so it cannot alter them.
    """
    complaint = store.get_complaint(citation.complaint_id)
    start, end = snap_span(complaint.text, citation.start, citation.end)
    quote = complaint.text[start:end].strip()
    if len(quote) > _MAX_QUOTE_CHARS:
        quote = quote[: _MAX_QUOTE_CHARS - 1].rstrip() + "…"
    return {
        "complaint_id": citation.complaint_id,
        "start": start,
        "end": end,
        "quote": quote,
        "channel": complaint.channel.value.replace("_", " "),
    }


def _render_finding(finding: Finding, store: Store, *, strict: bool) -> dict[str, Any]:
    claims = [
        {
            "text": resolve_text(claim.text, store, strict=strict),
            "requires_confirmation": claim.requires_confirmation,
            "citations": [resolve_quote(c, store) for c in claim.citations],
        }
        for claim in finding.claims
    ]
    return {
        "finding_id": finding.finding_id,
        "headline": resolve_text(finding.headline, store, strict=strict),
        "category_display": display_name(finding.category)
        if finding.category
        else None,
        "theme_id": finding.theme_id,
        "evidenced": [c for c in claims if not c["requires_confirmation"]],
        "hypotheses": [c for c in claims if c["requires_confirmation"]],
    }


def render_markdown(report: Report, store: Store) -> str:
    """Render the report object to Markdown."""
    environment = Environment(
        loader=FileSystemLoader(_TEMPLATE_DIR),
        undefined=StrictUndefined,
        autoescape=False,  # noqa: S701 - Markdown output, not HTML
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    # A verified report must resolve completely or stop. An unverified one is
    # already marked unpublishable, and rendering it — placeholders and all —
    # is what lets a reviewer see why it failed.
    strict = report.critic.passed

    output: str = environment.get_template("report.md.j2").render(
        report=report,
        generated_at=report.generated_at.strftime("%Y-%m-%d %H:%M UTC"),
        drivers=[_render_finding(f, store, strict=strict) for f in report.drivers],
        emerging=[_render_finding(f, store, strict=strict) for f in report.emerging],
        sentiment=[
            {
                "scope_display": display_name(signal.scope),
                "channel_display": signal.channel.replace("_", " "),
                "direction": signal.direction.value,
                "baseline": store.get_fact(signal.baseline_fact_id).render(),
                "current": store.get_fact(signal.current_fact_id).render(),
                "shift": store.get_fact(signal.shift_fact_id).render(),
            }
            for signal in report.sentiment
        ],
        adjudications=[
            {
                "theme_id": a.theme_id,
                "verdict": a.verdict.value.replace("_", " "),
                "rationale": resolve_text(a.rationale, store, strict=strict),
            }
            for a in report.adjudications
        ],
        remediations=[
            {
                "finding_id": r.finding_id,
                "recommendation": resolve_text(r.recommendation, store, strict=strict),
                "suggested_owner": r.suggested_owner,
                "citations": [resolve_quote(c, store) for c in r.citations],
                # Precedents that did not transfer are kept and shown: a report
                # that says what it ruled out is auditable, one that shows only
                # supporting evidence is advocacy.
                "transferring": [p for p in r.precedents if p.transfers],
                "rejected": [p for p in r.precedents if not p.transfers],
            }
            for r in report.remediations
        ],
    )
    log.info("report rendered: %d characters", len(output))
    return output


def utc_now() -> datetime:
    """Current UTC time. One place, so tests can patch it."""
    return datetime.now(UTC)
