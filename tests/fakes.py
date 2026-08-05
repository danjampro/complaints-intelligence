"""Test doubles.

``ScriptedLLM`` satisfies ``LLMClient`` without a network call. It reads the
identifiers and fact IDs out of the rendered prompt and builds valid output
from them, so the tests exercise the real critic and the real renderer rather
than a path that only works because verification was skipped.
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
    RemediateOutput,
)
from complaints_intelligence.llm.client import LLMResponse

_COMPLAINT_ID_RE = re.compile(r"\[complaint id=([A-Z0-9\-]+)")
_RESOLUTION_ID_RE = re.compile(r"\[resolution id=([A-Z0-9\-]+)")
_FACT_ID_RE = re.compile(r"`(f_\d{4})`")
_THEME_RE = re.compile(r"^Theme ID: (CT-\d{3})", re.MULTILINE)


@dataclass
class ScriptedLLM:
    """An ``LLMClient`` producing valid, verifiable output offline.

    ``defects`` lets a test provoke a specific critic failure, which is how the
    adversarial suite proves each check fires rather than merely existing.
    """

    model: str = "scripted-test-model"
    #: One of: literal_number, bad_fact, one_citation, bad_offsets, pii.
    defects: frozenset[str] = frozenset()
    #: Verdict the adjudicator returns per theme ID. Defaults to real_signal.
    verdicts: dict[str, str] = field(default_factory=dict)
    #: Every prompt actually sent, as ``(prompt_id, rendered)``. Lets a test
    #: assert on what the model was shown rather than on what the source does.
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
        self.rendered.append((prompt_id, rendered))
        builder = {
            "investigate": self._investigate,
            "revise": self._revise,
            "adjudicate": self._adjudicate,
            "remediate": self._remediate,
        }[prompt_id]
        return LLMResponse(
            parsed=schema.model_validate(builder(rendered).model_dump()),
            cassette_key=f"scripted-{prompt_id}",
            prompt_chars=len(rendered),
        )

    # -- builders ---------------------------------------------------------

    def _citations(self, rendered: str, count: int) -> list[DraftCitation]:
        ids = _COMPLAINT_ID_RE.findall(rendered)[:count]
        if "bad_offsets" in self.defects:
            # A range beyond any complaint's length.
            return [
                DraftCitation(complaint_id=i, start=99_000, end=99_100) for i in ids
            ]
        return [DraftCitation(complaint_id=i, start=0, end=20) for i in ids]

    def _claim_text(self, fact_ids: list[str]) -> str:
        reference = f"across {{{{{fact_ids[0]}}}}} complaints" if fact_ids else ""
        if "literal_number" in self.defects:
            return f"Complaint volume reached 142 cases {reference}."
        if "pii" in self.defects:
            return (
                f"Customers report failed transfers; contact someone@example.com "
                f"for detail, alongside {reference}."
            )
        return (
            f"Customers describe outbound transfers that do not complete and "
            f"charges they did not expect, alongside {reference}."
        )

    def _investigate(self, rendered: str) -> InvestigateOutput:
        facts = (
            ["f_9999"] if "bad_fact" in self.defects else _FACT_ID_RE.findall(rendered)
        )
        return InvestigateOutput(
            headline="Customers report transfers that do not complete.",
            claims=[
                DraftClaim(
                    text=self._claim_text(facts),
                    fact_refs=facts[:1],
                    citations=self._citations(
                        rendered, 1 if "one_citation" in self.defects else 2
                    ),
                )
            ],
            hypotheses=[],
        )

    def _revise(self, rendered: str) -> InvestigateOutput:
        """A revision always returns a clean draft. The point of the revise
        tests is that the loop runs and the critic re-checks, not that a
        scripted model can repair arbitrary damage."""
        return ScriptedLLM(model=self.model)._investigate(rendered)

    def _adjudicate(self, rendered: str) -> AdjudicateOutput:
        match = _THEME_RE.search(rendered)
        theme_id = match.group(1) if match else "CT-000"
        return AdjudicateOutput(
            verdict=self.verdicts.get(theme_id, "real_signal"),
            rationale=(
                "Members describe the same problem in different words across "
                "several channels, and the cluster has persisted."
            ),
            citations=self._citations(rendered, 2),
            headline="Customers report duplicate transfers from a savings feature.",
        )

    def _remediate(self, rendered: str) -> RemediateOutput:
        # Precedents come from the resolution half of each pair; citations from
        # the complaint half, which is where the offsets point.
        return RemediateOutput(
            recommendation=(
                "Trace and re-present affected transfers, refund charges arising "
                "from the failure, and raise the underlying timeout with the "
                "payments engineering team."
            ),
            precedents=[
                DraftPrecedent(
                    complaint_id=i,
                    transfers=True,
                    reason="Same failure mode and the action resolved it.",
                )
                for i in _RESOLUTION_ID_RE.findall(rendered)[:3]
            ],
            citations=self._citations(rendered, 2),
            fact_refs=[],
            suggested_owner="Payments engineering",
        )


@dataclass
class StubbornLLM(ScriptedLLM):
    """A model whose revisions never repair the defect, so the revise loop runs
    to its budget and stops rather than looping forever."""

    def _revise(self, rendered: str) -> InvestigateOutput:
        return self._investigate(rendered)
