"""Gemini client. The only module in the package that imports a vendor SDK.

Imported lazily and behind the ``live`` optional extra, so the offline demo
never needs ``google-genai`` installed. Every other module depends on
``LLMClient``, which is why swapping providers touches this file and nothing
else.

Structured output is requested via ``response_schema`` derived from the
Pydantic model, so the model returns JSON matching the schema and parsing is a
validation step rather than an extraction step. Model output is parsed into a
schema, never scraped from text.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from complaints_intelligence.errors import ComplaintsIntelligenceError
from complaints_intelligence.llm.protocol import LLMResponse, cassette_key
from complaints_intelligence.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - import guard only
    pass

log = get_logger(__name__)

#: Environment variable holding the API key. Never read at import time, so a
#: missing key is a clear error at construction rather than an import failure.
API_KEY_ENV = "GEMINI_API_KEY"


class GeminiClient:
    """Calls Gemini for structured output."""

    def __init__(
        self,
        *,
        model: str,
        temperature: float = 0.0,
        max_output_tokens: int = 4096,
        api_key: str | None = None,
    ) -> None:
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover - depends on extras
            msg = (
                "the 'live' extra is not installed. Install it with "
                "`uv sync --all-extras`, or run in the default replay mode "
                "which needs no credentials."
            )
            raise ComplaintsIntelligenceError(msg) from exc

        key = api_key or os.environ.get(API_KEY_ENV)
        if not key:
            msg = (
                f"{API_KEY_ENV} is not set. Live mode needs an API key; the "
                f"default replay mode does not."
            )
            raise ComplaintsIntelligenceError(msg)

        self._client = genai.Client(api_key=key)
        self._model = model
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens

    @property
    def mode(self) -> str:
        return "live"

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
        from google.genai import types

        config: Any = types.GenerateContentConfig(
            # Temperature zero for reproducibility. It does not make the model
            # deterministic — nothing does, across model versions — which is
            # why the report pins a model identifier and the cassettes are the
            # actual reproducibility mechanism.
            temperature=self._temperature,
            max_output_tokens=self._max_output_tokens,
            response_mime_type="application/json",
            response_schema=schema,
        )
        response = self._client.models.generate_content(
            model=self._model, contents=rendered, config=config
        )

        text = getattr(response, "text", None)
        if not text:
            msg = (
                f"Gemini returned no content for prompt {prompt_id!r}. This is "
                f"usually a safety block or a token limit."
            )
            raise ComplaintsIntelligenceError(msg)

        parsed = schema.model_validate_json(text)
        key = cassette_key(
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            rendered=rendered,
            schema_name=schema.__name__,
            model=self._model,
        )
        log.info(
            "gemini_completion",
            prompt_id=prompt_id,
            model=self._model,
            prompt_chars=len(rendered),
        )
        return LLMResponse(parsed=parsed, cassette_key=key, prompt_chars=len(rendered))
