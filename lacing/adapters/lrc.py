"""LRC (``.lrc``) lyrics adapter: plain LRC and enhanced LRC with word timing.

An LRC file is a list of time-tagged lyric lines, plus ID tags::

    [ar:Some Artist]
    [ti:Some Title]
    [length: 3:20]
    [offset:+250]
    [00:12.00]I came down to the river
    [00:15.30][01:02.00]chorus, sung twice
    [00:18.75]<00:18.75>Word <00:19.10>by <00:19.40>word

Tiers and bodies (the names lacing's lyric tracks already use,
:mod:`lacing.tracks.subtitle`):

- ``lines`` (stereotype ``NONE``): one annotation per time tag, body
  ``annot://schema/lyric-line/v1`` ``{"text": str}``. A line with several time
  tags (``[00:15.30][01:02.00]chorus``) becomes one annotation per tag, all
  with the same text. Leading and trailing blanks of the text are stripped; a
  tag with no text (``[01:30.00]``) is a line with text ``""``, the usual LRC
  way to clear the display.
- ``words`` (stereotype ``INCLUDED_IN`` ``lines``, only when the file has word
  stamps): one annotation per ``<mm:ss.xx>word`` segment, body
  ``annot://schema/word/v1`` ``{"text": str}``. Text before a line's first word
  stamp is a word starting at the line's time; a stamp followed only by blanks
  ends the previous word without starting one.
- ``tags`` (stereotype ``NONE``, only when the file has ID tags): **one**
  metadata annotation, a point at time 0, body ``annot://schema/lrc-tags/v1``
  ``{"tags": [{"key": str, "value": str}, ...]}``, every ID tag in file order
  with its key and value exactly as written (``[length: 3:20]`` keeps the value
  ``" 3:20"``). :func:`dump` writes these tags back verbatim. They live on one
  annotation rather than in every line body because they describe the file,
  not a line, and so that a store from another format (SubRip, WebVTT) dumps
  without inventing any.

End times (LRC has none):
    A line ends where the next *later* line starts (lines sharing a start, as
    in bilingual files, all end at the next later start). The last line ends
    at ``[length:]`` when the file gives one, else it is a point (``start ==
    end``). A word ends at the next word stamp of its line, or, for the last
    word, at its line's end (a point when that end is before the word starts,
    as in a last line that is itself a point). When a line has several time
    tags, its word stamps (absolute times) are read once, against the latest
    of those tags at or before the first word stamp (the first tag if none).

Offset:
    ``[offset:+/-ms]`` shifts every line and word time; ``+`` makes lyrics
    appear *sooner*, so a time is the tag minus the offset
    (https://en.wikipedia.org/wiki/LRC_(file_format): "with ``+`` causing
    lyrics to appear sooner"). It applies to the whole file wherever the tag
    stands; ``[length:]`` is a media duration and is not shifted. On dump the
    offset tag is written back and the times are shifted back by it, so a file
    with an offset round-trips. A time the offset makes negative raises.

Time discipline:
    Tags are ``[mm:ss.xx]`` or ``[mm:ss.xxx]`` (``.`` or ``:`` before the
    fraction; one to three fraction digits are read as a decimal fraction of a
    second, and ``[mm:ss]`` is a whole second). Every time is parsed as integer
    milliseconds and converted exactly to ``RationalTime`` at ``rate``
    (default 1000; it must hold a millisecond, or loading raises
    ``LossyTimeConversionError``), via :mod:`lacing.adapters._cues`. No float
    is involved. :func:`dump` writes centiseconds by default
    (``precision="cs"``, ``[mm:ss.xx]``, what LRC players expect) or
    milliseconds (``precision="ms"``). Finer times are **truncated** (the
    floor, for the non-negative times LRC holds): truncation is monotone, so
    written lines and word stamps keep their order.

Lossy fields on dump:
    End times are not written (except that ``[length:]`` tags pass through),
    so a line's end becomes the next line's start; gaps between lines are
    lost. Provenance, confidence, schema URIs and tier metadata are dropped.
    A line's text is written on one line: a multi-line text (a SubRip cue) has
    its lines joined by a space, blank ones dropped. Any annotation with a
    time interval and a ``text`` body, on any tier but the words tier, is
    written as a line, so SubRip and WebVTT cues dump to LRC. Word annotations
    on the words tier become word stamps in the line that contains them (the
    latest line starting at or before the word, whose interval holds the word
    or which is a point); words outside every line are dropped. Stamps are put
    before each word where it occurs in the line text; when a word is not
    found there in order, the line is written as its words joined by spaces.
    Text between two words is read back as part of the earlier word.

Malformed input raises ``ValueError`` naming the line number: a line that is
neither blank, a time-tagged line nor a single ID tag; a bad time tag or word
stamp; a bad ``[offset:]`` or ``[length:]`` value, or either tag twice; word
stamps going backwards; a negative time; a ``[length:]`` before the last line.
"""

