"""ASS / SSA (Advanced SubStation Alpha) subtitle adapter, with karaoke timing.

An ASS file is a set of ``[Section]`` blocks; the timed text is in ``[Events]``,
whose ``Format:`` line names the comma-separated fields of each event, the
text field last (so the text may hold commas)::

    [Script Info]
    ScriptType: v4.00+
    PlayResX: 1920

    [V4+ Styles]
    Format: Name, Fontname, Fontsize, PrimaryColour, ...
    Style: Default,Arial,48,&H00FFFFFF,...

    [Events]
    Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
    Dialogue: 0,0:00:01.00,0:00:03.50,Default,,0,0,0,,Hello, {\\i1}world{\\i0}\\Nline two
    Dialogue: 0,0:00:04.00,0:00:06.00,Karaoke,,0,0,0,,{\\k50}Ka{\\kf40}ra{\\ko60}o{\\k50}ke
    Comment: 0,0:00:07.00,0:00:08.00,Default,,0,0,0,,a note, not shown

Tiers and bodies (the ``lines``/``words`` names of lacing's lyric tracks,
:mod:`lacing.tracks.subtitle`, so ASS, LRC, SubRip and WebVTT convert into one
another out of the box):

- ``lines`` (stereotype ``NONE``): one annotation per ``Dialogue`` event,
  body ``annot://schema/ass-event/v1``::

      {"text": str, "raw": str, "style": str, "fields": {name: str}, "index": int}

  ``raw`` is the text field verbatim, override tags and all; ``text`` is what
  it reads as: override blocks ``{...}`` removed, ``\\N`` and ``\\n`` as a
  newline, ``\\h`` as a no-break space (U+00A0), and a vector drawing (the
  text between ``{\\p1}``, any ``\\p<n>`` with ``n > 0``, and ``{\\p0}``) as
  nothing, so a drawing-only event has an empty ``text``. ``style`` is the
  ``Style`` field. ``fields`` holds every other field of the event (``Layer``, ``Name``,
  ``MarginL``, ``MarginR``, ``MarginV``, ``Effect``, or ``Marked`` in SSA)
  verbatim, keyed by its name in the ``Format:`` line. ``index`` is the
  event's position in ``[Events]`` (dialogues and comments counted together),
  which :func:`dump` uses to write events back in file order, since a
  renderer resolves collisions in that order.
  **One tier for all styles, the style in the body**, rather than one tier per
  style: ASS styles are presentation, events of one style overlap freely, and
  one lines tier lets the words tier be ``INCLUDED_IN`` a single parent.
- ``words`` (stereotype ``INCLUDED_IN`` ``lines``, only when some dialogue has
  karaoke tags): one annotation per karaoke syllable, body
  ``annot://schema/ass-syllable/v1``
  ``{"text": str, "karaoke": "k" | "K" | "kf" | "ko", "event": int,
  "ordinal": int}``.
  ``text`` is the syllable's text (what follows its tag up to the next
  karaoke tag), stripped of blanks; ``karaoke`` the tag that timed it;
  ``event`` the ``index`` of its line; ``ordinal`` its place among that
  line's syllables (from 0), which :func:`dump` writes them back in, since
  times tie (``{\\k0}``, syllables cut at the event's end) and ``\\kt`` can
  move a later syllable before an earlier one. A word body without
  ``ordinal`` (another source's) is ordered by time. A syllable whose text
  is blank (a lead-in ``{\\k50}`` pause, or ``{\\k20} ``) is a gap, not a word.
- ``comments`` (stereotype ``NONE``, only when the file has some): one
  annotation per ``Comment`` event, with the same body as a dialogue. Comment
  events are not shown by a renderer; they are kept (on their own tier, so
  that they are flagged and other formats' writers can leave them out with
  ``tier=``), and their karaoke tags are not read as syllables (Aegisub's
  karaoke templater comments out the timed originals).
- ``script`` (stereotype ``NONE``): **one** metadata annotation, a point at
  time 0, body ``annot://schema/ass-script/v1``::

      {"sections": [{"name": str | None, "lines": [str]}],
       "events": {"name": str, "position": int, "format": [str], "lines": [str]}}

  Every section but ``[Events]`` (``[Script Info]``, ``[V4+ Styles]`` or
  ``[V4 Styles]``, ``[Fonts]``, ``[Graphics]``, ``[Aegisub Project Garbage]``,
  anything else) with its non-blank lines verbatim, in file order (a ``None``
  name holds lines before the first header); where ``[Events]`` stood among
  them; its ``Format:`` field names; and its other lines (``;`` comments,
  ``Picture:``, ``Sound:``, ``Movie:``, ``Command:``) verbatim. :func:`dump`
  writes all of this back. Inside ``[Fonts]`` and ``[Graphics]`` a bracketed
  line made only of uuencode characters is data, not a section header,
  unless it names a known section (``[EVENTS]``, ``[Script Info]``, a styles
  section, ``[Fonts]``, ``[Graphics]``, in any case). ``load(keep_sections=)``
  keeps only the named sections: ``[Fonts]``/``[Graphics]`` can be megabytes
  and ``[Aegisub Project Garbage]`` holds local file paths.

Karaoke:
    ``{\\k<cs>}``, ``{\\K<cs>}`` (= ``\\kf``), ``{\\kf<cs>}`` and ``{\\ko<cs>}``
    each start a syllable lasting ``<cs>`` centiseconds; syllables follow one
    another from the event start, so a syllable's start is the event start
    plus the durations before it, exactly. ``{\\kt<cs>}`` moves the start of
    the next syllable to ``<cs>`` after the event start (libass 0.17+). A
    decimal duration (``\\k12.5``) is read exactly too. A tag with no value
    (``{\\k}``) lasts 100 centiseconds (``\\kt``: 0), as in libass; a
    negative or malformed one raises, naming the line. A syllable that runs
    past its event's end is cut at the end (one that starts at or after it
    becomes a point there), so the words tier stays ``INCLUDED_IN`` the
    lines tier; its tag stays in ``raw``.

Time discipline:
    Event times are strictly ``H:MM:SS.cc``: exactly two centisecond digits,
    minutes and seconds below 60, so ``0:00:01.5`` and ``0:60:00.00`` raise
    (libass is laxer). They are integer centiseconds, read as integers and
    converted exactly to ``RationalTime`` at ``rate`` (default 1000; ``rate``
    must hold the times exactly, a centisecond and any decimal karaoke
    duration, or loading raises ``LossyTimeConversionError`` naming the
    line). No float is
    involved. :func:`dump` writes centiseconds: a finer time is **truncated**
    to the centisecond (the floor, for the non-negative times ASS holds), and
    karaoke durations are differences of truncated times, so truncation is
    monotone (every event keeps ``start <= end``, syllables keep their order
    and never get a negative duration) and the times read back are exactly the
    truncated ones. A negative time raises ``ValueError``.

dump:
    Writes ``[Script Info]``, a styles section and ``[Events]`` from the
    script metadata when the store has it (``script_info=`` when it has no
    ``[Script Info]``, ``default_style=``, Aegisub's ``Default``, when there
    are no styles, and ``event_format=`` when it has no ``[Events]`` format),
    then one ``Dialogue:`` per line and one ``Comment:`` per
    comment, ASS events in their ``index`` order, others after them by time.
    Any annotation with a time interval and a ``text`` body can be a line
    (by default the ``lines`` tier when it has text annotations, otherwise
    every top-level tier but the words and comments tiers, as the SubRip and
    WebVTT writers choose), so SubRip, WebVTT
    and LRC cues dump to ASS, their newlines written as ``\\N``. A line whose
    ``raw`` still reads as its ``text`` is written from ``raw``, override tags
    kept; when the ``text`` was edited, the ``text`` wins and the tags are
    lost. Karaoke tags come from the word annotations inside a line (an ASS
    syllable goes back to its own event; any other word, an LRC word stamp
    for one, to the latest-starting line that holds it in time and in text,
    the rule LRC uses): when they are the syllables ``raw`` already encodes,
    ``raw`` is written as is; otherwise ``raw``'s karaoke tags are replaced
    by ``{\\k..}`` tags (the word's own ``karaoke`` kind, ``k`` by default)
    placed before each word found in the text, in order, with an empty
    ``{\\k..}`` filling a gap before a word and a word cut at the next one's
    start. The text is never replaced by its words.

Lossy fields on dump:
    Provenance, confidence, schema URIs and tier metadata are dropped. Blank
    lines are not kept, and a ``Format:`` line is written with ``", "``
    between names; ``[Events]`` lines other than events are written after its
    ``Format:`` line; an event field not in the target ``Format:`` is dropped
    (a missing one is written as Aegisub writes it empty: ``0`` for layer and
    margins, empty otherwise). A word no line holds, or one not found in its
    line's text, is dropped; text between two words reads back as part of
    the earlier one. ASS has no escape: a ``{...}`` or a ``\\N``, ``\\n``,
    ``\\h`` in a plain text (a SubRip ``{\\an8}``, say) is written through and
    reads back as an override block or a break. A comma or line break in a
    non-text field, or a line break in ``raw``, cannot be written and raises
    ``ValueError``.

Malformed input raises ``ValueError`` naming the line number: a line in
``[Events]`` that is not ``Key: value`` or a ``;`` comment, a second or late
``Format:`` line, a ``Format:`` without ``Start``, ``End`` or ``Text`` last, an
event with too few fields, a bad time, an event ending before it starts, a
bad karaoke duration. Input with no ``[Events]`` section is not ASS and raises
too (an empty input included). ``[Events]`` without a ``Format:`` line uses
the default one (with ``Layer``; with ``Marked`` under ``[V4 Styles]``), as
libass does, and :func:`dump` then writes it.

Sources: the format specification "Sub Station Alpha v4.00+ Script Format"
(http://www.tcax.org/docs/ass-specs.htm), Aegisub's override-tag reference
(https://aegisub.org/docs/latest/ass_tags/, for ``\\k``, ``\\K``, ``\\kf``,
``\\ko``, ``\\N``, ``\\n``, ``\\h``), and libass's reader
(https://github.com/libass/libass, ``libass/ass.c`` and
``libass/ass_parse.c``) for what real files do.
"""

