"""SubRip (``.srt``) adapter.

SubRip is the plainest caption format: a flat sequence of cues, each one an
index line, a timing line, and one or more text lines, separated by blank
lines::

    1
    00:00:01,000 --> 00:00:02,500
    Hello world

    2
    00:00:02,500 --> 00:00:04,000 X1:100 X2:500 Y1:40 Y2:80
    Second cue
    on two lines

We map cues to a single tier named ``cues`` (override with ``tier=``), tier
stereotype ``NONE`` (SubRip has no hierarchy). Each cue becomes one
``Annotation`` whose body (``annot://schema/srt-cue/v1``) holds:

    {"text": str, "index": int | None}

``index`` is the cue number as written in the source (``None`` when a cue has
no index line); it is informational only, since SubRip indices are positional.

Parsing is tolerant of what real files do: UTF-8 with or without a BOM, CRLF
or CR line endings, extra or whitespace-only blank lines between cues, a
missing final blank line, ``.`` instead of ``,`` before the milliseconds, a
missing index line, a missing blank line between cues (an index line directly
followed by a timing line starts a new cue), and the trailing ``X1:… X2:…
Y1:… Y2:…`` position coordinates of some writers, which are ignored. A timing
line that does not parse raises ``ValueError`` naming its line number.

Lossy fields on dump:
    Provenance, confidence, schema URIs, and tier metadata are dropped, as are
    the source indices (cues are renumbered 1..N in start, then end, order)
    and position coordinates (never kept on load). Any annotation with a
    time interval (any reference kind) and a ``text`` body is emitted, so WebVTT cues dump to
    SubRip too, losing their WebVTT ``id`` and ``settings``. Blank lines inside
    a cue's text cannot be represented (a blank line ends a cue) and are
    dropped. Negative times cannot be written and raise ``ValueError``.

Time discipline:
    SubRip timestamps are integer milliseconds, ``HH:MM:SS,mmm``. They are
    parsed as integers and converted exactly to ``RationalTime`` at ``rate``
    (default 1000; ``rate`` must hold a millisecond exactly, or loading raises
    ``LossyTimeConversionError``). No float is ever involved. On dump, a time
    finer than a millisecond is **truncated** to the millisecond (the floor,
    for non-negative times): truncation is monotone, so every dumped cue keeps
    ``start <= end``; a sub-millisecond cue may become zero-length. WebVTT
    uses the same rule (:mod:`lacing.adapters._cues`).

There is no formal SubRip specification; the de facto description is
https://en.wikipedia.org/wiki/SubRip#Format.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

from lacing.adapters import adapter_generator_id, register_adapter
from lacing.adapters._cues import (
    cue_payload,
    format_cue_time,
    hms_to_ms,
    interval_sort_key,
    iter_with_intervals,
    ms_to_rational,
    read_text,
)
from lacing.model import Annotation, MediaRef, Provenance
from lacing.store import IntervalAnnotationStore, MemoryStore
from lacing.tier import Tier
from lacing.time import RationalTime, TimeInterval


ADAPTER_NAME = "srt"
ADAPTER_VERSION = "1.0.0"
GENERATED_BY = str(adapter_generator_id(ADAPTER_NAME, ADAPTER_VERSION))
BODY_SCHEMA_URI = "annot://schema/srt-cue/v1"
DEFAULT_TIER_NAME = "cues"
DEFAULT_RATE = 1000
DEFAULT_ASSET_ID = "srt:unspecified"
EXTENSION = ".srt"
MEDIA_TYPE = "application/x-subrip"
TIMING_ARROW = "-->"
DECIMAL_SEPARATOR = ","  # what dump writes; load also accepts "."


_TIMESTAMP = r"(\d+):([0-5]?\d):([0-5]?\d)[,.](\d{3})"
_COORDINATES = r"(?:\s+[XY][12]:-?\d+)*"
_TIMING_RE = re.compile(
    rf"^\s*{_TIMESTAMP}\s*{TIMING_ARROW}\s*{_TIMESTAMP}{_COORDINATES}\s*$",
    re.IGNORECASE | re.ASCII,  # ASCII digits only, not full-width ones
)
_INDEX_RE = re.compile(r"^\s*(\d+)\s*$", re.ASCII)
_LINE_BREAK_RE = re.compile(r"\r\n|\r|\n")


# ---------------------------------------------------------------------------
# parsing helpers
# ---------------------------------------------------------------------------


def _parse_timing(line: str, rate: int, *, line_no: int) -> TimeInterval:
    """Parse a timing line into an exact ``TimeInterval``.

    >>> _parse_timing("00:00:01,001 --> 00:00:02.500 X1:1 X2:2 Y1:3 Y2:4", 1000,
    ...               line_no=2)
    TimeInterval(RationalTime(1001, 1000), RationalTime(2500, 1000))
    """
    m = _TIMING_RE.match(line)
    if m is None:
        raise ValueError(f"line {line_no}: malformed SubRip timing line {line!r}")
    g = [int(x) for x in m.groups()]
    start = ms_to_rational(hms_to_ms(*g[:3], millis=g[3]), rate)
    end = ms_to_rational(hms_to_ms(*g[4:7], millis=g[7]), rate)
    if end < start:
        raise ValueError(f"line {line_no}: cue ends before it starts: {line!r}")
    return TimeInterval(start, end)


def _format_timestamp(t: RationalTime) -> str:
    """Format as ``HH:MM:SS,mmm``, truncating sub-millisecond precision.

    >>> _format_timestamp(RationalTime(1001, 1000))
    '00:00:01,001'
    """
    return format_cue_time(t, separator=DECIMAL_SEPARATOR, format_name="SubRip")


def _looks_like_inline_srt(s: str) -> bool:
    """A ``str`` holding SubRip content rather than a path to it."""
    return TIMING_ARROW in s or "\n" in s or "\r" in s


def _is_blank(line: str) -> bool:
    return line.strip() == ""


def _iter_cues(text: str, rate: int) -> Iterator[dict[str, Any]]:
    """Yield ``{"index", "interval", "text"}`` for each cue of ``text``."""
    lines = _LINE_BREAK_RE.split(text)
    n = len(lines)

    def starts_cue(j: int) -> bool:
        # An index line followed by a timing line: a cue, even with no blank
        # line before it.
        return (
            _INDEX_RE.match(lines[j]) is not None
            and j + 1 < n
            and _TIMING_RE.match(lines[j + 1]) is not None
        )

    i = 0
    while i < n:
        while i < n and _is_blank(lines[i]):
            i += 1
        if i >= n:
            break

        index: int | None = None
        m = _INDEX_RE.match(lines[i])
        if m is not None:
            index = int(m.group(1))
            i += 1
            if i >= n or _is_blank(lines[i]):
                raise ValueError(
                    f"line {i}: cue {index} has no timing line after its index"
                )
        elif TIMING_ARROW not in lines[i]:
            raise ValueError(
                f"line {i + 1}: expected a cue index or timing line, got {lines[i]!r}"
            )

        interval = _parse_timing(lines[i], rate, line_no=i + 1)
        i += 1

        payload: list[str] = []
        while i < n and not _is_blank(lines[i]) and not starts_cue(i):
            payload.append(lines[i])
            i += 1

        yield {"index": index, "interval": interval, "text": "\n".join(payload)}


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------


def load(
    source: str | bytes | os.PathLike,
    *,
    rate: int = DEFAULT_RATE,
    asset_id: str = DEFAULT_ASSET_ID,
    attribution: str = "anonymous",
    tier: str = DEFAULT_TIER_NAME,
    **_kwargs: Any,
) -> IntervalAnnotationStore:
    """Parse a SubRip file, or SubRip bytes or text, into a ``MemoryStore``.

    Args:
        source: Bytes (UTF-8, BOM tolerated), a path, or inline text. A
            ``str`` containing a newline or ``-->`` is inline text; any other
            ``str`` is read as a path when one exists there.
        rate: Rate of every ``RationalTime`` produced; must hold a millisecond.
        asset_id: The ``MediaRef.asset_id`` the cues annotate.
        attribution: ``Provenance.was_attributed_to`` of every cue.
        tier: Name of the tier the cues go in.

    Raises:
        ValueError: On a malformed cue, naming the line number.
    """
    text = read_text(source, looks_inline=_looks_like_inline_srt)
    cues = list(_iter_cues(text, rate))  # parse fully before building anything

    store = MemoryStore()
    store.add_tier(Tier(tier))
    now = RationalTime.now(rate)
    for cue in cues:
        store.add(
            Annotation(
                id=uuid4(),
                tier=tier,
                reference=MediaRef(asset_id=asset_id, interval=cue["interval"]),
                body={"text": cue["text"], "index": cue["index"]},
                body_schema_uri=BODY_SCHEMA_URI,
                provenance=Provenance(
                    was_generated_by=GENERATED_BY,
                    was_attributed_to=attribution,
                    generated_at_time=now,
                    activity="import",
                ),
            )
        )
    return store


# ---------------------------------------------------------------------------
# dump
# ---------------------------------------------------------------------------


def _cue_text(body: Any) -> str | None:
    """The cue text of an annotation body, ``None`` if it has none.

    Blank lines are dropped: in SubRip a blank line ends the cue.
    """
    text = body.get("text") if isinstance(body, dict) else None
    if text is None:
        return None
    return cue_payload(str(text))


def dump(
    store: IntervalAnnotationStore,
    target: str | os.PathLike | None = None,
    *,
    tier: str | None = None,
    **_kwargs: Any,
) -> bytes | None:
    """Write annotations as SubRip.

    Args:
        store: Source store. Every annotation with a time interval (any reference kind) and a
            ``text`` body (an SRT or WebVTT cue, or any other) is emitted,
            sorted by start then end, and numbered 1..N in that order.
        target: Output path. If None, returns bytes (UTF-8, no BOM, ``\\n``).
        tier: Restrict export to this tier. None = export all tiers.
    """
    candidates = [
        a
        for a in iter_with_intervals(store)
        if (tier is None or a.tier == tier) and _cue_text(a.body) is not None
    ]
    candidates.sort(key=interval_sort_key)

    blocks: list[str] = []
    for number, ann in enumerate(candidates, start=1):
        iv = ann.interval
        assert iv is not None  # iter_with_intervals filters
        timing = (
            f"{_format_timestamp(iv.start)} {TIMING_ARROW} {_format_timestamp(iv.end)}"
        )
        blocks.append(f"{number}\n{timing}\n{_cue_text(ann.body)}\n")

    blob = "\n".join(blocks).encode("utf-8")
    if target is None:
        return blob
    Path(os.fspath(target)).write_bytes(blob)
    return None


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------


register_adapter(
    name=ADAPTER_NAME,
    version=ADAPTER_VERSION,
    load=load,
    dump=dump,
    extensions=(EXTENSION,),
    media_types=(MEDIA_TYPE,),
    body_schema_uris=(BODY_SCHEMA_URI,),
    description="SubRip (.srt) subtitles. Flat numbered cues, no tier hierarchy.",
)