from __future__ import annotations

import os
import re
from bisect import bisect_right
from collections.abc import Iterator
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any
from uuid import uuid4

from lacing.adapters import adapter_generator_id, register_adapter
from lacing.adapters._common import iter_with_intervals, read_text
from lacing.adapters._cues import (
    MS_PER_SECOND,
    cue_payload,
    hms_to_ms,
    interval_sort_key,
    ms_to_rational,
    rational_to_ms,
    split_cue_lines,
)
from lacing.model import Annotation, MediaRef, Provenance
from lacing.store import IntervalAnnotationStore, MemoryStore
from lacing.tier import Tier, TierStereotype
from lacing.time import RationalTime, TimeInterval
from lacing.tracks.subtitle import (
    LINE_SCHEMA_URI,
    LINES_TIER,
    WORD_SCHEMA_URI,
    WORDS_TIER,
)

ADAPTER_NAME = "lrc"
ADAPTER_VERSION = "1.0.0"
GENERATED_BY = str(adapter_generator_id(ADAPTER_NAME, ADAPTER_VERSION))
LINE_BODY_SCHEMA_URI = LINE_SCHEMA_URI  # annot://schema/lyric-line/v1
WORD_BODY_SCHEMA_URI = WORD_SCHEMA_URI  # annot://schema/word/v1
TAGS_BODY_SCHEMA_URI = "annot://schema/lrc-tags/v1"
DEFAULT_TIER_NAME = LINES_TIER
DEFAULT_WORDS_TIER_NAME = WORDS_TIER
DEFAULT_TAGS_TIER_NAME = "tags"
DEFAULT_RATE = 1000
DEFAULT_ASSET_ID = "lrc:unspecified"
EXTENSION = ".lrc"
# No IANA-registered media type exists for LRC; this is the de facto one.
MEDIA_TYPE = "application/x-lrc"
OFFSET_KEY = "offset"
LENGTH_KEY = "length"

_FRACTION_DIGITS = {"cs": 2, "ms": 3}
_MS_PER_CS = 10

_CLOCK = r"(\d+):([0-5]?\d)(?:[.:](\d{1,3}))?"
_CLOCK_RE = re.compile(rf"^{_CLOCK}$", re.ASCII)
_LEADING_TAG_RE = re.compile(r"\[([^\]]*)\]")
_ID_TAG_RE = re.compile(r"^([A-Za-z#][\w#-]*):(.*)$", re.ASCII | re.DOTALL)
# What claims to be a word stamp: "<" digits ":" ... ">". Its inside must then
# be a valid clock; "<3" and other angle brackets in lyrics are plain text.
_WORD_STAMP_RE = re.compile(r"<(\d+:[^<>]*)>", re.ASCII)
_OFFSET_RE = re.compile(r"^\s*([+-]?\d+)\s*$", re.ASCII)


# ---------------------------------------------------------------------------
# parsing helpers
# ---------------------------------------------------------------------------


def _clock_to_ms(clock: str) -> int | None:
    """Milliseconds of an ``mm:ss[.xx]`` clock, ``None`` if it is not one.

    >>> _clock_to_ms("01:02.5"), _clock_to_ms("01:02:05"), _clock_to_ms("0:02.005")
    (62500, 62050, 2005)
    >>> _clock_to_ms("00:61.00") is None
    True
    """
    m = _CLOCK_RE.match(clock)
    if m is None:
        return None
    minutes, seconds, frac = m.groups()
    millis = int((frac or "").ljust(3, "0"))
    return hms_to_ms(0, int(minutes), int(seconds), millis=millis)


@dataclass(frozen=True, slots=True)
class _Row:
    """One time-tagged line of the file, before offset and end times."""

    line_no: int
    tag_ms: tuple[int, ...]
    text: str
    # (stamp_ms or None for "the line's time", segment text) for enhanced LRC
    segments: tuple[tuple[int | None, str], ...] | None