from __future__ import annotations

import os
import re
from bisect import bisect_right
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any
from uuid import uuid4

from lacing.adapters import adapter_generator_id, register_adapter
from lacing.adapters._common import import_provenance, iter_with_intervals, read_text
from lacing.adapters._cues import (
    MS_PER_SECOND,
    assign_words,
    nonnegative_ms,
    place_words,
    select_cue_annotations,
    split_cue_lines,
)
from lacing.model import Annotation, MediaRef, Provenance
from lacing.store import IntervalAnnotationStore, MemoryStore
from lacing.tier import Tier, TierStereotype
from lacing.time import LossyTimeConversionError, RationalTime, TimeInterval
from lacing.tracks.subtitle import LINES_TIER, WORDS_TIER

ADAPTER_NAME = "ass"
ADAPTER_VERSION = "1.0.0"
GENERATED_BY = str(adapter_generator_id(ADAPTER_NAME, ADAPTER_VERSION))
EVENT_BODY_SCHEMA_URI = "annot://schema/ass-event/v1"
SYLLABLE_BODY_SCHEMA_URI = "annot://schema/ass-syllable/v1"
SCRIPT_BODY_SCHEMA_URI = "annot://schema/ass-script/v1"
DEFAULT_TIER_NAME = LINES_TIER
DEFAULT_WORDS_TIER_NAME = WORDS_TIER
DEFAULT_COMMENTS_TIER_NAME = "comments"
DEFAULT_SCRIPT_TIER_NAME = "script"
DEFAULT_RATE = 1000
DEFAULT_ASSET_ID = "ass:unspecified"
EXTENSIONS = (".ass", ".ssa")
MEDIA_TYPE = "text/x-ssa"
FORMAT_NAME = "ASS"

