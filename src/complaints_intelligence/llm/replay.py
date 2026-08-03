"""Replay client: the default, and what makes the demo run offline.

Cassettes are genuine recordings of exchanges with Gemini, committed as
readable JSON. A reviewer with no credentials sees the real model's reasoning;
a reviewer with a key can re-record and compare.

A miss is a hard error. The two tempting fallbacks are both worse than
failing:

- Falling back to a live call breaks the offline guarantee silently, and the
  demo would work on the author's machine and nowhere else.
- Falling back to a canned stub would make the output a fiction while still
  looking like a model ran. The cassettes' whole value is that they are
  recordings, and a stub that pretends to be one destroys that.

So a miss says exactly which prompt is missing and how to record it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from complaints_intelligence.errors import CassetteMissError
from complaints_intelligence.llm.protocol import LLMResponse, cassette_key
from complaints_intelligence.logging import get_logger

log = get_logger(__name__)

CASSETTE_DIR = Path(__file__).parent / "cassettes"


def cassette_path(directory: Path, key: str) -> Path:
    """Path for a cassette. One file per exchange, so diffs are readable."""
    return directory / f"{key}.json"


class ReplayClient:
    """Serves recorded completions from disk."""

    def __init__(
        self,
        *,
        model: str,
        directory: Path | None = None,
    ) -> None:
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
        if not path.exists():
            msg = (
                f"no cassette for prompt {prompt_id!r} (key {key}).\n"
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
            # A cassette that no longer satisfies its schema means the schema
            # moved under the recording. Failing loudly beats silently
            # dropping fields the report may depend on.
            msg = (
                f"cassette {path.name} does not satisfy {schema.__name__}; "
                f"the schema has changed since recording. Re-record with "
                f"`ci run --record`."
            )
            raise CassetteMissError(msg) from exc

        log.debug("cassette_replayed", prompt_id=prompt_id, key=key)
        return LLMResponse(parsed=parsed, cassette_key=key, prompt_chars=len(rendered))
