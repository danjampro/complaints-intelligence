"""State carried through the agent graph.

One mutable object threaded through the nodes. LangGraph merges partial
updates into it; the fields a node writes are the fields it returns.

``RunContext`` holds the things every node needs but none of them owns — the
store, the tools, the client. Kept off the graph state because they are not
data, do not serialise, and putting them there would make a checkpoint of the
state impossible.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

from complaints_intelligence.agent.budgets import BudgetLedger
from complaints_intelligence.agent.schemas import PlannedInvestigation
from complaints_intelligence.agent.tools import ToolBelt
from complaints_intelligence.config import Settings
from complaints_intelligence.domain.brief import MetricsBrief
from complaints_intelligence.domain.complaint import ComplaintEnvelope
from complaints_intelligence.domain.finding import Adjudication, Finding, Remediation
from complaints_intelligence.domain.report import CriticReport
from complaints_intelligence.domain.trace import LLMCall
from complaints_intelligence.llm.protocol import LLMClient
from complaints_intelligence.store.duckdb_store import DuckDBStore


@dataclass
class RunContext:
    """Injected collaborators for one run.

    Not part of the graph state: these are dependencies, not data. Every node
    takes the context rather than importing a store or a client, which is what
    makes the graph testable with a fake client and an in-memory store.
    """

    settings: Settings
    store: DuckDBStore
    tools: ToolBelt
    llm: LLMClient
    ledger: BudgetLedger
    #: Model calls made, in order. Appended by the node helper, not by nodes.
    llm_calls: list[LLMCall] = field(default_factory=list)
    #: Nodes entered, in order. Reveals which revise loops fired.
    node_sequence: list[str] = field(default_factory=list)
    #: Evidence retrieved per finding, kept so the revise loop can re-prompt
    #: with the same complaints rather than retrieving different ones and
    #: quietly changing what the finding is about.
    evidence: dict[str, tuple[ComplaintEnvelope, ...]] = field(default_factory=dict)


class RunState(BaseModel):
    """The graph's data state."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    brief: MetricsBrief

    plan: list[PlannedInvestigation] = Field(default_factory=list)
    plan_skipped: list[tuple[str, str]] = Field(default_factory=list)

    findings: list[Finding] = Field(default_factory=list)
    adjudications: list[Adjudication] = Field(default_factory=list)
    remediations: list[Remediation] = Field(default_factory=list)

    critic: CriticReport | None = None
    revision: int = 0

    #: Set when a node degraded rather than failed — budget exhaustion,
    #: retrieval that found nothing, an adjudication declined.
    notes: list[str] = Field(default_factory=list)