CS_PER_SECOND = 100
_MS_PER_CS = MS_PER_SECOND // CS_PER_SECOND
_CS_PER_MINUTE = 60 * CS_PER_SECOND
_CS_PER_HOUR = 60 * _CS_PER_MINUTE

EVENTS_SECTION = "Events"
SCRIPT_INFO_SECTION = "Script Info"
STYLES_SECTION = "V4+ Styles"
_SSA_STYLES_SECTION = "v4 styles"
_STYLES_SECTIONS = {STYLES_SECTION.lower(), _SSA_STYLES_SECTION, "v4++ styles"}
_BINARY_SECTIONS = {"fonts", "graphics"}
# Headers always read as headers, even inside [Fonts]/[Graphics] data (where an
# all-caps "[EVENTS]" is also made of uuencode characters).
_KNOWN_SECTIONS = {
    EVENTS_SECTION.lower(),
    SCRIPT_INFO_SECTION.lower(),
    *_STYLES_SECTIONS,
    *_BINARY_SECTIONS,
}
DIALOGUE, COMMENT = "Dialogue", "Comment"

DEFAULT_EVENT_FORMAT = (
    "Layer",
    "Start",
    "End",
    "Style",
    "Name",
    "MarginL",
    "MarginR",
    "MarginV",
    "Effect",
    "Text",
)
SSA_EVENT_FORMAT = ("Marked", *DEFAULT_EVENT_FORMAT[1:])
# How Aegisub writes an event field left empty (lowercased names); "" otherwise.
_EVENT_FIELD_DEFAULTS = {
    "layer": "0",
    "marked": "Marked=0",
    "marginl": "0",
    "marginr": "0",
    "marginv": "0",
}
DEFAULT_STYLE_FORMAT = (
    "Name",
    "Fontname",
    "Fontsize",
    "PrimaryColour",
    "SecondaryColour",
    "OutlineColour",
    "BackColour",
    "Bold",
    "Italic",
    "Underline",
    "StrikeOut",
    "ScaleX",
    "ScaleY",
    "Spacing",
    "Angle",
    "BorderStyle",
    "Outline",
    "Shadow",
    "Alignment",
    "MarginL",
    "MarginR",
    "MarginV",
    "Encoding",
)
DEFAULT_STYLE_NAME = "Default"
# Aegisub's "Default" style (lowercased field names); "0" for any other field.
DEFAULT_STYLE = {
    "name": DEFAULT_STYLE_NAME,
    "fontname": "Arial",
    "fontsize": "20",
    "primarycolour": "&H00FFFFFF",
    "secondarycolour": "&H000000FF",
    "outlinecolour": "&H00000000",
    "tertiarycolour": "&H00000000",
    "backcolour": "&H00000000",
    "scalex": "100",
    "scaley": "100",
    "borderstyle": "1",
    "outline": "2",
    "shadow": "2",
    "alignment": "2",
    "marginl": "10",
    "marginr": "10",
    "marginv": "10",
    "encoding": "1",
}
DEFAULT_SCRIPT_INFO = ("; Script generated by lacing", "ScriptType: v4.00+")
KARAOKE_KINDS = ("k", "K", "kf", "ko")
_DEFAULT_KARAOKE = "k"
_KARAOKE_RESET = "kt"

_HEADER_RE = re.compile(r"^\[(.+)\]$")
_UUENCODED_RE = re.compile(r"^[!-`]+$")  # uuencode's alphabet, chars 33..96
_KEY_VALUE_RE = re.compile(r"^([A-Za-z]+)\s*:\s*(.*)$", re.DOTALL)
_FORMAT_KEY_RE = re.compile(r"^\s*Format\s*:", re.IGNORECASE)
_STYLE_KEY_RE = re.compile(r"^\s*Style\s*:", re.IGNORECASE)
_TIME_RE = re.compile(r"^\s*(\d+):([0-5]?\d):([0-5]?\d)\.(\d\d)\s*$", re.ASCII)
_TOKEN_RE = re.compile(r"(\{[^}]*\})|\\([Nnh])|([^{\\]+|.)", re.DOTALL)
_ESCAPES = {"N": "\n", "n": "\n", "h": " "}
_KARAOKE_TAG_RE = re.compile(r"\\(kf|ko|kt|k|K)([^\\]*)")
_KARAOKE_VALUE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)", re.ASCII)
_KARAOKE_DEFAULT_CS = 100  # libass: a ``\k`` with no value lasts a second
# ``\p<scale>`` (drawing mode), not ``\pos(`` or ``\pbo``; no digits is scale 0.
_DRAWING_TAG_RE = re.compile(r"\\p(?!os|bo)\s*(-?\d+)?", re.ASCII)


# ---------------------------------------------------------------------------
# text: tokens, plain text, karaoke syllables
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Token:
    """A piece of an event's text: an override block, an escape, or a run."""

    raw: str
    plain: str
    block: str | None = None  # the inside of an override block
    is_run: bool = False  # plain text, one raw character per plain character


def _drawing_after(block: str, drawing: bool) -> bool:
    """Whether drawing mode is on after the override block ``block``: the last
    ``\\p<n>`` in it decides (``n > 0`` on; ``0``, negative or none off)."""
    scales = _DRAWING_TAG_RE.findall(block)
    if not scales:
        return drawing
    return int(scales[-1] or 0) > 0


def _tokens(raw: str) -> list[_Token]:
    """``raw`` cut into override blocks, ``\\N``/``\\n``/``\\h`` escapes and
    plain runs. An unclosed ``{`` and any other backslash are plain text.
    Between ``{\\p1}`` (any ``\\p<n>``, ``n > 0``) and ``{\\p0}``, text is a
    vector drawing, not words: its runs and escapes read as nothing."""
    out: list[_Token] = []
    drawing = False
    for m in _TOKEN_RE.finditer(raw):
        block, escape, run = m.groups()
        if block is not None:
            out.append(_Token(block, "", block[1:-1]))
            drawing = _drawing_after(block[1:-1], drawing)
        elif drawing:
            out.append(_Token(m.group(0), ""))
        elif escape is not None:
            out.append(_Token(m.group(0), _ESCAPES[escape]))
        else:
            out.append(_Token(run, run, is_run=True))
    return out


