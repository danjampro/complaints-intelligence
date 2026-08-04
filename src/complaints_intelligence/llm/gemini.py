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
import re
import time
from typing import TYPE_CHECKING, Any, cast

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

#: Transient failures worth retrying. 429 is rate limiting; 5xx is the
#: provider. Everything else means the request itself is wrong.
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_RETRY_ATTEMPTS = 5
_RETRY_INITIAL_DELAY = 2.0
#: Ceiling on a single wait. A daily quota reports a retry delay measured in
#: hours; waiting for it would hang a run that should fail with a clear
#: message instead.
_RETRY_MAX_DELAY = 70.0

_RETRY_DELAY_RE = re.compile(r"'?retryDelay'?\s*:\s*'?(\d+(?:\.\d+)?)s")


def _retry_after(exc: Exception) -> float | None:
    """Seconds the server asked us to wait, if it said.

    Parsed from the message rather than a typed field because the SDK
    surfaces the ``RetryInfo`` detail only in the raw error payload.
    """
    match = _RETRY_DELAY_RE.search(str(exc))
    return float(match.group(1)) if match else None


class GeminiClient:
    """Calls Gemini for structured output."""

    def __init__(
        self,
        *,
        model: str,
        temperature: float = 0.0,
        max_output_tokens: int = 16384,
        thinking_level: str = "low",
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
        self._thinking_level = thinking_level

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

        # The SDK types this as its own enum; the value is validated against
        # a Literal in `LLMConfig`, so the cast is narrowing a string we have
        # already constrained rather than trusting arbitrary input.
        thinking: Any = types.ThinkingConfig(
            thinking_level=cast("Any", self._thinking_level)
        )
        config: Any = types.GenerateContentConfig(
            # Temperature zero for reproducibility. It does not make the model
            # deterministic — nothing does, across model versions — which is
            # why the report pins a model identifier and the cassettes are the
            # actual reproducibility mechanism.
            temperature=self._temperature,
            max_output_tokens=self._max_output_tokens,
            response_mime_type="application/json",
            response_schema=schema,
            thinking_config=thinking,
        )
        response = self._generate_with_retry(rendered, config, prompt_id)

        # A truncated response is invalid JSON, and the resulting parse error
        # points at a syntax problem rather than at the real cause. Check the
        # finish reason first so the message names what actually happened.
        finish_reason = self._finish_reason(response)
        if finish_reason and finish_reason not in {"STOP", "FINISH_REASON_STOP"}:
            msg = (
                f"Gemini stopped early on prompt {prompt_id!r} "
                f"(finish_reason={finish_reason}). For MAX_TOKENS, raise "
                f"`llm.max_output_tokens`; for SAFETY, the prompt or the "
                f"retrieved complaint text triggered a filter."
            )
            raise ComplaintsIntelligenceError(msg)

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

    def _generate_with_retry(self, rendered: str, config: Any, prompt_id: str) -> Any:
        """Call the model, retrying transient server errors.

        Rate limits and 5xx responses are ordinary weather on a hosted API,
        and a run makes a dozen or so calls — without this, recording a full
        set of cassettes fails most times it is attempted, halfway through.

        Only transient classes are retried. A 400 means the request is wrong
        and retrying it will produce the same wrong answer more slowly.
        """
        from google.genai import errors

        delay = _RETRY_INITIAL_DELAY
        last: Exception | None = None

        for attempt in range(1, _RETRY_ATTEMPTS + 1):
            try:
                return self._client.models.generate_content(
                    model=self._model, contents=rendered, config=config
                )
            except (errors.ServerError, errors.ClientError) as exc:
                status = getattr(exc, "code", None)
                if status not in _RETRYABLE_STATUS:
                    raise
                last = exc
                if attempt == _RETRY_ATTEMPTS:
                    break
                # Prefer the server's own hint over guessing. A 429 carries
                # the exact delay it wants; exponential backoff either waits
                # too long or retries into the same limit.
                wait = _retry_after(exc) or delay
                log.warning(
                    "gemini_retry",
                    prompt_id=prompt_id,
                    status=status,
                    attempt=attempt,
                    sleeping=round(wait, 1),
                )
                time.sleep(min(wait, _RETRY_MAX_DELAY))
                delay *= 2

        msg = (
            f"Gemini did not respond for prompt {prompt_id!r} after "
            f"{_RETRY_ATTEMPTS} attempts: {last}"
        )
        raise ComplaintsIntelligenceError(msg)

    @staticmethod
    def _finish_reason(response: Any) -> str | None:
        """Why generation stopped, if the SDK reported it."""
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            return None
        reason = getattr(candidates[0], "finish_reason", None)
        if reason is None:
            return None
        return str(getattr(reason, "name", reason))
