"""The live Gemini client and the recorder that captures its exchanges.

The only module in the package that imports a vendor SDK, and it is imported
lazily behind the ``live`` extra — which is why swapping providers touches this
file and nothing else.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

from complaints_intelligence.llm.client import (
    CASSETTE_DIR,
    LLMClient,
    LLMResponse,
    cassette_key,
    cassette_path,
)

log = logging.getLogger(__name__)

API_KEY_ENV = "GEMINI_API_KEY"

#: Rate limiting and 5xx are ordinary weather on a hosted API. A 400 means the
#: request is wrong and retrying produces the same wrong answer more slowly.
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_RETRY_ATTEMPTS = 5
_RETRY_INITIAL_DELAY = 2.0
#: A daily quota reports a retry delay in hours; waiting for it would hang a
#: run that should fail with a clear message instead.
_RETRY_MAX_DELAY = 70.0
_RETRY_DELAY_RE = re.compile(r"'?retryDelay'?\s*:\s*'?(\d+(?:\.\d+)?)s")


class GeminiClient:
    """Calls Gemini for structured output.

    Structured output is requested via ``response_schema``, so parsing is a
    validation step rather than an extraction step.
    """

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
                "`uv sync --all-extras`, or use the default replay mode, which "
                "needs no credentials."
            )
            raise RuntimeError(msg) from exc

        key = api_key or os.environ.get(API_KEY_ENV)
        if not key:
            msg = f"{API_KEY_ENV} is not set. The default replay mode needs no key."
            raise RuntimeError(msg)

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

        config: Any = types.GenerateContentConfig(
            # Temperature zero for reproducibility. It does not make the model
            # deterministic — nothing does, across model versions — which is
            # why the recordings are the actual reproducibility mechanism.
            temperature=self._temperature,
            max_output_tokens=self._max_output_tokens,
            response_mime_type="application/json",
            response_schema=schema,
            thinking_config=types.ThinkingConfig(
                thinking_level=cast("Any", self._thinking_level)
            ),
        )
        response = self._generate_with_retry(rendered, config, prompt_id)

        # A truncated response is invalid JSON, and the resulting parse error
        # points at syntax rather than at the real cause. Check why generation
        # stopped first, so the message names what actually happened.
        reason = self._finish_reason(response)
        if reason and reason not in {"STOP", "FINISH_REASON_STOP"}:
            msg = (
                f"Gemini stopped early on prompt {prompt_id!r} "
                f"(finish_reason={reason}). For MAX_TOKENS raise "
                f"`llm.max_output_tokens`; for SAFETY, the prompt or the "
                f"retrieved complaint text triggered a filter."
            )
            raise RuntimeError(msg)

        text = getattr(response, "text", None)
        if not text:
            msg = f"Gemini returned no content for prompt {prompt_id!r}."
            raise RuntimeError(msg)

        return LLMResponse(
            parsed=schema.model_validate_json(text),
            cassette_key=cassette_key(
                prompt_id=prompt_id,
                prompt_version=prompt_version,
                rendered=rendered,
                schema_name=schema.__name__,
                model=self._model,
            ),
            prompt_chars=len(rendered),
        )

    def _generate_with_retry(self, rendered: str, config: Any, prompt_id: str) -> Any:
        """Call the model, retrying only transient server errors."""
        from google.genai import errors

        delay = _RETRY_INITIAL_DELAY
        last: Exception | None = None
        for attempt in range(1, _RETRY_ATTEMPTS + 1):
            try:
                return self._client.models.generate_content(
                    model=self._model, contents=rendered, config=config
                )
            except (errors.ServerError, errors.ClientError) as exc:
                if getattr(exc, "code", None) not in _RETRYABLE_STATUS:
                    raise
                last = exc
                if attempt == _RETRY_ATTEMPTS:
                    break
                # Prefer the server's own hint: a 429 carries the exact delay
                # it wants, and backoff either waits too long or retries into
                # the same limit.
                wait = _retry_after(exc) or delay
                log.warning("retrying %s after %.1fs", prompt_id, wait)
                time.sleep(min(wait, _RETRY_MAX_DELAY))
                delay *= 2

        msg = f"Gemini did not respond for prompt {prompt_id!r}: {last}"
        raise RuntimeError(msg)

    @staticmethod
    def _finish_reason(response: Any) -> str | None:
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            return None
        reason = getattr(candidates[0], "finish_reason", None)
        return None if reason is None else str(getattr(reason, "name", reason))


def _retry_after(exc: Exception) -> float | None:
    """Seconds the server asked us to wait, parsed from the error payload."""
    match = _RETRY_DELAY_RE.search(str(exc))
    return float(match.group(1)) if match else None


class RecordingClient:
    """Delegates to a live client and persists every exchange.

    The rendered prompt is written alongside the response so a reviewer can
    read exactly what the model was asked, including the fenced untrusted
    block, rather than taking it on trust.
    """

    def __init__(self, inner: LLMClient, *, directory: Path | None = None) -> None:
        self._inner = inner
        self._directory = directory or CASSETTE_DIR
        self._directory.mkdir(parents=True, exist_ok=True)

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
        key = cassette_key(
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            rendered=rendered,
            schema_name=schema.__name__,
            model=self._inner.model,
        )
        # Resume rather than re-record: a full run is a dozen rate-limited
        # calls, and without this one failure two thirds through means paying
        # for the whole run again.
        existing = cassette_path(self._directory, key)
        if existing.exists():
            payload = json.loads(existing.read_text(encoding="utf-8"))
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
        cassette_path(self._directory, key).write_text(
            json.dumps(
                {
                    "prompt_id": prompt_id,
                    "prompt_version": prompt_version,
                    "schema": schema.__name__,
                    "model": self._inner.model,
                    "recorded_at": datetime.now(UTC).isoformat(),
                    "prompt": rendered,
                    "response": response.parsed.model_dump(mode="json"),
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        return response