def plain_text(raw: str) -> str:
    """What an ASS text reads as: override blocks removed, ``\\N`` and ``\\n``
    as a newline, ``\\h`` as a no-break space, a ``\\p`` drawing as nothing.

    >>> plain_text(r"Hello, {\\i1}world{\\i0}\\Nline\\htwo")
    'Hello, world\\nline\\xa0two'
    >>> plain_text(r"{\\p1}m 0 0 l 100 0 100 100{\\p0}Sign")
    'Sign'
    """
    return "".join(t.plain for t in _tokens(raw))


def _karaoke_cs(arg: str, *, kind: str, where: str) -> Fraction:
    """A karaoke tag's centiseconds, exactly; a blank one is libass's default
    (100 for a syllable, 0 for ``\\kt``)."""
    if not arg.strip():
        return Fraction(0 if kind == _KARAOKE_RESET else _KARAOKE_DEFAULT_CS)
    m = _KARAOKE_VALUE_RE.match(arg)
    if m is None:
        raise ValueError(f"{where}: malformed karaoke duration {arg!r}")
    return Fraction(m.group(1))  # exact: from the decimal string


@dataclass(frozen=True, slots=True)
class _Syllable:
    """A karaoke syllable, its times in centiseconds from the event start."""

    kind: str
    start: Fraction
    end: Fraction
    text: str


def _syllables(tokens: list[_Token], *, where: str) -> list[_Syllable]:
    """The non-blank karaoke syllables of an event's text, in order."""
    out: list[_Syllable] = []
    cursor = Fraction(0)
    current: tuple[str, Fraction, Fraction] | None = None
    texts: list[str] = []

    def close() -> None:
        text = "".join(texts).strip()
        if current is not None and text:
            out.append(_Syllable(*current, text))
        texts.clear()

    for token in tokens:
        if token.block is None:
            texts.append(token.plain)
            continue
        for m in _KARAOKE_TAG_RE.finditer(token.block):
            kind = m.group(1)
            cs = _karaoke_cs(m.group(2), kind=kind, where=where)
            if kind == _KARAOKE_RESET:
                cursor = cs
                continue
            close()
            current = (kind, cursor, cursor + cs)
            cursor += cs
    close()
    return out


def _strip_karaoke(tokens: list[_Token]) -> list[_Token]:
    """``tokens`` without karaoke tags; a block left empty is dropped."""
    out: list[_Token] = []
    for t in tokens:
        if t.block is not None and _KARAOKE_TAG_RE.search(t.block):
            inside = _KARAOKE_TAG_RE.sub("", t.block)
            if not inside:
                continue
            t = _Token("{" + inside + "}", "", inside)
        out.append(t)
    return out


def _escape(text: str) -> str:
    """A plain text as ASS text: line breaks become ``\\N``."""
    return r"\N".join(split_cue_lines(text))


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------


def _parse_time(value: str, *, line_no: int) -> Fraction:
    """Seconds of an ``H:MM:SS.cc`` time, exactly.

    >>> _parse_time("1:02:03.45", line_no=1)
    Fraction(74469, 20)
    """
    m = _TIME_RE.match(value)
    if m is None:
        raise ValueError(f"line {line_no}: malformed ASS time {value.strip()!r}")
    h, mi, s, cs = (int(x) for x in m.groups())
    return Fraction(
        h * _CS_PER_HOUR + mi * _CS_PER_MINUTE + s * CS_PER_SECOND + cs, CS_PER_SECOND
    )


@dataclass(frozen=True, slots=True)
class _Event:
    line_no: int
    kind: str
    start: Fraction
    end: Fraction
    style: str
    fields: dict[str, str]
    raw: str
    index: int


@dataclass
class _Parsed:
    sections: list[dict[str, Any]]
    events_meta: dict[str, Any] | None
    events: list[_Event]


def _section_name(stripped: str, *, current: str | None) -> str | None:
    """The name of the section ``stripped`` opens, None if it is no header."""
    m = _HEADER_RE.match(stripped)
    if m is None:
        return None
    if m.group(1).strip().lower() in _KNOWN_SECTIONS:
        return m.group(1)
    in_binary = current is not None and current.strip().lower() in _BINARY_SECTIONS
    if in_binary and _UUENCODED_RE.match(stripped):
        return None  # uuencoded font or picture data that happens to be bracketed
    return m.group(1)


def _is_event_format(names: Iterable[str]) -> bool:
    """Whether ``names`` can be an ``[Events]`` format: Start, End, Text last."""
    lowered = [n.strip().lower() for n in names]
    return bool(lowered) and {"start", "end"} <= set(lowered) and lowered[-1] == "text"


def _parse_format(value: str, *, line_no: int) -> tuple[str, ...]:
    names = tuple(n.strip() for n in value.split(","))
    if not _is_event_format(names):
        raise ValueError(
            f"line {line_no}: an [Events] Format line needs Start, End, and Text "
            f"last: {value!r}"
        )
    return names


def _parse_event(
    kind: str, value: str, fmt: tuple[str, ...], *, line_no: int, index: int
) -> _Event:
    parts = value.split(",", len(fmt) - 1)
    if len(parts) < len(fmt):
        raise ValueError(
            f"line {line_no}: a {kind} line with {len(parts)} fields, "
            f"the Format line has {len(fmt)}"
        )
    by_lower = {name.lower(): part for name, part in zip(fmt, parts)}
    start = _parse_time(by_lower["start"], line_no=line_no)
    end = _parse_time(by_lower["end"], line_no=line_no)
    if end < start:
        raise ValueError(f"line {line_no}: the event ends before it starts")
    reserved = {"start", "end", "style", "text"}
    return _Event(
        line_no=line_no,
        kind=kind,
        start=start,
        end=end,
        style=by_lower.get("style", DEFAULT_STYLE_NAME),
        fields={n: p for n, p in zip(fmt, parts) if n.lower() not in reserved},
        raw=parts[-1],
        index=index,
    )