def _parse_segments(
    text: str, *, line_no: int
) -> tuple[str, tuple[tuple[int | None, str], ...] | None]:
    """Split a line's text at its word stamps: ``(plain text, segments)``.

    ``segments`` is None when the text has no word stamp.
    """
    stamps = list(_WORD_STAMP_RE.finditer(text))
    if not stamps:
        return text.strip(), None
    segments: list[tuple[int | None, str]] = []
    if text[: stamps[0].start()].strip():
        segments.append((None, text[: stamps[0].start()]))
    for i, m in enumerate(stamps):
        ms = _clock_to_ms(m.group(1))
        if ms is None:
            raise ValueError(f"line {line_no}: malformed LRC word stamp <{m.group(1)}>")
        end = stamps[i + 1].start() if i + 1 < len(stamps) else len(text)
        segments.append((ms, text[m.end() : end]))
    return _WORD_STAMP_RE.sub("", text).strip(), tuple(segments)


def _iter_lines(text: str) -> Iterator[tuple[int, str, Any]]:
    """Yield ``(line_no, "row", _Row)`` or ``(line_no, "tag", (key, value))``
    for each non-blank line of ``text``."""
    for line_no, line in enumerate(split_cue_lines(text), start=1):
        if not line.strip():
            continue
        stripped = line.lstrip()
        first = _LEADING_TAG_RE.match(stripped)
        if first is None:
            raise ValueError(
                f"line {line_no}: expected an LRC time tag or ID tag, got {line!r}"
            )
        inner = first.group(1)
        id_tag = _ID_TAG_RE.match(inner)
        if id_tag is not None:
            if stripped[first.end() :].strip():
                raise ValueError(
                    f"line {line_no}: text after the ID tag [{inner}]: {line!r}"
                )
            yield line_no, "tag", (id_tag.group(1), id_tag.group(2))
            continue
        tag_ms: list[int] = []
        pos = 0
        while (m := _LEADING_TAG_RE.match(stripped, pos)) is not None:
            candidate = m.group(1)
            if tag_ms and not candidate[:1].isdigit():
                break  # "[00:12.00][Chorus] ..." keeps "[Chorus]" as text
            ms = _clock_to_ms(candidate)
            if ms is None:
                raise ValueError(
                    f"line {line_no}: malformed LRC time tag [{candidate}]"
                )
            tag_ms.append(ms)
            pos = m.end()
        plain, segments = _parse_segments(stripped[pos:], line_no=line_no)
        yield line_no, "row", _Row(line_no, tuple(tag_ms), plain, segments)


def _parse_offset(value: str, *, where: str) -> int:
    m = _OFFSET_RE.match(value)
    if m is None:
        raise ValueError(f"{where}: malformed LRC [offset:] value {value!r}")
    return int(m.group(1))


def _parse_length(value: str, *, where: str) -> int:
    ms = _clock_to_ms(value.strip())
    if ms is None:
        raise ValueError(f"{where}: malformed LRC [length:] value {value!r}")
    return ms


@dataclass(frozen=True, slots=True)
class _Parsed:
    rows: list[_Row]
    tags: list[tuple[str, str]]
    offset_ms: int
    length: tuple[int, int] | None  # (ms, line_no)


def _parse(text: str) -> _Parsed:
    rows: list[_Row] = []
    tags: list[tuple[str, str]] = []
    special: dict[str, tuple[int, int]] = {}  # key -> (value, line_no)
    for line_no, kind, item in _iter_lines(text):
        if kind == "row":
            rows.append(item)
            continue
        key, value = item
        tags.append((key, value))
        lowered = key.lower()
        if lowered in (OFFSET_KEY, LENGTH_KEY):
            if lowered in special:
                raise ValueError(f"line {line_no}: a second [{lowered}:] tag")
            parse = _parse_offset if lowered == OFFSET_KEY else _parse_length
            special[lowered] = (parse(value, where=f"line {line_no}"), line_no)
    offset = special.get(OFFSET_KEY, (0, 0))[0]
    return _Parsed(rows, tags, offset, special.get(LENGTH_KEY))


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------


def _looks_like_inline_lrc(s: str) -> bool:
    """A ``str`` holding LRC content rather than a path to it."""
    return "\n" in s or "\r" in s or s.lstrip().startswith("[")


