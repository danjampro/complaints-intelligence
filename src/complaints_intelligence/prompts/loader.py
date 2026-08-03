"""Loading versioned prompt files.

Prompts live in files, not string literals. A prompt change is a code change:
it goes through review, it appears in a diff, and it goes through the
regression suite.

Each file is hashed on load and the hash is pinned into the report. A version
string can be forgotten on edit; a content hash cannot. That is what makes an
undeclared prompt change detectable in a published artefact eighteen months
later.

Rendering uses ``str.format`` with named placeholders rather than Jinja. The
templates are simple, and a substitution language with logic in it is a
substitution language that can be made to do something unintended by a
carefully shaped variable.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from complaints_intelligence.logging import get_logger

log = get_logger(__name__)

_PROMPT_ROOT = Path(__file__).parent

_FRONTMATTER = re.compile(r"^---\n(?P<meta>.*?)\n---\n(?P<body>.*)$", re.DOTALL)


@dataclass(frozen=True)
class Prompt:
    """One versioned prompt template."""

    id: str
    version: str
    #: SHA-256 of the whole file, frontmatter included.
    content_hash: str
    body: str
    path: Path

    def render(self, **variables: str) -> str:
        """Substitute named placeholders.

        Raises on a missing variable rather than leaving a literal ``{name}``
        in the prompt. A half-rendered prompt produces plausible output from
        an incomplete question, which is the worst possible failure mode: it
        does not look like a failure.
        """
        try:
            return self.body.format(**variables)
        except KeyError as exc:
            msg = (
                f"prompt {self.id!r} ({self.path.name}) requires variable "
                f"{exc.args[0]!r}, which was not supplied"
            )
            raise KeyError(msg) from exc


def _parse(path: Path) -> Prompt:
    raw = path.read_text(encoding="utf-8")
    match = _FRONTMATTER.match(raw)
    if match is None:
        msg = f"prompt {path} is missing its --- frontmatter block"
        raise ValueError(msg)

    meta: dict[str, str] = {}
    for line in match.group("meta").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()

    missing = {"id", "version"} - set(meta)
    if missing:
        msg = f"prompt {path} frontmatter is missing {sorted(missing)}"
        raise ValueError(msg)

    return Prompt(
        id=meta["id"],
        version=meta["version"],
        content_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        body=match.group("body").strip(),
        path=path,
    )


@cache
def load(prompt_id: str, version: str) -> Prompt:
    """Load one prompt by id and version.

    Cached: a run loads the same handful of prompts repeatedly, and re-reading
    from disk mid-run would let a prompt change take effect partway through,
    producing a report whose pinned hash describes only part of itself.
    """
    path = _PROMPT_ROOT / version / f"{prompt_id}.md"
    if not path.exists():
        available = sorted(p.stem for p in (_PROMPT_ROOT / version).glob("*.md"))
        msg = f"no prompt {prompt_id!r} in version {version!r}; available: {available}"
        raise FileNotFoundError(msg)

    prompt = _parse(path)
    if prompt.id != prompt_id:
        msg = (
            f"prompt file {path.name} declares id {prompt.id!r} "
            f"but was loaded as {prompt_id!r}"
        )
        raise ValueError(msg)
    if prompt.version != version:
        msg = (
            f"prompt {path} declares version {prompt.version!r} "
            f"but lives in directory {version!r}"
        )
        raise ValueError(msg)
    return prompt


def load_all(version: str) -> dict[str, Prompt]:
    """Load every prompt in a version. Used to pin hashes into the report."""
    directory = _PROMPT_ROOT / version
    if not directory.is_dir():
        msg = f"no prompt version directory {directory}"
        raise FileNotFoundError(msg)
    return {p.stem: load(p.stem, version) for p in sorted(directory.glob("*.md"))}


def prompt_hashes(version: str) -> dict[str, str]:
    """Map prompt id to content hash, for the run trace."""
    return {pid: prompt.content_hash for pid, prompt in load_all(version).items()}