def _default_event_format(sections: Iterable[dict[str, Any]]) -> tuple[str, ...]:
    """libass's default when ``[Events]`` has no Format line: SSA's under
    ``[V4 Styles]``, ASS's otherwise."""
    names = {(s["name"] or "").strip().lower() for s in sections}
    return SSA_EVENT_FORMAT if _SSA_STYLES_SECTION in names else DEFAULT_EVENT_FORMAT


def _parse_events(
    lines: list[tuple[int, str]],
    *,
    name: str,
    position: int,
    sections: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[_Event]]:
    fmt: tuple[str, ...] | None = None
    events: list[_Event] = []
    other: list[str] = []
    for line_no, line in lines:
        stripped = line.strip()
        if stripped.startswith(";"):
            other.append(line)
            continue
        m = _KEY_VALUE_RE.match(line.lstrip())  # the text keeps trailing blanks
        if m is None:
            raise ValueError(f"line {line_no}: malformed [Events] line {line!r}")
        key, value = m.group(1).lower(), m.group(2)
        if key == "format":
            if fmt is not None or events:
                raise ValueError(f"line {line_no}: a second or late Format line")
            fmt = _parse_format(value, line_no=line_no)
        elif key in (DIALOGUE.lower(), COMMENT.lower()):
            fmt = fmt or _default_event_format(sections)
            kind = DIALOGUE if key == DIALOGUE.lower() else COMMENT
            events.append(
                _parse_event(kind, value, fmt, line_no=line_no, index=len(events))
            )
        else:
            other.append(line)  # Picture:, Sound:, Movie:, Command:
    meta = {
        "name": name,
        "position": position,
        "format": list(fmt or _default_event_format(sections)),
        "lines": other,
    }
    return meta, events


def _parse(text: str, *, keep_sections: Iterable[str] | None = None) -> _Parsed:
    """``text`` parsed; the script keeps only the non-Events sections named in
    ``keep_sections`` (case-insensitive; ``None`` keeps them all)."""
    raw_sections: list[tuple[str | None, list[tuple[int, str]]]] = [(None, [])]
    for line_no, line in enumerate(split_cue_lines(text), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        name = _section_name(stripped, current=raw_sections[-1][0])
        if name is not None:
            raw_sections.append((name, []))
        else:
            raw_sections[-1][1].append((line_no, line))

    sections: list[dict[str, Any]] = []
    events_lines: list[tuple[int, str]] = []
    events_at: tuple[str, int] | None = None
    for name, lines in raw_sections:
        if name is not None and name.strip().lower() == EVENTS_SECTION.lower():
            events_at = events_at or (name, len(sections))
            events_lines.extend(lines)
        elif name is not None or lines:
            sections.append({"name": name, "lines": [line for _, line in lines]})
    if events_at is None:
        raise ValueError("no [Events] section in the input: not an ASS/SSA file")
    meta, events = _parse_events(
        events_lines, name=events_at[0], position=events_at[1], sections=sections
    )
    if keep_sections is not None:
        keep = {name.strip().lower() for name in keep_sections}

        def kept(s: dict[str, Any]) -> bool:
            return s["name"] is not None and s["name"].strip().lower() in keep

        meta["position"] = sum(map(kept, sections[: meta["position"]]))
        sections = [s for s in sections if kept(s)]
    return _Parsed(sections, meta, events)


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
    words_tier: str = DEFAULT_WORDS_TIER_NAME,
    comments_tier: str = DEFAULT_COMMENTS_TIER_NAME,
    script_tier: str = DEFAULT_SCRIPT_TIER_NAME,
    encoding: str | None = None,
    keep_sections: Iterable[str] | None = None,
    **_kwargs: Any,
) -> IntervalAnnotationStore:
    """Parse an ASS/SSA file, or ASS bytes or text, into a ``MemoryStore``.

    Dialogue events go on ``tier``, their karaoke syllables on ``words_tier``,
    comment events on ``comments_tier``, the script's other sections on one
    annotation on ``script_tier`` (see the module docstring).

    Args:
        source: Bytes (see ``encoding``), a path, or inline text. A
            ``str`` naming an existing file is read from it (even one named
            ``"[Group] Show - 01.ass"``); any other ``str`` is inline text.
        rate: Rate of every ``RationalTime`` produced; must hold a centisecond
            (and any decimal karaoke duration) exactly.
        asset_id: The ``MediaRef.asset_id`` the events annotate.
        attribution: ``Provenance.was_attributed_to`` of every annotation.
        tier: Name of the lines (dialogue) tier.
        words_tier: Name of the karaoke syllable tier (created only when
            there are syllables).
        comments_tier: Name of the comment-event tier (created only when
            there are comments).
        script_tier: Name of the script-metadata tier.
        encoding: Text encoding of a file or of bytes. ``None`` sniffs a BOM
            (UTF-8, UTF-16, UTF-32) and otherwise reads UTF-8; name one
            (``"cp1252"``) for an older file without a BOM.
        keep_sections: Names of the non-``[Events]`` sections the ``script``
            annotation keeps verbatim (case-insensitive, e.g.
            ``("Script Info", "V4+ Styles")``); ``None`` (the default) keeps
            them all. ``[Fonts]`` and ``[Graphics]`` can be megabytes of
            uuencoded data, and ``[Aegisub Project Garbage]`` holds local file
            paths, so name what you need before storing or sharing the result.
            :func:`dump` writes defaults for a dropped ``[Script Info]`` or
            styles section.

    Raises:
        ValueError: On malformed input, naming the line number, and on input
            with no ``[Events]`` section. A ``rate`` that cannot hold a time
            or a karaoke duration raises ``LossyTimeConversionError`` (a
            ``ValueError``) naming the line too.
    """
    if isinstance(keep_sections, str):
        keep_sections = (keep_sections,)
    parsed = _parse(read_text(source, encoding=encoding), keep_sections=keep_sections)

    def at(seconds: Fraction) -> RationalTime:
        return RationalTime.from_seconds(seconds, rate=rate)

    provenance = import_provenance(
        GENERATED_BY, attribution, generated_at=RationalTime.now(rate)
    )
    built: list[Annotation] = []

    def add(tier_name: str, start: Fraction, end: Fraction, body: dict, uri: str):
        built.append(
            Annotation(
                id=uuid4(),
                tier=tier_name,
                reference=MediaRef(
                    asset_id=asset_id, interval=TimeInterval(at(start), at(end))
                ),
                body=body,
                body_schema_uri=uri,
                provenance=provenance,
            )
        )

    def add_event(ev: _Event) -> int:
        """Add ``ev`` and its syllables; the number of syllables added."""
        tokens = _tokens(ev.raw)
        body = {
            "text": "".join(t.plain for t in tokens),
            "raw": ev.raw,
            "style": ev.style,
            "fields": dict(ev.fields),
            "index": ev.index,
        }
        if ev.kind == COMMENT:
            add(comments_tier, ev.start, ev.end, body, EVENT_BODY_SCHEMA_URI)
            return 0
        add(tier, ev.start, ev.end, body, EVENT_BODY_SCHEMA_URI)
        syllables = _syllables(tokens, where=f"line {ev.line_no}")
        for ordinal, syl in enumerate(syllables):
            add(
                words_tier,
                min(ev.start + syl.start / CS_PER_SECOND, ev.end),
                min(ev.start + syl.end / CS_PER_SECOND, ev.end),
                {
                    "text": syl.text,
                    "karaoke": syl.kind,
                    "event": ev.index,
                    "ordinal": ordinal,
                },
                SYLLABLE_BODY_SCHEMA_URI,
            )
        return len(syllables)

    has_words = has_comments = False
    for ev in parsed.events:
        try:
            has_words |= add_event(ev) > 0
        except LossyTimeConversionError as error:
            raise LossyTimeConversionError(f"line {ev.line_no}: {error}") from error
        has_comments |= ev.kind == COMMENT
    script = {"sections": parsed.sections, "events": parsed.events_meta}
    add(script_tier, Fraction(0), Fraction(0), script, SCRIPT_BODY_SCHEMA_URI)

    store = MemoryStore()
    store.add_tier(Tier(tier))
    if has_words:
        store.add_tier(
            Tier(words_tier, stereotype=TierStereotype.INCLUDED_IN, parent=tier)
        )
    if has_comments:
        store.add_tier(Tier(comments_tier))
    store.add_tier(Tier(script_tier))
    for a in built:
        store.add(a)
    return store


