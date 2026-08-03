"""Run trace: what makes a report defensible eighteen months later.

Every tool call, its arguments, the facts retrieved, and the prompt and model
versions in force are recorded. In a deployed system this is written to a
BigQuery trace table (architecture section 10); here it is serialised
alongside the report.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class PinnedVersions(BaseModel):
    """Everything that must be identical to reconstruct a historical report.

    Prompt files are hashed rather than merely numbered: a version string can
    be forgotten on edit, a content hash cannot. A prompt change is a code
    change, and this is what makes that detectable in a published artefact.
    """

    model_config = ConfigDict(frozen=True)

    taxonomy_version: str
    prompt_version: str
    #: Prompt id -> SHA-256 of the prompt file contents.
    prompt_hashes: dict[str, str]
    model: str
    llm_mode: str
    package_version: str
    synth_seed: int


class ToolCall(BaseModel):
    """One invocation of a read-only agent tool."""

    model_config = ConfigDict(frozen=True)

    sequence: Annotated[int, Field(ge=0)]
    node: str
    tool: str
    arguments: dict[str, str | int | float | None]
    #: Number of records returned. The records themselves are not duplicated
    #: into the trace; they are re-derivable from the arguments.
    result_count: int
    fact_ids_returned: tuple[str, ...] = ()


class LLMCall(BaseModel):
    """One model invocation.

    ``cassette_key`` is present in replay and record modes and is what lets a
    reviewer find the exact recorded exchange behind any drafted sentence.
    """

    model_config = ConfigDict(frozen=True)

    sequence: Annotated[int, Field(ge=0)]
    node: str
    prompt_id: str
    prompt_version: str
    schema_name: str
    cassette_key: str | None = None
    prompt_chars: int = 0


class RunTrace(BaseModel):
    """The full record of one agent run."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    started_at: datetime
    versions: PinnedVersions

    tool_calls: tuple[ToolCall, ...] = ()
    llm_calls: tuple[LLMCall, ...] = ()
    #: Nodes entered, in order. Reveals which revise loops fired.
    node_sequence: tuple[str, ...] = ()
    #: Non-fatal degradations: budget exhaustion, retrieval that found
    #: nothing, an adjudication the agent declined to make.
    notes: tuple[str, ...] = ()
