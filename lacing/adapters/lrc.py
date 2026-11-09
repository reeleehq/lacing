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
  way to clear the display. Lines may overlap (see the end times below).
- ``words`` (stereotype ``INCLUDED_IN`` ``lines``, only when the file has word
  stamps): one annotation per ``<mm:ss.xx>word`` segment, body
  ``annot://schema/word/v1`` ``{"text": str}``. Text before a line's first word
  stamp is a word starting at the line's time; a stamp followed only by blanks
  ends the previous word without starting one. LRC has no escape, so a literal
  ``<mm:ss.xx>`` inside lyric text is read as a word stamp.
- ``tags`` (stereotype ``NONE``, only when the file has ID tags): **one**
  metadata annotation, a point at time 0, body ``annot://schema/lrc-tags/v1``
  ``{"tags": [{"key": str, "value": str}, ...]}``, every ID tag in file order
  with its key and value exactly as written (``[length: 3:20]`` keeps the value
  ``" 3:20"``). :func:`dump` writes these tags back verbatim, one per row. They
  live on one annotation rather than in every line body because they describe
  the file, not a line, and so that a store from another format (SubRip,
  WebVTT) dumps without inventing any.

End times (LRC has none):
    A line ends where the next *later* line starts (lines sharing a start, as
    in bilingual files, all end at the next later start). The last line ends
    at ``[length:]`` when the file gives one at or after its start, else it is
    a point (``start == end``); a ``[length:]`` before the last line is only a
    hint and is ignored. A word ends at the next word stamp of its line, or,
    for the last word, at its line's end (a point when that end is before the
    word starts, as in a last line that is itself a point). When a line has
    several time tags, its word stamps (absolute times) are read once, against
    the latest of those tags at or before the first word stamp (the first tag
    if none). That line is then widened to hold its words, since the words
    tier is ``INCLUDED_IN`` the lines tier: it starts at its first word when
    that word is stamped before the line's tag, and it ends at its last word
    when that word is sung past the next line's start (karaoke files do both).
    A widened line overlaps its neighbours.