# ---------------------------------------------------------------------------
# dump
# ---------------------------------------------------------------------------


def _cs(t: RationalTime) -> int:
    """``t`` in whole centiseconds, truncated; a negative time raises."""
    return nonnegative_ms(t, format_name=FORMAT_NAME) // _MS_PER_CS


def _format_time(t: RationalTime) -> str:
    """``t`` as ``H:MM:SS.cc``, truncated to the centisecond.

    >>> _format_time(RationalTime(3723459, 1000))
    '1:02:03.45'
    """
    hours, rem = divmod(_cs(t), _CS_PER_HOUR)
    minutes, rem = divmod(rem, _CS_PER_MINUTE)
    seconds, cs = divmod(rem, CS_PER_SECOND)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{cs:02d}"


@dataclass(frozen=True, slots=True)
class _Line:
    """An event to write."""

    interval: TimeInterval
    start: Fraction
    end: Fraction
    text: str  # plain text
    raw: str | None  # the ASS text, when it still reads as ``text``
    style: str
    fields: dict[str, str]
    index: int | None  # ASS read order
    comment: bool


@dataclass(frozen=True, slots=True)
class _Word:
    interval: TimeInterval
    start: Fraction
    end: Fraction
    text: str
    kind: str
    event: int | None
    ordinal: int | None  # its place among its event's syllables


def _line_of(
    a: Annotation, *, comment: bool, default_style: str = DEFAULT_STYLE_NAME
) -> _Line | None:
    body, iv = a.body, a.interval
    if not isinstance(body, dict) or body.get("text") is None or iv is None:
        return None
    text = str(body["text"])
    is_ass = a.body_schema_uri == EVENT_BODY_SCHEMA_URI
    raw = body.get("raw") if is_ass else None
    if not isinstance(raw, str) or plain_text(raw) != text:
        raw = None  # the text was edited, or this is not an ASS event
    index = body.get("index") if is_ass else None
    fields = body.get("fields") if is_ass else None
    return _Line(
        interval=iv,
        start=iv.start.to_fraction(),
        end=iv.end.to_fraction(),
        text=text,
        raw=raw,
        style=str(body.get("style") or default_style) if is_ass else default_style,
        fields={str(k): str(v) for k, v in fields.items()}
        if isinstance(fields, dict)
        else {},
        index=index if isinstance(index, int) else None,
        comment=comment,
    )


def _word_of(a: Annotation) -> _Word | None:
    body, iv = a.body, a.interval
    if not isinstance(body, dict) or body.get("text") is None or iv is None:
        return None
    text = str(body["text"]).strip()
    if not text:
        return None
    kind = body.get("karaoke")
    is_ass = a.body_schema_uri == SYLLABLE_BODY_SCHEMA_URI
    event, ordinal = (
        (body.get("event"), body.get("ordinal")) if is_ass else (None, None)
    )
    return _Word(
        interval=iv,
        start=iv.start.to_fraction(),
        end=iv.end.to_fraction(),
        text=text,
        kind=kind if kind in KARAOKE_KINDS else _DEFAULT_KARAOKE,
        event=event if isinstance(event, int) else None,
        ordinal=ordinal if isinstance(ordinal, int) else None,
    )


