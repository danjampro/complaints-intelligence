"""Constructing the LLM client for a run.

One place decides which implementation is in force, so no node has to know
that more than one exists.
"""

from __future__ import annotations

from complaints_intelligence.config import LLMConfig
from complaints_intelligence.llm.protocol import LLMClient
from complaints_intelligence.llm.replay import ReplayClient
from complaints_intelligence.logging import get_logger

log = get_logger(__name__)


def build_client(config: LLMConfig) -> LLMClient:
    """Build the client for the configured mode.

    ``replay`` is the default and needs no credentials. The other two import
    ``google-genai``, which is why that import lives inside the branch: the
    offline path must not require the extra to be installed.
    """
    match config.mode:
        case "replay":
            return ReplayClient(model=config.model)

        case "live":
            from complaints_intelligence.llm.gemini import GeminiClient

            return GeminiClient(
                model=config.model,
                temperature=config.temperature,
                max_output_tokens=config.max_output_tokens,
                thinking_level=config.thinking_level,
            )

        case "record":
            from complaints_intelligence.llm.gemini import GeminiClient
            from complaints_intelligence.llm.record import RecordingClient

            return RecordingClient(
                GeminiClient(
                    model=config.model,
                    temperature=config.temperature,
                    max_output_tokens=config.max_output_tokens,
                    thinking_level=config.thinking_level,
                )
            )