Offset:
    ``[offset:+/-ms]`` shifts every line and word time; ``+`` makes lyrics
    appear *sooner*, so a time is the tag minus the offset. The primary source
    is ffmpeg's LRC demuxer (``libavformat/lrcdec.c``:
    ``sub->pts = ts_start - lrc->ts_offset``); Wikipedia agrees
    (https://en.wikipedia.org/wiki/LRC_(file_format): "with ``+`` causing
    lyrics to appear sooner"). It applies to the whole file wherever the tag
    stands; ``[length:]`` is a media duration and is not shifted; an empty
    ``[offset:]`` is 0. A time the offset makes negative (``[offset:+500]``
    with a ``[00:00.00]Artist - Title`` line, a common file) is clamped to 0
    where ffmpeg lets the negative time through; the clamped time is **not
    exact**, and it dumps as the offset itself (``[00:00.50]``). On dump the
    offset tag is written back and the times are shifted back by it, so a file
    with an offset round-trips.

Time discipline:
    Tags are ``[mm:ss.xx]`` or ``[mm:ss.xxx]`` (``.``, ``,`` or ``:`` before
    the fraction; one to three fraction digits are read as a decimal fraction
    of a second, and ``[mm:ss]`` is a whole second). Every time is parsed as
    integer milliseconds and converted exactly to ``RationalTime`` at ``rate``
    (default 1000; it must hold a millisecond, or loading raises
    ``LossyTimeConversionError``), via :mod:`lacing.adapters._cues`. No float
    is involved. :func:`dump` writes centiseconds by default
    (``precision="cs"``, ``[mm:ss.xx]``, what LRC players expect) or
    milliseconds (``precision="ms"``). Finer times are **truncated** (the
    floor, for the non-negative times LRC holds): truncation is monotone, so
    written lines and word stamps keep their order.

Lossy fields on dump:
    End times are not written (except that ``[length:]`` tags pass through,
    and a word's end is stamped when it is not implied), so a line's end
    becomes the next line's start (or its last word's end); gaps between lines
    are lost. Provenance, confidence, schema URIs and tier metadata are
    dropped. A line's text, and a word's, is written on one line: a multi-line
    text (a SubRip cue) has its lines joined by a space, blank ones dropped.
    By default (``tier=None``) the lines are the ``lines`` tier when the store
    has text annotations on it, and otherwise every annotation with a time
    interval and a ``text`` body on any tier but the words tier, so SubRip and
    WebVTT cues dump to LRC. Word annotations on the words tier become word
    stamps in the line that holds them (among the lines whose interval
    contains the word, the one starting latest); a word no line holds is
    dropped, and so is a word the line's text does not contain (in order):
    the line's text is always written as it is, never replaced by its words.
    Text between two words is read back as part of the earlier word, and text
    before the first word as a word of its own. A word overlapping the next
    one is cut at the next word's start. A line text that itself starts with
    a ``[mm:ss.xx]`` clock reads back as another time tag.

Lenient input, as ffmpeg's demuxer is: a line with no leading time tag or ID
tag (stray text, a bare ``[Chorus]``) is skipped; after a line's first time
tag, the first bracket that is not a clock (``[00:01.00][2x] la``) starts the
text; several ID tags may share a line (``[ar:A][ti:T]``). Malformed input
raises ``ValueError`` naming the line number: a line whose first bracket
claims to be a time (``[`` digits ``:``) but is not a valid clock; a bad word
stamp; a bad ``[offset:]`` or ``[length:]`` value, or either tag twice; text
after ID tags; word stamps going backwards.
"""

from __future__ import annotations

import os
import re
from bisect import bisect_right
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any
from uuid import uuid4

from lacing.adapters import adapter_generator_id, register_adapter
from lacing.adapters._common import display_text, iter_with_intervals, read_text
from lacing.adapters._cues import (
    MS_PER_MINUTE,
    MS_PER_SECOND,
    assign_words,
    cue_payload,
    hms_to_ms,
    ms_to_rational,
    nonnegative_ms,
    place_words,
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
FORMAT_NAME = "LRC"

_FRACTION_DIGITS = {"cs": 2, "ms": 3}
_MS_PER_CS = 10

_CLOCK = r"(\d+):([0-5]?\d)(?:[.,:](\d{1,3}))?"
_CLOCK_RE = re.compile(rf"^{_CLOCK}$", re.ASCII)
_LEADING_TAG_RE = re.compile(r"\[([^\]]*)\]")
_ID_TAG_RE = re.compile(r"^([A-Za-z#][\w#-]*):(.*)$", re.ASCII | re.DOTALL)
# A line whose first bracket claims to be a time: "[" digits ":" (any digits,
# so a full-width "[００:01]" claims one too, and then fails as malformed).
_CLAIMS_TIME_TAG_RE = re.compile(r"^\[\s*[-+]?\d+\s*:")
# What claims to be a word stamp: "<" digits ":" ... ">". Its inside must then
# be a valid clock; "<3" and other angle brackets in lyrics are plain text.
_WORD_STAMP_RE = re.compile(r"<(\d+:[^<>]*)>", re.ASCII)
_OFFSET_RE = re.compile(r"^\s*([+-]?\d+)\s*$", re.ASCII)


# ---------------------------------------------------------------------------
# parsing helpers
# ---------------------------------------------------------------------------


def _clock_to_ms(clock: str) -> int | None:
    """Milliseconds of an ``mm:ss[.xx]`` clock, ``None`` if it is not one.

    >>> _clock_to_ms("01:02.5"), _clock_to_ms("01:02:05"), _clock_to_ms("0:02,005")
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


def _id_tags(line: str, *, line_no: int) -> list[tuple[str, str]] | None:
    """The ``(key, value)`` ID tags ``line`` consists of (``[ar:A][ti:T]``),
    or None when it does not start with one."""
    tags: list[tuple[str, str]] = []
    rest = line
    while (m := _LEADING_TAG_RE.match(rest)) and (t := _ID_TAG_RE.match(m.group(1))):
        tags.append((t.group(1), t.group(2)))
        rest = rest[m.end() :].lstrip()
    if tags and rest:
        raise ValueError(f"line {line_no}: text after the ID tag {line!r}")
    return tags or None


def _time_row(line: str, *, line_no: int) -> _Row:
    """The row of a line starting with a time tag: its leading clocks, up to
    the first bracket that is not one (``[2x]``, ``[Chorus]``), then text."""
    tag_ms: list[int] = []
    pos = 0
    while (m := _LEADING_TAG_RE.match(line, pos)) is not None:
        ms = _clock_to_ms(m.group(1))
        if ms is None:
            break
        tag_ms.append(ms)
        pos = m.end()
    if not tag_ms:
        first = _LEADING_TAG_RE.match(line)
        what = f"[{first.group(1)}]" if first else f"(no closing bracket) in {line!r}"
        raise ValueError(f"line {line_no}: malformed LRC time tag {what}")
    plain, segments = _parse_segments(line[pos:], line_no=line_no)
    return _Row(line_no, tuple(tag_ms), plain, segments)


def _iter_lines(text: str) -> Iterator[tuple[int, str, Any]]:
    """Yield ``(line_no, "row", _Row)`` or ``(line_no, "tag", (key, value))``
    for each line of ``text`` that has a time tag or ID tags; skip the rest
    (blank lines, stray text, a bare ``[Chorus]``), as ffmpeg's lrcdec does."""
    for line_no, line in enumerate(split_cue_lines(text), start=1):
        stripped = line.strip()
        if (tags := _id_tags(stripped, line_no=line_no)) is not None:
            for tag in tags:
                yield line_no, "tag", tag
        elif _CLAIMS_TIME_TAG_RE.match(stripped):
            yield line_no, "row", _time_row(stripped, line_no=line_no)


def _parse_offset(value: str, *, where: str) -> int:
    if not value.strip():
        return 0  # an empty "[offset:]"
    m = _OFFSET_RE.match(value)
    if m is None:
        raise ValueError(f"{where}: malformed LRC [offset:] value {value!r}")
    return int(m.group(1))


def _parse_length(value: str, *, where: str) -> int | None:
    if not value.strip():
        return None  # an empty "[length:]"
    ms = _clock_to_ms(value.strip())
    if ms is None:
        raise ValueError(f"{where}: malformed LRC [length:] value {value!r}")
    return ms


@dataclass(frozen=True, slots=True)
class _Parsed:
    rows: list[_Row]
    tags: list[tuple[str, str]]
    offset_ms: int
    length_ms: int | None


def _parse(text: str) -> _Parsed:
    rows: list[_Row] = []
    tags: list[tuple[str, str]] = []
    special: dict[str, int | None] = {}
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
            special[lowered] = parse(value, where=f"line {line_no}")
    if not rows and not tags and text.strip():
        raise ValueError(
            "no LRC time tag or ID tag in the input: not an LRC file "
            "(stray lines are skipped, but a file of nothing else is refused)"
        )
    return _Parsed(rows, tags, special.get(OFFSET_KEY) or 0, special.get(LENGTH_KEY))


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------


def _effective_ms(tag_ms: int, offset_ms: int) -> int:
    """The time of a tag or stamp: minus the offset ("+" makes lyrics appear
    sooner, as in ffmpeg's lrcdec), clamped to 0."""
    return max(0, tag_ms - offset_ms)


def _line_ends(starts: list, length: Any = None) -> list:
    """End of each line (``starts`` sorted): the next later start, then
    ``length`` (None, a point, without it). Works on any ordered times."""
    distinct = sorted(set(starts))
    ends = []
    for s in starts:
        i = bisect_right(distinct, s)
        ends.append(distinct[i] if i < len(distinct) else length)
    return ends


def _words_of(
    row: _Row, occurrences: list[tuple[int, int]], offset_ms: int
) -> tuple[int, list[tuple[str, int, int]]]:
    """``(anchor, words)`` of an enhanced ``row``: the index, in
    ``occurrences`` (the row's ``(start_ms, end_ms)`` lines, sorted), of the
    line its stamps are read against, and ``(text, start_ms, end_ms)`` of each
    word."""
    assert row.segments is not None
    first_stamp = next(
        _effective_ms(ms, offset_ms) for ms, _ in row.segments if ms is not None
    )
    anchor = 0
    for k, occ in enumerate(occurrences):
        if occ[0] <= first_stamp:
            anchor = k
    line_start, line_end = occurrences[anchor]
    times = [
        line_start if ms is None else _effective_ms(ms, offset_ms)
        for ms, _ in row.segments
    ]
    if any(b < a for a, b in zip(times, times[1:])):
        raise ValueError(f"line {row.line_no}: LRC word stamps go backwards")
    words: list[tuple[str, int, int]] = []
    for i, ((_, seg), start) in enumerate(zip(row.segments, times)):
        word = seg.strip()
        if not word:
            continue  # a stamp followed by blanks only ends the previous word
        end = times[i + 1] if i + 1 < len(times) else max(line_end, start)
        words.append((word, start, end))
    return anchor, words


def _read_words(
    lines: list[tuple[int, _Row]], spans: list[tuple[int, int]], offset_ms: int
) -> list[tuple[str, int, int]]:
    """The words of every enhanced line, widening ``spans`` (in place) so
    that the line each row's words are read against holds them."""
    by_row: dict[int, list[int]] = {}
    for i, (_, row) in enumerate(lines):
        by_row.setdefault(row.line_no, []).append(i)
    words: list[tuple[str, int, int]] = []
    for indices in by_row.values():
        row = lines[indices[0]][1]
        if row.segments is None:
            continue
        anchor, row_words = _words_of(row, [spans[i] for i in indices], offset_ms)
        if row_words:
            i = indices[anchor]
            start, end = spans[i]
            spans[i] = (min(start, row_words[0][1]), max(end, row_words[-1][2]))
            words.extend(row_words)
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
    encoding: str | None = None,
    **_kwargs: Any,
) -> IntervalAnnotationStore:
    """Parse an LRC file, or LRC bytes or text, into a ``MemoryStore``.

    Lines go on ``tier``, word stamps on ``words_tier``, ID tags on one
    annotation on ``tags_tier`` (see the module docstring for end times and
    the offset sign).

    Args:
        source: Bytes (UTF-8, BOM tolerated), a path, or inline text. A
            ``str`` naming an existing file is read from it (even one named
            ``"[Group] Song.lrc"``); any other ``str`` is inline text.
        rate: Rate of every ``RationalTime`` produced; must hold a millisecond.
        asset_id: The ``MediaRef.asset_id`` the lyrics annotate.
        attribution: ``Provenance.was_attributed_to`` of every annotation.
        tier: Name of the lines tier.
        words_tier: Name of the words tier (created only for enhanced LRC).
        tags_tier: Name of the ID-tag tier (created only when there are tags).
        encoding: Text encoding of a file or of bytes. ``None`` sniffs a BOM
            (UTF-8, UTF-16, UTF-32) and otherwise reads UTF-8; name one
            (``"cp1252"``) for a file without a BOM.

    Raises:
        ValueError: On malformed input, naming the line number.
    """
    parsed = _parse(read_text(source, encoding=encoding))
    offset = parsed.offset_ms

    # (start_ms, row) per time tag, sorted by start; file order breaks ties.
    lines = sorted(
        ((_effective_ms(ms, offset), row) for row in parsed.rows for ms in row.tag_ms),
        key=lambda pair: pair[0],
    )
    length_ms = parsed.length_ms
    if lines and length_ms is not None and length_ms < lines[-1][0]:
        length_ms = None  # a hint only: the last line becomes a point
    ends = _line_ends([s for s, _ in lines], length_ms)
    spans = [(s, s if e is None else e) for (s, _), e in zip(lines, ends)]
    words = _read_words(lines, spans, offset)

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
    shifted = RationalTime(written.numerator, written.denominator)
    ms = nonnegative_ms(shifted, format_name=FORMAT_NAME)
    minutes, rem = divmod(ms, MS_PER_MINUTE)
    seconds, millis = divmod(rem, MS_PER_SECOND)
    if precision == "cs":
        return f"{minutes:02d}:{seconds:02d}.{millis // _MS_PER_CS:02d}"
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"


def _line_text(body: Any) -> str | None:
    """A body's :func:`display_text` on one physical line; ``None`` if it has none."""
    text = display_text(body)
    if text is None:
        return None
    return " ".join(split_cue_lines(cue_payload(text)))


@dataclass(frozen=True, slots=True)
class _Timed:
    """A line or word to write: its interval, exact bounds, one-line text."""

    tier: str
    interval: TimeInterval
    start: Fraction
    end: Fraction
    text: str


def _timed(a: Annotation) -> _Timed | None:
    text = _line_text(a.body)
    iv = a.interval
    if text is None or iv is None:
        return None
    return _Timed(a.tier, iv, iv.start.to_fraction(), iv.end.to_fraction(), text)


def _stamped_text(
    text: str,
    words: list[_Timed],
    stamp: Callable[[RationalTime], str],
    *,
    line_end: Fraction | None,
) -> str:
    """``text`` with a ``<stamp>`` before each word it contains, and an end
    stamp after a word (and the text that follows it) whose end is not where
    loading would put it: the next word's start, or, for the last word, the
    later of ``line_end`` (the next later line's start) and its own start,
    always stamped when ``line_end`` is None. A word running past the next
    word's start is cut there."""
    placed = place_words(text, words)
    if not placed:
        return text
    out = [text[: placed[0][1]]]
    for i, (w, pos) in enumerate(placed):
        out.append(f"<{stamp(w.interval.start)}>{w.text}")
        nxt = placed[i + 1][1] if i + 1 < len(placed) else len(text)
        out.append(text[pos + len(w.text) : nxt])  # read back as part of w
        if i + 1 < len(placed):
            needs_end = w.end < placed[i + 1][0].start
        else:
            # with no later line, loading would end it at [length:] if any
            needs_end = line_end is None or w.end != max(line_end, w.start)
        if needs_end:
            out.append(f"<{stamp(w.interval.end)}>")
    return "".join(out)


def _tags_to_write(annotations: list[Annotation]) -> list[tuple[str, str]]:
    return [
        (t["key"], t["value"])
        for a in annotations
        if a.body_schema_uri == TAGS_BODY_SCHEMA_URI and isinstance(a.body, dict)
        for t in a.body.get("tags", [])
    ]


def _offset_to_write(tags: list[tuple[str, str]]) -> int:
    offsets = [v for k, v in tags if k.lower() == OFFSET_KEY]
    if len(offsets) > 1:
        raise ValueError(f"more than one [{OFFSET_KEY}:] tag to write: {offsets}")
    return _parse_offset(offsets[0], where="lrc-tags body") if offsets else 0


def _is_line_tier(texts: list[_Timed], *, tier: str | None, words_tier: str):
    """The test a text's tier passes to be written as a line."""
    if tier is not None:
        return lambda name: name == tier and name != words_tier
    if any(t.tier == DEFAULT_TIER_NAME for t in texts):
        return lambda name: name == DEFAULT_TIER_NAME
    return lambda name: name != words_tier


def _by_interval(t: _Timed) -> tuple[Fraction, Fraction]:
    return (t.start, t.end)


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
        store: Source store. Lines are annotations with a time interval and a
            ``text`` body (an LRC line, a SubRip or WebVTT cue, or any other).
        target: Output path. If None, returns bytes (UTF-8, no BOM, ``\\n``).
        tier: The tier whose texts are the lines. None (the default) means the
            ``lines`` tier when the store has text annotations on it (so a
            phones or notes tier beside it is not written as lyrics), and
            otherwise every tier but ``words_tier``.
        words_tier: Tier whose annotations are written as word stamps.
        precision: ``"cs"`` (``[mm:ss.xx]``, default) or ``"ms"``
            (``[mm:ss.xxx]``); finer times are truncated.
    """
    if precision not in _FRACTION_DIGITS:
        raise ValueError(f"precision must be one of {sorted(_FRACTION_DIGITS)}")
    annotations = list(iter_with_intervals(store))
    tags = _tags_to_write(annotations)
    offset = _offset_to_write(tags)

    def stamp(t: RationalTime) -> str:
        return _format_clock(t, offset_ms=offset, precision=precision)

    texts = [t for a in annotations if (t := _timed(a)) is not None]
    is_line = _is_line_tier(texts, tier=tier, words_tier=words_tier)
    lines = sorted((t for t in texts if is_line(t.tier)), key=_by_interval)
    words = sorted(
        (t for t in texts if t.tier == words_tier and t.text), key=_by_interval
    )
    words_by_line = assign_words(lines, words)
    next_starts = _line_ends([line.start for line in lines])

    rows = [f"[{key}:{value}]" for key, value in tags]
    for i, line in enumerate(lines):
        text = line.text
        if i in words_by_line:
            text = _stamped_text(text, words_by_line[i], stamp, line_end=next_starts[i])
        rows.append(f"[{stamp(line.interval.start)}]{text}")

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