def _words_by_line(lines: list[_Line], words: list[_Word]) -> dict[int, list[_Word]]:
    """Words per index in ``lines`` (sorted by start). An ASS syllable goes to
    its own event when that event still holds it in time; any other word goes
    where :func:`~lacing.adapters._cues.assign_words` puts it."""
    by_event = {line.index: i for i, line in enumerate(lines) if line.index is not None}
    by_line: dict[int, list[_Word]] = {}
    others: list[_Word] = []
    for w in words:
        i = by_event.get(w.event) if w.event is not None else None
        if i is not None and lines[i].start <= w.start and w.end <= lines[i].end:
            by_line.setdefault(i, []).append(w)
        else:
            others.append(w)
    for i, ws in assign_words(lines, others).items():
        by_line.setdefault(i, []).extend(ws)
    for ws in by_line.values():
        if len({w.event for w in ws}) == 1 and all(w.ordinal is not None for w in ws):
            ws.sort(key=lambda w: w.ordinal)  # one event's syllables: text order
        else:
            ws.sort(key=_word_order)
    return by_line


def _word_order(w: _Word) -> tuple[Fraction, Fraction, int, int]:
    """Time order; ties (zero-length syllables, syllables cut at their event's
    end) broken by event and syllable ordinal, so the order never depends on
    the store's iteration order."""
    missing = -1
    return (
        w.start,
        w.end,
        missing if w.event is None else w.event,
        missing if w.ordinal is None else w.ordinal,
    )


def _encodes(line: _Line, tokens: list[_Token], words: list[_Word]) -> bool:
    """Whether ``tokens`` (the line's ``raw``) already encode ``words``."""
    syllables = _syllables(tokens, where="an ASS event's raw text")
    if len(syllables) != len(words):
        return False
    for syl, w in zip(syllables, words):
        start = min(line.start + syl.start / CS_PER_SECOND, line.end)
        end = min(line.start + syl.end / CS_PER_SECOND, line.end)
        if (syl.text, syl.kind, start, end) != (w.text, w.kind, w.start, w.end):
            return False
    return True


def _with_karaoke(tokens: list[_Token], line: _Line, words: list[_Word]) -> str:
    """The text of ``tokens`` (karaoke-free) with a karaoke tag before each
    word found in it, and an empty ``{\\k..}`` before a word after a gap."""
    base = "".join(t.raw for t in tokens)
    plain_starts: list[int] = []
    anchors: list[tuple[int, bool]] = []  # (raw offset, is_run) per plain token
    plain_at = raw_at = 0
    for t in tokens:
        if t.plain:
            plain_starts.append(plain_at)
            anchors.append((raw_at, t.is_run))
        plain_at += len(t.plain)
        raw_at += len(t.raw)

    def raw_position(pos: int) -> int:
        k = bisect_right(plain_starts, pos) - 1
        raw_start, is_run = anchors[k]
        return raw_start + (pos - plain_starts[k] if is_run else 0)

    placed = place_words("".join(t.plain for t in tokens), words)
    pieces: list[str] = []
    done = 0
    cursor = _cs(line.interval.start)
    for i, (w, pos) in enumerate(placed):
        start = max(_cs(w.interval.start), cursor)
        end = _cs(w.interval.end)
        if i + 1 < len(placed):
            end = min(end, _cs(placed[i + 1][0].interval.start))
        end = max(end, start)
        tag = f"{{\\k{start - cursor}}}" if start > cursor else ""
        tag += f"{{\\{w.kind}{end - start}}}"
        cursor = end
        at = raw_position(pos)
        pieces += [base[done:at], tag]
        done = at
    pieces.append(base[done:])
    return "".join(pieces)


def _event_text(line: _Line, words: list[_Word]) -> str:
    if line.raw is not None:
        tokens = _tokens(line.raw)
        if line.comment or _encodes(line, tokens, words):
            return line.raw
    else:
        tokens = _tokens(_escape(line.text))
    tokens = _strip_karaoke(tokens)
    if not words:
        return "".join(t.raw for t in tokens)
    return _with_karaoke(tokens, line, words)


def _field(value: str, *, name: str) -> str:
    if "," in value or "\n" in value or "\r" in value:
        raise ValueError(
            f"ASS cannot write the {name} field {value!r}: it holds a comma or "
            "a line break"
        )
    return value


def _event_row(line: _Line, text: str, fmt: list[str]) -> str:
    if "\n" in text or "\r" in text:
        raise ValueError(f"ASS cannot write an event text with a line break: {text!r}")
    fields = {k.lower(): v for k, v in line.fields.items()}
    values: list[str] = []
    for name in fmt:
        low = name.lower()
        if low == "text":
            values.append(text)
        elif low == "start":
            values.append(_format_time(line.interval.start))
        elif low == "end":
            values.append(_format_time(line.interval.end))
        elif low == "style":
            values.append(_field(line.style, name=name))
        else:
            default = _EVENT_FIELD_DEFAULTS.get(low, "")
            values.append(_field(fields.get(low, default), name=name))
    return f"{COMMENT if line.comment else DIALOGUE}: {','.join(values)}"


def _default_style_line(fmt: list[str], style: Mapping[str, str]) -> str:
    return "Style: " + ",".join(_field(style.get(n.lower(), "0"), name=n) for n in fmt)


def _with_default_style(lines: list[str], style: Mapping[str, str]) -> list[str]:
    """A styles section's lines, with ``style`` added when it has none."""
    if any(_STYLE_KEY_RE.match(line) for line in lines):
        return lines
    fmt_line = next((line for line in lines if _FORMAT_KEY_RE.match(line)), None)
    if fmt_line is None:
        fmt = list(DEFAULT_STYLE_FORMAT)
        return [f"Format: {', '.join(fmt)}", *lines, _default_style_line(fmt, style)]
    fmt = [n.strip() for n in fmt_line.split(":", 1)[1].split(",")]
    return [*lines, _default_style_line(fmt, style)]


def _script_of(annotations: list[Annotation]) -> dict[str, Any] | None:
    scripts = [
        a.body
        for a in annotations
        if a.body_schema_uri == SCRIPT_BODY_SCHEMA_URI and isinstance(a.body, dict)
    ]
    if len(scripts) > 1:
        raise ValueError(f"{len(scripts)} ASS script annotations: dump one at a time")
    return scripts[0] if scripts else None


