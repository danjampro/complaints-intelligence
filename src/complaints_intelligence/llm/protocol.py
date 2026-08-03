"""The LLM seam.

Every node depends on this protocol. No node imports a vendor SDK, and the
only module that does is ``llm.gemini``, behind an optional extra.

Two properties are enforced by the signature rather than by convention:

- The caller supplies a Pydantic ``schema`` and receives an instance of it.
  Model output is parsed into a schema, never scraped from text, so a
  malformed response is a validation error at the boundary and not a
  surprising string three stages later.
- ``prompt_id`` and ``prompt_version`` are required. Every call is
  attributable to a versioned prompt file, which is what makes a published
  report reconstructable.
"""

from __future__ import annotations

import hashlib
import json
from typing import Protocol, runtime_checkable

from pydantic import BaseModel


class LLMResponse[T: BaseModel](BaseModel):
    """A parsed model response plus what is needed to trace it."""

    model_config = {"frozen": True}

    parsed: T
    #: Key of the cassette this came from, in replay and record modes.
    cassette_key: str | None = None
    #: Characters sent. Cheap proxy for cost, and a budget signal.
    prompt_chars: int = 0


@runtime_checkable
class LLMClient(Protocol):
    """Produces structured output from a rendered prompt."""

    @property
    def mode(self) -> str:
        """``replay``, ``live`` or ``record``. Recorded in the run trace."""
        ...

    @property
    def model(self) -> str:
        """Model identifier, pinned into the report."""
        ...

    def complete[T: BaseModel](
        self,
        *,
        prompt_id: str,
        prompt_version: str,
        rendered: str,
        schema: type[T],
    ) -> LLMResponse[T]:
        """Run one completion and parse the result into ``schema``."""
        ...


def cassette_key(
    *,
    prompt_id: str,
    prompt_version: str,
    rendered: str,
    schema_name: str,
    model: str,
) -> str:
    """Stable key identifying one prompt/schema/model exchange.

    Hashing the *rendered* prompt rather than its inputs is deliberate. Any
    change to the prompt template, the retrieved evidence, or the brief
    changes the key and produces a cassette miss — which is the intended
    behaviour. A recording that silently kept being replayed after its inputs
    changed would be a fiction, and the demo's credibility rests on the
    cassettes being genuine recordings of the prompts actually shown here.
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
