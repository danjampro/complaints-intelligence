"""Test doubles.

``ScriptedLLM`` satisfies ``LLMClient`` without a network call. It reads the
identifiers and fact IDs out of the rendered prompt and builds valid output
from them, so citations resolve and fact references check out — which means
the tests exercise the real critic and the real renderer rather than a path
that only works because verification was skipped.

It is deliberately *not* a stand-in for the model in the demo. The demo
replays genuine recordings. This exists so the graph, the budgets, the critic
and the renderer can be tested without credentials, and so failure modes can
be provoked on demand.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import BaseModel

from complaints_intelligence.agent.schemas import (
    AdjudicateOutput,
    DraftCitation,
    DraftClaim,
    DraftPrecedent,
    InvestigateOutput,
    PlannedInvestigation,
    PlanOutput,
    RemediateOutput,
    SkippedNote,
)
from complaints_intelligence.llm.protocol import LLMResponse

_COMPLAINT_ID_RE = re.compile(r"\[complaint id=([A-Z0-9\-]+)")
_RESOLUTION_ID_RE = re.compile(r"\[resolution id=([A-Z0-9\-]+)")
_FACT_ID_RE = re.compile(r"`(f_\d{4})`")
_CATEGORY_RE = re.compile(r"^Category: (\S+)", re.MULTILINE)
_THEME_RE = re.compile(r"^Theme ID: (CT-\d{3})", re.MULTILINE)


@dataclass
class ScriptedLLM:
    """An ``LLMClient`` that produces valid, verifiable output offline.

    ``defects`` lets a test provoke a specific critic failure — used by the
    adversarial suite to prove each check actually fires rather than merely
    existing.
    """

    model: str = "scripted-test-model"
    #: Names of defects to inject: "literal_number", "bad_fact",
    #: "one_citation", "causal", "bad_offsets", "pii".
    defects: frozenset[str] = frozenset()
    #: Verdict the adjudicator returns per theme ID. Defaults to real_signal.
    verdicts: dict[str, str] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    #: Every prompt actually sent, as ``(prompt_id, rendered)``. Lets a test
    #: assert on what the model was shown rather than on what the source
    #: appears to do.
    rendered: list[tuple[str, str]] = field(default_factory=list)

    @property
    def mode(self) -> str:
        return "scripted"

    def complete[T: BaseModel](
        self,
        *,
        prompt_id: str,
        prompt_version: str,
        rendered: str,
        schema: type[T],
    ) -> LLMResponse[T]:
        self.calls.append(prompt_id)
        self.rendered.append((prompt_id, rendered))
        builder = {
            "plan": self._plan,
            "investigate": self._investigate,
            "revise": self._revise,
            "adjudicate": self._adjudicate,
            "remediate": self._remediate,
        }[prompt_id]
        parsed = builder(rendered)
        return LLMResponse(
            parsed=schema.model_validate(parsed.model_dump()),
            cassette_key=f"scripted-{prompt_id}",
            prompt_chars=len(rendered),
        )

    # -- builders ---------------------------------------------------------

    def _plan(self, rendered: str) -> PlanOutput:
        categories = re.findall(r"^- \*\*([a-z_]+)\*\* —", rendered, re.MULTILINE)
        themes = re.findall(r"^- \*\*(CT-\d{3})\*\* —", rendered, re.MULTILINE)
        return PlanOutput(
            investigations=[
                *(
                    PlannedInvestigation(
                        target=c, kind="category", reason="Movement worth review."
                    )
                    for c in categories
                ),
                *(
                    PlannedInvestigation(
                        target=t, kind="candidate_theme", reason="Needs adjudication."
                    )
                    for t in themes
                ),
            ],
            skipped=[SkippedNote(target="none", reason="nothing skipped")],
        )

    def _citations(self, rendered: str, count: int) -> list[DraftCitation]:
        ids = _COMPLAINT_ID_RE.findall(rendered)[:count]
        end = 5 if "bad_offsets" in self.defects else 20
        start = 0
        if "bad_offsets" in self.defects:
            # An offset range beyond any complaint's length.
            return [
                DraftCitation(complaint_id=i, start=99_000, end=99_100) for i in ids
            ]
        return [
            DraftCitation(complaint_id=i, start=start, end=max(end, start + 1))
            for i in ids
        ]

    def _claim_text(self, fact_ids: list[str]) -> str:
        reference = f"{{{{{fact_ids[0]}}}}}" if fact_ids else ""
        if "literal_number" in self.defects:
            return f"Complaint volume reached 142 cases {reference}."
        if "causal" in self.defects:
            return (
                f"Customers report repeated failed transfers, caused by a "
                f"gateway fault, alongside {reference}."
            )
        if "pii" in self.defects:
            return (
                f"Customers report failed transfers; contact "
                f"someone@example.com for detail, alongside {reference}."
            )
        return (
            f"Customers describe outbound transfers that do not complete and "
            f"charges they did not expect, alongside {reference}."
        )

    def _investigate(self, rendered: str) -> InvestigateOutput:
        facts = _FACT_ID_RE.findall(rendered)
        if "bad_fact" in self.defects:
            facts = ["f_9999"]
        citation_count = 1 if "one_citation" in self.defects else 2
        return InvestigateOutput(
            headline="Customers report transfers that do not complete.",
            claims=[
                DraftClaim(
                    text=self._claim_text(facts),
                    fact_refs=facts[:1],
                    citations=self._citations(rendered, citation_count),
                )
            ],
            hypotheses=[],
        )

    def _revise(self, rendered: str) -> InvestigateOutput:
        """A revision always returns a clean draft.

        The point of the revise tests is that the loop runs and the critic
        re-checks, not that a scripted model can repair arbitrary damage.
        """
        clean = ScriptedLLM(model=self.model)
        return clean._investigate(rendered)

    def _adjudicate(self, rendered: str) -> AdjudicateOutput:
        theme_match = _THEME_RE.search(rendered)
        theme_id = theme_match.group(1) if theme_match else "CT-000"
        return AdjudicateOutput(
            verdict=self.verdicts.get(theme_id, "real_signal"),
            rationale=(
                "Members describe the same problem in different words across "
                "several channels, and the cluster has persisted."
            ),
            citations=self._citations(rendered, 2),
            duplicate_of_category=None,
            headline="Customers report duplicate transfers from a savings feature.",
        )

    def _remediate(self, rendered: str) -> RemediateOutput:
        # Precedents are read from the resolution half of each pair, citations
        # from the complaint half — which is where the offsets point, and the
        # reason the complaint is in the prompt at all.
        ids = _RESOLUTION_ID_RE.findall(rendered)
        return RemediateOutput(
            recommendation=(
                "Trace and re-present affected transfers, refund charges "
                "arising from the failure, and raise the underlying timeout "
                "with the payments engineering team."
            ),
            precedents=[
                DraftPrecedent(
                    complaint_id=i,
                    transfers=True,
                    reason="Same failure mode and the action resolved it.",
                )
                for i in ids[:3]
            ],
            citations=self._citations(rendered, 2),
            fact_refs=[],
            suggested_owner="Payments engineering",
        )


@dataclass
class ExhaustedLLM:
    """A client that is never reached, for budget-exhaustion tests."""

    model: str = "never-called"

    @property
    def mode(self) -> str:
        return "scripted"

    def complete[T: BaseModel](
        self,
        *,
        prompt_id: str,
        prompt_version: str,
        rendered: str,
        schema: type[T],
    ) -> LLMResponse[T]:
        msg = "the LLM should not have been reached"
        raise AssertionError(msg)