def _sections_to_write(
    script: dict[str, Any] | None,
    *,
    script_info: Sequence[str],
    default_style: Mapping[str, str],
    event_format: Sequence[str],
) -> tuple[list[tuple[str | None, list[str]]], dict[str, Any]]:
    """``(sections, events meta)``; the events section is the ``None``-lines
    entry in ``sections``."""
    events = dict((script or {}).get("events") or {})
    events.setdefault("name", EVENTS_SECTION)
    events.setdefault("format", list(event_format))
    events.setdefault("lines", [])
    found = [
        (s.get("name"), list(s.get("lines") or []))
        for s in (script or {}).get("sections") or []
    ]
    position = min(int(events.get("position", len(found))), len(found))
    sections: list[tuple[str | None, list[str] | None]] = [
        *found[:position],
        (events["name"], None),
        *found[position:],
    ]
    names = [(n or "").strip().lower() for n, _ in sections]
    styles = [i for i, n in enumerate(names) if n in _STYLES_SECTIONS]
    if styles:
        i = styles[0]
        lines = _with_default_style(sections[i][1] or [], default_style)
        sections[i] = (sections[i][0], lines)
    else:
        at = next(i for i, (_, lines) in enumerate(sections) if lines is None)
        sections.insert(at, (STYLES_SECTION, _with_default_style([], default_style)))
    if SCRIPT_INFO_SECTION.lower() not in names:
        sections.insert(0, (SCRIPT_INFO_SECTION, list(script_info)))
    return sections, events


def _event_order(line: _Line) -> tuple[int, int, Fraction, Fraction]:
    if line.index is not None:
        return (0, line.index, line.start, line.end)
    return (1, 0, line.start, line.end)


def dump(
    store: IntervalAnnotationStore,
    target: str | os.PathLike | None = None,
    *,
    tier: str | None = None,
    words_tier: str = DEFAULT_WORDS_TIER_NAME,
    comments_tier: str = DEFAULT_COMMENTS_TIER_NAME,
    script_info: Sequence[str] = DEFAULT_SCRIPT_INFO,
    default_style: Mapping[str, str] = DEFAULT_STYLE,
    event_format: Sequence[str] = DEFAULT_EVENT_FORMAT,
    **_kwargs: Any,
) -> bytes | None:
    """Write annotations as an ASS (v4.00+) script.

    Args:
        store: Source store. Lines are annotations with a time interval and a
            ``text`` body (an ASS dialogue, an LRC line, a SubRip or WebVTT
            cue, or any other); comments are those on ``comments_tier``.
        target: Output path. If None, returns bytes (UTF-8, no BOM, ``\\n``).
        tier: The tier whose texts are the dialogue lines. None (the default)
            means the ``lines`` tier when the store has text annotations on
            it, and otherwise every top-level tier (one with no parent
            constraint, as the SubRip and WebVTT writers choose) but
            ``words_tier`` and ``comments_tier``.
        words_tier: Tier whose annotations are written as karaoke tags.
        comments_tier: Tier whose annotations are written as ``Comment:``.
        script_info: The ``[Script Info]`` lines written when the store has
            no ASS script metadata, or it has no such section.
        default_style: The style written when the styles section has no
            ``Style:`` line: field values keyed by lowercased ``Format:``
            name (``"0"`` for a missing field); its ``name`` is also the
            style of every non-ASS line. Aegisub's ``Default`` by default.
        event_format: The ``[Events]`` ``Format:`` field names written when
            the store has no ASS script metadata (``Start``, ``End`` and
            ``Text`` last required; raises ``ValueError`` otherwise).
    """
    if not _is_event_format(event_format):
        raise ValueError(
            f"event_format needs Start, End, and Text last: {list(event_format)!r}"
        )
    style = {str(k).lower(): str(v) for k, v in default_style.items()}
    style_name = style.setdefault("name", DEFAULT_STYLE_NAME)
    annotations = list(iter_with_intervals(store))
    script = _script_of(annotations)
    sections, events = _sections_to_write(
        script, script_info=script_info, default_style=style, event_format=event_format
    )

    line_by_id = {
        id(a): line
        for a in annotations
        if a.tier not in (words_tier, comments_tier)
        and (line := _line_of(a, comment=False, default_style=style_name)) is not None
    }
    texts = [a for a in annotations if id(a) in line_by_id]
    lines = sorted(
        (line_by_id[id(a)] for a in select_cue_annotations(store, texts, tier=tier)),
        key=lambda line: (line.start, line.end),
    )
    comments = [
        line
        for a in annotations
        if a.tier == comments_tier
        and (line := _line_of(a, comment=True, default_style=style_name)) is not None
    ]
    words = sorted(
        (w for a in annotations if a.tier == words_tier and (w := _word_of(a))),
        key=_word_order,
    )
    words_by_line = _words_by_line(lines, words)

    fmt = list(events["format"])
    rows_by_event = [
        (line, _event_row(line, _event_text(line, words_by_line.get(i, [])), fmt))
        for i, line in enumerate(lines)
    ]
    rows_by_event += [(c, _event_row(c, _event_text(c, []), fmt)) for c in comments]
    rows_by_event.sort(key=lambda pair: _event_order(pair[0]))

    out: list[str] = []
    for name, lines_ in sections:
        if lines_ is None:  # the events section
            out.append(f"[{name}]")
            out.append(f"Format: {', '.join(fmt)}")
            out.extend(events["lines"])
            out.extend(row for _, row in rows_by_event)
        else:
            if name is not None:
                out.append(f"[{name}]")
            out.extend(lines_)
        out.append("")

    blob = "\n".join(out).encode("utf-8")
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
    extensions=EXTENSIONS,
    media_types=(MEDIA_TYPE,),
    body_schema_uris=(
        EVENT_BODY_SCHEMA_URI,
        SYLLABLE_BODY_SCHEMA_URI,
        SCRIPT_BODY_SCHEMA_URI,
    ),
    description=(
        "ASS/SSA subtitles (.ass, .ssa): events with styles and override "
        "tags, karaoke syllables, script metadata kept for round trips."
    ),
)
