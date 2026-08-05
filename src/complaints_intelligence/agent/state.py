"""State carried through the agent graph, and the bounds on a run.

``RunState`` is data the graph merges between nodes; ``RunContext`` holds the
injected collaborators, which are kept off the state because they are
dependencies rather than data and do not serialise.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from complaints_intelligence.config import BudgetConfig, Settings
from complaints_intelligence.inputs import ComplaintEnvelope, MetricsBrief
from complaints_intelligence.llm.client import LLMClient
from complaints_intelligence.outputs import (
    Adjudication,
    CriticReport,
    Finding,
    Remediation,
)
from complaints_intelligence.store import Store

if TYPE_CHECKING:  # imported lazily: ToolBelt depends on BudgetLedger below
    from complaints_intelligence.agent.tools import ToolBelt

log = logging.getLogger(__name__)


class BudgetExceededError(RuntimeError):
    """A run hit one of its hard bounds. Caught by the graph, not the caller."""


@dataclass
class BudgetLedger:
    """Spend against a run's budget (invariant 4).

    A bound that crashes the run is not a usable bound, so exhaustion is a
    condition the graph handles: the run finishes with what it has and records
    why it stopped.
    """

    config: BudgetConfig
    llm_calls: int = 0
    tool_calls: int = 0
    revisions: int = 0
    notes: list[str] = field(default_factory=list)

    def spend_llm(self, node: str) -> None:
        if self.llm_calls >= self.config.max_llm_calls:
            msg = f"model call budget exhausted at {self.config.max_llm_calls} ({node})"
            raise BudgetExceededError(msg)
        self.llm_calls += 1

    def spend_tool(self, node: str, tool: str) -> None:
        if self.tool_calls >= self.config.max_tool_calls:
            msg = (
                f"tool call budget exhausted at {self.config.max_tool_calls} "
                f"({node}/{tool})"
            )
            raise BudgetExceededError(msg)
        self.tool_calls += 1

    def may_revise(self) -> bool:
        return self.revisions < self.config.max_revisions

    def spend_revision(self) -> None:
        self.revisions += 1

    def note(self, message: str) -> None:
        """Record a degradation, surfaced in the trace and the report."""
        log.warning("run degraded: %s", message)
        self.notes.append(message)


@dataclass
class RunContext:
    """Injected collaborators for one run.

    Every node takes the context rather than importing a store or a client,
    which is what makes the graph testable with a fake client.
    """

    settings: Settings
    store: Store
    llm: LLMClient
    ledger: BudgetLedger
    tools: ToolBelt
    node_sequence: list[str] = field(default_factory=list)
    #: Evidence retrieved per finding, kept so a revision re-prompts with the
    #: same complaints rather than quietly changing what the finding is about.
    evidence: dict[str, tuple[ComplaintEnvelope, ...]] = field(default_factory=dict)


class RunState(BaseModel):
    """The graph's data state; the fields a node writes are the fields it
    returns."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    brief: MetricsBrief
    findings: list[Finding] = Field(default_factory=list)
    adjudications: list[Adjudication] = Field(default_factory=list)
    remediations: list[Remediation] = Field(default_factory=list)
    critic: CriticReport | None = None
    revision: int = 0
