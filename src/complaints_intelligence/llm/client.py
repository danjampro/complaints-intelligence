"""The LLM seam, and the offline replay client behind it.

Every node depends on the ``LLMClient`` protocol; the only module that imports
a vendor SDK is ``llm.gemini``, behind an optional extra.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ValidationError

from complaints_intelligence.config import LLMConfig

CASSETTE_DIR = Path(__file__).parent / "cassettes"


class CassetteMissError(RuntimeError):
    """No recording exists for a prompt that replay mode was asked to serve."""


class LLMResponse[T: BaseModel](BaseModel):
    """A parsed model response plus what is needed to trace it."""

    model_config = {"frozen": True}

    parsed: T
    cassette_key: str | None = None
    prompt_chars: int = 0


@runtime_checkable
class LLMClient(Protocol):
    """Produces structured output from a rendered prompt.

    The caller supplies a Pydantic ``schema`` and receives an instance of it,
    so model output is parsed at the boundary and never scraped from text.
    """

    @property
    def mode(self) -> str: ...

    @property
    def model(self) -> str: ...

    def complete[T: BaseModel](
        self,
        *,
        prompt_id: str,
        prompt_version: str,
        rendered: str,
        schema: type[T],
    ) -> LLMResponse[T]: ...


def cassette_key(
    *, prompt_id: str, prompt_version: str, rendered: str, schema_name: str, model: str
) -> str:
    """Stable key identifying one prompt/schema/model exchange.

    The *rendered* prompt is hashed, so any change to the template, the
    retrieved evidence or the brief produces a miss — which is intended. A
    recording that kept being replayed after its inputs changed would be a
    fiction, and the demo rests on the recordings being genuine.
    """
    payload = json.dumps(
        {
            "prompt_id": prompt_id,
            "prompt_version": prompt_version,
            "schema": schema_name,
            "model": model,
            "rendered": rendered,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{prompt_id}-{digest[:16]}"


def cassette_path(directory: Path, key: str) -> Path:
    """One file per exchange, so diffs stay readable."""
    return directory / f"{key}.json"


class ReplayClient:
    """Serves recorded completions from disk. The default, and what makes the
    demo run offline with no credentials."""

    def __init__(self, *, model: str, directory: Path | None = None) -> None:
        self._model = model
        self._directory = directory or CASSETTE_DIR

    @property
    def mode(self) -> str:
        return "replay"

    @property
    def model(self) -> str:
        return self._model

    def complete[T: BaseModel](
        self,
        *,
        prompt_id: str,
        prompt_version: str,
        rendered: str,
        schema: type[T],
    ) -> LLMResponse[T]:
        key = cassette_key(
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            rendered=rendered,
            schema_name=schema.__name__,
            model=self._model,
        )
        path = cassette_path(self._directory, key)
        # A miss is a hard error. Falling back to a live call would break the
        # offline guarantee silently; falling back to a canned stub would make
        # the output a fiction while still looking like a model ran.
        if not path.exists():
            msg = (
                f"no recording for prompt {prompt_id!r} (key {key}).\n"
                f"Expected: {path}\n"
                f"The prompt, the retrieved evidence or the brief has changed "
                f"since the recordings were made.\n"
                f"Re-record with:  ci run --record   "
                f"(needs GEMINI_API_KEY and the 'live' extra)"
            )
            raise CassetteMissError(msg)

        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        try:
            parsed = schema.model_validate(payload["response"])
        except ValidationError as exc:
            msg = (
                f"recording {path.name} does not satisfy {schema.__name__}; the "
                f"schema has changed since it was made. Re-record with "
                f"`ci run --record`."
            )
            raise CassetteMissError(msg) from exc

        return LLMResponse(parsed=parsed, cassette_key=key, prompt_chars=len(rendered))


def build_client(config: LLMConfig) -> LLMClient:
    """Construct the client for a run's configured mode."""
    if config.mode == "replay":
        return ReplayClient(model=config.model)

    # Imported here so the offline path never needs google-genai installed.
    from complaints_intelligence.llm.gemini import GeminiClient, RecordingClient

    live = GeminiClient(
        model=config.model,
        temperature=config.temperature,
        max_output_tokens=config.max_output_tokens,
        thinking_level=config.thinking_level,
    )
    return RecordingClient(live) if config.mode == "record" else live