def _effective_ms(tag_ms: int, offset_ms: int, *, line_no: int) -> int:
    ms = tag_ms - offset_ms  # "+" makes lyrics appear sooner
    if ms < 0:
        raise ValueError(
            f"line {line_no}: time {tag_ms} ms minus offset {offset_ms} ms is negative"
        )
    return ms


def _line_ends(starts: list[int], length_ms: int | None) -> list[int | None]:
    """End of each line (``starts`` sorted): the next later start, then
    ``length_ms`` (None, a point, without it)."""
    distinct = sorted(set(starts))
    ends: list[int | None] = []
    for s in starts:
        i = bisect_right(distinct, s)
        ends.append(distinct[i] if i < len(distinct) else length_ms)
    return ends


def _words_of(
    row: _Row, occurrences: list[tuple[int, int]], offset_ms: int
) -> list[tuple[str, int, int]]:
    """``(text, start_ms, end_ms)`` of each word of an enhanced ``row``.

    ``occurrences`` are the row's ``(start_ms, end_ms)`` lines, sorted.
    """
    assert row.segments is not None
    stamped = [ms for ms, _ in row.segments if ms is not None]
    first_stamp = _effective_ms(stamped[0], offset_ms, line_no=row.line_no)
    anchor = occurrences[0]
    for occ in occurrences:
        if occ[0] <= first_stamp:
            anchor = occ
    times = [
        anchor[0] if ms is None else _effective_ms(ms, offset_ms, line_no=row.line_no)
        for ms, _ in row.segments
    ]
    if any(b < a for a, b in zip(times, times[1:])):
        raise ValueError(f"line {row.line_no}: LRC word stamps go backwards")
    words: list[tuple[str, int, int]] = []
    for i, ((_, seg), start) in enumerate(zip(row.segments, times)):
        word = seg.strip()
        if not word:
            continue  # a stamp followed by blanks only ends the previous word
        end = times[i + 1] if i + 1 < len(times) else max(anchor[1], start)
        words.append((word, start, end))
    return words


def load(
    source: str | bytes | os.PathLike,
    *,
    rate: int = DEFAULT_RATE,
    asset_id: str = DEFAULT_ASSET_ID,
    attribution: str = "anonymous",
    tier: str = DEFAULT_TIER_NAME,
    words_tier: str = DEFAULT_WORDS_TIER_NAME,
    tags_tier: str = DEFAULT_TAGS_TIER_NAME,
    **_kwargs: Any,
) -> IntervalAnnotationStore:
    """Parse an LRC file, or LRC bytes or text, into a ``MemoryStore``.

    Lines go on ``tier``, word stamps on ``words_tier``, ID tags on one
    annotation on ``tags_tier`` (see the module docstring for end times and
    the offset sign).

    Args:
        source: Bytes (UTF-8, BOM tolerated), a path, or inline text. A
            ``str`` with a line break, or starting with ``[``, is inline text;
            any other ``str`` is read as a path when a file exists there.
        rate: Rate of every ``RationalTime`` produced; must hold a millisecond.
        asset_id: The ``MediaRef.asset_id`` the lyrics annotate.
        attribution: ``Provenance.was_attributed_to`` of every annotation.
        tier: Name of the lines tier.
        words_tier: Name of the words tier (created only for enhanced LRC).
        tags_tier: Name of the ID-tag tier (created only when there are tags).

    Raises:
        ValueError: On malformed input, naming the line number.
    """
    parsed = _parse(read_text(source, looks_inline=_looks_like_inline_lrc))
    offset = parsed.offset_ms

    # (start_ms, row) per time tag, sorted by start; file order breaks ties.
    lines = sorted(
        (
            (_effective_ms(ms, offset, line_no=row.line_no), row)
            for row in parsed.rows
            for ms in row.tag_ms
        ),
        key=lambda pair: pair[0],
    )
    length_ms = None
    if parsed.length is not None:
        length_ms, length_line = parsed.length
        if lines and length_ms < lines[-1][0]:
            raise ValueError(
                f"line {length_line}: [length:] ends before the last line starts"
            )
    ends = _line_ends([s for s, _ in lines], length_ms)
    spans = [(s, s if e is None else e) for (s, _), e in zip(lines, ends)]

    occurrences: dict[int, list[tuple[int, int]]] = {}
    for (_, row), span in zip(lines, spans):
        occurrences.setdefault(row.line_no, []).append(span)
    words = [
        w
        for row in parsed.rows
        if row.segments is not None and row.tag_ms
        for w in _words_of(row, occurrences[row.line_no], offset)
    ]

    store = MemoryStore()
    provenance = Provenance(
        was_generated_by=GENERATED_BY,
        was_attributed_to=attribution,
        generated_at_time=RationalTime.now(rate),
        activity="import",
    )

    def add(tier_name: str, start: int, end: int, body: dict, uri: str) -> None:
        interval = TimeInterval(ms_to_rational(start, rate), ms_to_rational(end, rate))
        store.add(
            Annotation(
                id=uuid4(),
                tier=tier_name,
                reference=MediaRef(asset_id=asset_id, interval=interval),
                body=body,
                body_schema_uri=uri,
                provenance=provenance,
            )
        )

    store.add_tier(Tier(tier))
    for (_, row), (start, end) in zip(lines, spans):
        add(tier, start, end, {"text": row.text}, LINE_BODY_SCHEMA_URI)
    if words:
        store.add_tier(
            Tier(words_tier, stereotype=TierStereotype.INCLUDED_IN, parent=tier)
        )
        for text, start, end in words:
            add(words_tier, start, end, {"text": text}, WORD_BODY_SCHEMA_URI)
    if parsed.tags:
        store.add_tier(Tier(tags_tier))
        body = {"tags": [{"key": k, "value": v} for k, v in parsed.tags]}
        add(tags_tier, 0, 0, body, TAGS_BODY_SCHEMA_URI)
    return store


