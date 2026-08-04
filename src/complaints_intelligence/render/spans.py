"""Citation span arithmetic, shared by the renderer and the critic.

A citation is a complaint ID and a character range. Two stages act on that
range and they must agree:

- The **renderer** slices the range out of stored text to print a quotation.
- The **critic** slices the same range to scan it for personal data.

If the critic scanned a narrower span than the renderer printed, a redaction
miss could be widened into view by the renderer without the check ever having
seen it — a citation ending mid-digit-run is the concrete case. So the
arithmetic lives here once rather than being written out at each call site.
"""

from __future__ import annotations


def snap_to_words(text: str, start: int, end: int) -> tuple[int, int]:
    """Widen a span outward to the nearest word boundaries.

    Models pick offsets approximately, and a quotation cut mid-word — "the
    transfer failed without any explanat" — reads as a defect in the report
    rather than in the citation.

    Widening only. The span still covers everything the model cited, so the
    quotation cannot be narrowed to change its sense; it can only gain the
    rest of a word it already partly covered.
    """
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    while end < len(text) and not text[end - 1].isspace() and not text[end].isspace():
        end += 1
    return start, end


def clamp_and_snap(text: str, start: int, end: int) -> tuple[int, int]:
    """Bring a model-supplied span inside the text, then widen it to words.

    Clamping first is what makes the widening safe: ``snap_to_words`` indexes
    ``text`` directly, so an offset past the end would raise rather than
    degrade.
    """
    start = max(0, min(start, len(text)))
    end = max(start, min(end, len(text)))
    return snap_to_words(text, start, end)
