"""Typed configuration.

Everything tunable lives here rather than as literals at call sites, so a run
can be described by its settings and reproduced from them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

PACKAGE_ROOT: Final[Path] = Path(__file__).resolve().parent
REPO_ROOT: Final[Path] = PACKAGE_ROOT.parent.parent

#: Structural taxonomy changes mint a new version plus an old->new mapping;
#: the taxonomy is never mutated in place.
TAXONOMY_VERSION: Final[str] = "v4.2"

REPORTING_WEEK: Final[str] = "2026-W31"
BASELINE_WEEK: Final[str] = "2026-W30"


class BudgetConfig(BaseModel):
    """Hard bounds on a single agent run (invariant 4)."""

    max_llm_calls: int = 40
    max_tool_calls: int = 60
    max_revisions: int = 2
    #: Categories and themes are budgeted separately, so the more numerous
    #: categories cannot crowd out emerging-theme adjudication entirely.
    max_investigations: int = 5
    max_adjudications: int = 3
    max_exemplars_per_finding: int = 6
    max_precedents_per_finding: int = 6


class CriticThresholds(BaseModel):
    """What the critic enforces before a draft may be rendered."""

    #: Two rather than one, because a single complaint is an anecdote.
    min_citations_per_claim: int = 2


class LLMConfig(BaseModel):
    """LLM client selection and generation parameters.

    ``mode`` chooses the implementation behind the ``LLMClient`` protocol:
    ``replay`` reads committed recordings offline, ``live`` calls Gemini,
    ``record`` calls Gemini and writes the recordings back.
    """

    mode: Literal["replay", "live", "record"] = "replay"
    #: Pinned by name, not a moving alias: the model identifier is part of what
    #: makes a published report reconstructable.
    model: str = "gemini-3.5-flash-lite"
    temperature: float = 0.0
    #: Generous, because a truncated response is not a partial finding — it is
    #: invalid JSON, and the whole call is wasted.
    max_output_tokens: int = 16384
    #: Low on purpose: the graph has already decomposed the problem, so each
    #: call is constrained extraction rather than open-ended reasoning.
    thinking_level: Literal["low", "medium", "high"] = "low"
    prompt_version: str = "v1"


class Settings(BaseSettings):
    """Top-level settings, overridable by environment or ``.env``."""

    model_config = SettingsConfigDict(
        env_prefix="CI_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
    )

    output_dir: Path = REPO_ROOT / "out"

    budget: BudgetConfig = BudgetConfig()
    critic: CriticThresholds = CriticThresholds()
    llm: LLMConfig = LLMConfig()