# ---------------------------------------------------------------------------
# dump
# ---------------------------------------------------------------------------


def _format_clock(t: RationalTime, *, offset_ms: int, precision: str) -> str:
    """``t`` shifted back by ``offset_ms``, as ``mm:ss.xx`` (or ``.xxx``),
    truncated.

    >>> _format_clock(RationalTime(62509, 1000), offset_ms=0, precision="cs")
    '01:02.50'
    >>> _format_clock(RationalTime(1, 3), offset_ms=250, precision="ms")
    '00:00.583'
    """
    written = t.to_fraction() + Fraction(offset_ms, MS_PER_SECOND)
    if written < 0:  # checked before truncation, which would round -1/3 ms to 0
        raise ValueError(f"LRC cannot represent a negative time: {t!r}")
    ms = rational_to_ms(RationalTime(written.numerator, written.denominator))
    minutes, rem = divmod(ms, 60 * MS_PER_SECOND)
    seconds, millis = divmod(rem, MS_PER_SECOND)
    if precision == "cs":
        return f"{minutes:02d}:{seconds:02d}.{millis // _MS_PER_CS:02d}"
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"


def _line_text(body: Any) -> str | None:
    """A body's text on one physical line; ``None`` if it has none."""
    text = body.get("text") if isinstance(body, dict) else None
    if text is None:
        return None
    return " ".join(split_cue_lines(cue_payload(str(text))))


def _stamped_text(
    text: str, line_end: RationalTime, words: list[Annotation], stamp
) -> str:
    """``text`` with a ``<stamp>`` before each word, and an end stamp after a
    word (and the text that follows it) whose end is not where the next word,
    or the line's end, takes over."""
    positions: list[int] = []
    cursor = 0
    for w in words:
        found = text.find(w.body["text"], cursor)
        if found < 0:
            positions = []
            break
        positions.append(found)
        cursor = found + len(w.body["text"])
    if not positions:  # a word not in the text: write the words alone
        text = " ".join(w.body["text"] for w in words)
        positions = []
        cursor = 0
        for w in words:
            positions.append(cursor)
            cursor += len(w.body["text"]) + 1
    out = [text[: positions[0]]]
    for i, (w, pos) in enumerate(zip(words, positions)):
        iv = w.interval
        assert iv is not None
        word_end = pos + len(w.body["text"])
        out.append(f"<{stamp(iv.start)}>{w.body['text']}")
        nxt = positions[i + 1] if i + 1 < len(words) else len(text)
        out.append(text[word_end:nxt])  # read back as part of this word
        takes_over = words[i + 1].interval.start if i + 1 < len(words) else line_end
        if iv.end != takes_over:
            out.append(f"<{stamp(iv.end)}>")
    return "".join(out)


