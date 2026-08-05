"""Hand-written demonstration data, and the taxonomy it is classified against.

Small enough to read: a reviewer can open the JSON and follow exactly what the
pipeline is doing to it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from complaints_intelligence.inputs import ComplaintEnvelope, Fact, ResolutionNote

FIXTURE_DIR = Path(__file__).parent


def _read(name: str) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(
        (FIXTURE_DIR / name).read_text(encoding="utf-8")
    )
    return payload


def load_complaints() -> tuple[ComplaintEnvelope, ...]:
    """The complaint sample, in file order."""
    return tuple(
        ComplaintEnvelope.model_validate(row)
        for row in _read("complaints.json")["complaints"]
    )


def load_resolutions() -> tuple[ResolutionNote, ...]:
    """Resolution notes on the closed complaints."""
    return tuple(
        ResolutionNote.model_validate(row)
        for row in _read("resolutions.json")["resolutions"]
    )


def load_facts() -> tuple[Fact, ...]:
    """The precomputed fact store for the reporting week."""
    return tuple(Fact.model_validate(row) for row in _read("facts.json")["facts"])


def load_brief_spec() -> dict[str, Any]:
    """The metrics layer's declared verdicts, before measured cluster
    properties are added by ``brief.build_brief``."""
    return _read("brief.json")
