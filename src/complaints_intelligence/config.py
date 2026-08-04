"""Typed configuration.

Everything tunable lives here rather than as literals at call sites, so a run
can be described by its settings and reproduced from them. Thresholds that
shape the metrics brief are configuration, not model choices — anything the
thresholds miss cannot appear in the report, so they are stated explicitly and
recorded in the run trace.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PACKAGE_ROOT: Final[Path] = Path(__file__).resolve().parent
REPO_ROOT: Final[Path] = PACKAGE_ROOT.parent.parent

#: The taxonomy version every synthetic record is stamped with. Structural
#: changes mint a new version plus an old->new mapping; never mutated in place.
TAXONOMY_VERSION: Final[str] = "v4.2"

#: The reporting week and its comparison baseline.
REPORTING_WEEK: Final[str] = "2026-W31"
BASELINE_WEEK: Final[str] = "2026-W30"


class SynthConfig(BaseModel):
    """Controls synthetic data generation.

    Volumes are deliberately far below the ~5,000/week of the real problem.
    The fixtures must be small enough for a human to read and follow what the
    pipeline is doing.
    """

    seed: int = 42
    baseline_week: str = BASELINE_WEEK
    reporting_week: str = REPORTING_WEEK
    complaints_per_week: int = 600
    closed_fraction: float = Field(default=0.6, ge=0.0, le=1.0)


class EmbeddingConfig(BaseModel):
    """TF-IDF + truncated SVD, standing in for a hosted embedding model.

    Local, deterministic and dependency-light, which is what invariant 5
    requires. ``retrieval.embedder`` records what is lost against a real
    embedding model, which is the production choice.
    """

    n_components: int = 128
    min_df: int = 2
    max_df: float = 0.6
    ngram_range: tuple[int, int] = (1, 2)
    seed: int = 42


class BriefThresholds(BaseModel):
    """Fixed thresholds that build the metrics brief from the run's facts.

    The brief is the agent's entire view of the week. Truncation is what makes
    runs bounded and weeks comparable; it is also why these numbers are
    configuration with a stated minimum detectable effect rather than a
    heuristic buried in code.
    """

    #: Proportional week-on-week change at which a category is flagged.
    volume_change_flag: float = 0.20
    #: Minimum baseline count before a proportional change is trusted at all.
    min_baseline_count: int = 15
    #: Shift in mean sentiment (on a -1..1 scale) worth reporting.
    #:
    #: Applied *in addition to* a Welch test with the same FDR control as the
    #: volume tests. Significance alone would surface trivially small moves in
    #: large cells; a threshold alone would surface sampling noise in small
    #: ones. Both gates are needed, for different reasons.
    sentiment_shift_flag: float = 0.15
    #: Benjamini-Hochberg false discovery rate for the velocity tests.
    fdr_alpha: float = 0.10
    #: Brief truncation. Anything past these ranks is recorded as considered
    #: but not carried, never silently dropped.
    max_flagged_categories: int = 8
    max_candidate_themes: int = 3


class BudgetConfig(BaseModel):
    """Hard bounds on a single agent run (invariant 4)."""

    max_llm_calls: int = 40
    max_tool_calls: int = 60
    max_revisions: int = 2
    #: Category investigations and theme adjudications are budgeted
    #: separately. A single combined cap lets categories — of which there are
    #: always more — crowd out theme adjudication entirely, and emerging-risk
    #: detection is the part of the report with the least redundancy: a driver
    #: missed this week shows up next week, an emerging theme missed compounds.
    max_investigations: int = 5
    max_adjudications: int = 3
    max_exemplars_per_finding: int = 6
    max_precedents_per_finding: int = 6


class CriticThresholds(BaseModel):
    """What the critic enforces before a draft may be rendered."""

    #: Every qualitative claim needs at least this many complaint citations.
    min_citations_per_claim: int = 2


class LLMConfig(BaseModel):
    """LLM client selection and generation parameters.

    ``mode`` chooses the implementation behind the ``LLMClient`` protocol:

    - ``replay``  reads committed cassettes; offline, deterministic, default.
    - ``live``    calls Gemini; requires the ``live`` extra and an API key.
    - ``record``  calls Gemini and writes cassettes back.
    """

    mode: Literal["replay", "live", "record"] = "replay"
    #: Pinned by name, deliberately not a moving alias such as
    #: ``gemini-flash-latest``. The model identifier is part of what makes a
    #: published report reconstructable, and an alias that silently points
    #: somewhere new eighteen months later defeats that.
    #:
    #: A lite model is sufficient here and is a deliberate choice rather than
    #: a cost compromise. The graph has already done the decomposition — the
    #: evidence is retrieved, the candidate fact IDs are chosen, the schema is
    #: fixed — so each call is constrained extraction against explicit rules
    #: rather than open-ended reasoning. Correctness is enforced by the critic
    #: and by the fact store, not by model capability, which is what makes the
    #: smaller model safe to use.
    model: str = "gemini-3.5-flash-lite"
    temperature: float = 0.0
    #: Generous, because a truncated response is not a partial finding — it is
    #: invalid JSON, and the whole call is wasted.
    max_output_tokens: int = 16384
    #: Reasoning effort. Deliberately low: these prompts are structured
    #: extraction against explicit rules, with the evidence already retrieved
    #: and the fact IDs already chosen. At the default level the model spent
    #: ~15k tokens thinking and then truncated its own JSON, which is cost and
    #: latency spent on a problem the graph has already decomposed.
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

    data_dir: Path = REPO_ROOT / "data"
    output_dir: Path = REPO_ROOT / "out"

    synth: SynthConfig = SynthConfig()
    embedding: EmbeddingConfig = EmbeddingConfig()
    brief: BriefThresholds = BriefThresholds()
    budget: BudgetConfig = BudgetConfig()
    critic: CriticThresholds = CriticThresholds()
    llm: LLMConfig = LLMConfig()

    @property
    def complaints_path(self) -> Path:
        return self.data_dir / "complaints.parquet"

    @property
    def resolutions_path(self) -> Path:
        return self.data_dir / "resolutions.parquet"

    @property
    def facts_path(self) -> Path:
        return self.data_dir / "facts.parquet"

    @property
    def brief_path(self) -> Path:
        return self.data_dir / "brief.json"


def load_settings() -> Settings:
    """Build settings from the environment.

    A function rather than a module-level singleton: tests need to construct
    settings with temporary paths without mutating global state.
    """
    return Settings()