def _assign_words(
    lines: list[Annotation], words: list[Annotation]
) -> dict[int, list[Annotation]]:
    """Words per line index: the latest line starting at or before the word
    that holds it (or is a point). Among lines with that same start (a
    bilingual file), the first whose text contains the word."""
    starts = [a.interval.start.to_fraction() for a in lines]

    def holds(i: int, w: Annotation) -> bool:
        iv = lines[i].interval
        return iv.is_point or w.interval.end <= iv.end

    by_line: dict[int, list[Annotation]] = {}
    for w in words:
        start = w.interval.start.to_fraction()
        tied: list[int] = []  # the holders sharing the latest holder's start
        for i in range(bisect_right(starts, start) - 1, -1, -1):
            if tied and starts[i] != starts[tied[0]]:
                break
            if holds(i, w):
                tied.append(i)
        if not tied:
            continue  # outside every line: dropped
        tied.reverse()
        text = w.body["text"]
        chosen = next(
            (i for i in tied if text in (_line_text(lines[i].body) or "")), tied[0]
        )
        by_line.setdefault(chosen, []).append(w)
    return by_line


def dump(
    store: IntervalAnnotationStore,
    target: str | os.PathLike | None = None,
    *,
    tier: str | None = None,
    words_tier: str = DEFAULT_WORDS_TIER_NAME,
    precision: str = "cs",
    **_kwargs: Any,
) -> bytes | None:
    """Write annotations as LRC (enhanced LRC when there are words).

    ID tags (from ``annot://schema/lrc-tags/v1`` annotations) come first,
    verbatim; then one ``[mm:ss.xx]text`` row per line, sorted by start then
    end; word annotations on ``words_tier`` become ``<mm:ss.xx>`` stamps in
    the line holding them. With an ``[offset:]`` tag, times are shifted back
    by it, so that loading applies it again.

    Args:
        store: Source store. Every annotation with a time interval and a
            ``text`` body not on ``words_tier`` is a line (an LRC line, a
            SubRip or WebVTT cue, or any other).
        target: Output path. If None, returns bytes (UTF-8, no BOM, ``\\n``).
        tier: Restrict lines to this tier. None = every tier but ``words_tier``.
        words_tier: Tier whose annotations are written as word stamps.
        precision: ``"cs"`` (``[mm:ss.xx]``, default) or ``"ms"``
            (``[mm:ss.xxx]``); finer times are truncated.
    """
    if precision not in _FRACTION_DIGITS:
        raise ValueError(f"precision must be one of {sorted(_FRACTION_DIGITS)}")
    annotations = list(iter_with_intervals(store))
    tags = [
        (t["key"], t["value"])
        for a in annotations
        if a.body_schema_uri == TAGS_BODY_SCHEMA_URI and isinstance(a.body, dict)
        for t in a.body.get("tags", [])
    ]
    offsets = [v for k, v in tags if k.lower() == OFFSET_KEY]
    if len(offsets) > 1:
        raise ValueError(f"more than one [{OFFSET_KEY}:] tag to write: {offsets}")
    offset = _parse_offset(offsets[0], where="lrc-tags body") if offsets else 0

    def stamp(t: RationalTime) -> str:
        return _format_clock(t, offset_ms=offset, precision=precision)

    lines = sorted(
        (
            a
            for a in annotations
            if a.tier != words_tier
            and (tier is None or a.tier == tier)
            and _line_text(a.body) is not None
        ),
        key=interval_sort_key,
    )
    words = sorted(
        (a for a in annotations if a.tier == words_tier and _line_text(a.body)),
        key=interval_sort_key,
    )
    words_by_line = _assign_words(lines, words)

    rows = [f"[{key}:{value}]" for key, value in tags]
    for i, line in enumerate(lines):
        iv = line.interval
        assert iv is not None  # iter_with_intervals filters
        text = _line_text(line.body) or ""
        if i in words_by_line:
            text = _stamped_text(text, iv.end, words_by_line[i], stamp)
        rows.append(f"[{stamp(iv.start)}]{text}")

    blob = "".join(f"{row}\n" for row in rows).encode("utf-8")
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
    body_schema_uris=(
        LINE_BODY_SCHEMA_URI,
        WORD_BODY_SCHEMA_URI,
        TAGS_BODY_SCHEMA_URI,
    ),
    description="LRC lyrics (.lrc), plain and enhanced (word stamps); ID tags kept.",
)
