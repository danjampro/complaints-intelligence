"""Loading versioned prompt files.

Prompts live in files, not string literals: a prompt change is a code change,
so it appears in a diff and goes through the regression suite.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

_PROMPT_ROOT = Path(__file__).parent
_FRONTMATTER = re.compile(r"^---\n(?P<meta>.*?)\n---\n(?P<body>.*)$", re.DOTALL)


@dataclass(frozen=True)
class Prompt:
    """One versioned prompt template."""

    id: str
    version: str
    body: str
    path: Path

    def render(self, **variables: str) -> str:
        """Substitute named placeholders, raising on a missing one.

        Rendering uses ``str.format`` rather than a templating language: a
        substitution language with logic in it can be made to do something
        unintended by a carefully shaped variable. A half-rendered prompt is
        the worst failure mode, because it does not look like one.
        """
        try:
            return self.body.format(**variables)
        except KeyError as exc:
            msg = (
                f"prompt {self.id!r} requires variable {exc.args[0]!r}, "
                f"which was not supplied"
            )
            raise KeyError(msg) from exc


@cache
def load(prompt_id: str, version: str) -> Prompt:
    """Load one prompt by id and version.

    Cached, so a prompt edited mid-run cannot take effect partway through and
    produce a report that is half one version and half another.
    """
    path = _PROMPT_ROOT / version / f"{prompt_id}.md"
    if not path.exists():
        available = sorted(p.stem for p in (_PROMPT_ROOT / version).glob("*.md"))
        msg = f"no prompt {prompt_id!r} in version {version!r}; available: {available}"
        raise FileNotFoundError(msg)

    raw = path.read_text(encoding="utf-8")
    match = _FRONTMATTER.match(raw)
    if match is None:
        msg = f"prompt {path} is missing its --- frontmatter block"
        raise ValueError(msg)

    meta = {
        key.strip(): value.strip()
        for key, _, value in (
            line.partition(":")
            for line in match.group("meta").splitlines()
            if line.strip()
        )
    }
    if meta.get("id") != prompt_id or meta.get("version") != version:
        msg = (
            f"prompt file {path.name} declares id={meta.get('id')!r} "
            f"version={meta.get('version')!r}, but was loaded as "
            f"{prompt_id!r}/{version!r}"
        )
        raise ValueError(msg)

    return Prompt(
        id=prompt_id, version=version, body=match.group("body").strip(), path=path
    )
