"""Recording client: wraps a live client and writes cassettes.

Used once during development to capture the exchanges the offline demo then
replays. Cassettes are committed.

The recorded file carries the rendered prompt alongside the response. That
costs repository size and buys something important: a reviewer can read
exactly what the model was asked, including the fenced untrusted block, and
check for themselves that the injection payloads were present and were treated
as data. A cassette holding only the response would require taking that on
trust.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from complaints_intelligence.llm.protocol import (
    LLMClient,
    LLMResponse,
    cassette_key,
)
from complaints_intelligence.llm.replay import CASSETTE_DIR, cassette_path
from complaints_intelligence.logging import get_logger

log = get_logger(__name__)


class RecordingClient:
    """Delegates to an inner client and persists every exchange."""

    def __init__(
        self,
        inner: LLMClient,
        *,
        directory: Path | None = None,
        resume: bool = True,
    ) -> None:
        self._inner = inner
        self._directory = directory or CASSETTE_DIR
        self._directory.mkdir(parents=True, exist_ok=True)
        self._resume = resume

    @property
    def mode(self) -> str:
        return "record"

    @property
    def model(self) -> str:
        return self._inner.model

    def complete[T: BaseModel](
        self,
        *,
        prompt_id: str,
        prompt_version: str,
        rendered: str,
        schema: type[T],
    ) -> LLMResponse[T]:
        # Resume rather than re-record. A full run is a dozen or so calls
        # against a rate-limited API; without this, one failure two thirds of
        # the way through means paying for the whole run again — and on a
        # quota-limited key, often means not being able to finish at all.
        if self._resume:
            key = cassette_key(
                prompt_id=prompt_id,
                prompt_version=prompt_version,
                rendered=rendered,
                schema_name=schema.__name__,
                model=self._inner.model,
            )
            existing = cassette_path(self._directory, key)
            if existing.exists():
                payload = json.loads(existing.read_text(encoding="utf-8"))
                log.info("cassette_reused", prompt_id=prompt_id, key=key)
                return LLMResponse(
                    parsed=schema.model_validate(payload["response"]),
                    cassette_key=key,
                    prompt_chars=len(rendered),
                )

        response = self._inner.complete(
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            rendered=rendered,
            schema=schema,
        )
        if response.cassette_key is None:  # pragma: no cover - defensive
            msg = "inner client returned no cassette key; cannot record"
            raise ValueError(msg)

        path = cassette_path(self._directory, response.cassette_key)
        payload = {
            "prompt_id": prompt_id,
            "prompt_version": prompt_version,
            "schema": schema.__name__,
            "model": self._inner.model,
            "recorded_at": datetime.now(UTC).isoformat(),
            "prompt": rendered,
            "response": response.parsed.model_dump(mode="json"),
        }
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        log.info("cassette_recorded", prompt_id=prompt_id, path=str(path.name))
        return response
