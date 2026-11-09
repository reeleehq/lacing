"""Aligned tracks: one text, spans at every level, in a store and on the wire.

The wire document is :class:`lacing.bodies.aligned_track.AlignedTrackV1`
(integer milliseconds, the text stored once, a time-provenance on every span,
exported as JSON Schema for the TypeScript side). A store holds the same spans
as annotations (``RationalTime`` intervals) on one tier per level, with the
``annot://schema/aligned-span/v1`` body. Two converters, exact both ways:

- :func:`from_aligned_track`: a wire document into a store;
- :func:`to_aligned_track`: a store into a wire document. It reads the spans
  of the aligned-span body and also, as ``imported`` times, what
  :class:`lacing.tracks.subtitle.SubtitleBuilder` writes (sections, lines,
  words), so a store that exists today can be exported without a rewrite.

>>> from lacing.bodies.aligned_track import AlignedSpan, AlignedTrackV1, SpanTime
>>> track = AlignedTrackV1(
...     asset_id="song.mp3",
...     text="hello world",
...     spans=[
...         AlignedSpan(level="line", chars=(0, 11), start_ms=0, end_ms=1000,
...                     time=SpanTime(kind="imported")),
...         AlignedSpan(level="word", chars=(0, 5), start_ms=0, end_ms=400, parent=0,
...                     time=SpanTime(kind="measured", confidence=0.9)),
...         AlignedSpan(level="word", chars=(6, 11), start_ms=400, end_ms=1000, parent=0,
...                     time=SpanTime(kind="interpolated")),
...     ],
... )
>>> to_aligned_track(from_aligned_track(track), asset_id="song.mp3") == track
True

A store keeps what the document says, so the round trip is exact: the text on
one ``aligned-text`` annotation, and on each span's body its ``chars`` and the
``id`` of its parent's annotation. A store that never held a track (a
``SubtitleBuilder`` one) has neither, and an export works them out: the
parent is the innermost enclosing span of a coarser level, and the text is the
lines joined by newlines (else the words, or the syllables, joined by spaces),
a finer span being located, in order, in its parent's range (ignoring case).
Spans come out in pre-order: a parent, then what it holds, siblings by start,
then end, then level; the round trip is exact for a document in that order
(the validator does not require it, so another order comes back reordered).
A stored ``parent_id`` or ``chars`` an edit made inconsistent (a parent
deleted, a span moved) is dropped on export, not an error.
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from fractions import Fraction
from uuid import UUID, uuid4

from lacing.adapters import adapter_generator_id
from lacing.bodies.aligned_track import (
    LEVELS,
    SPAN_SCHEMA_URI,
    TEXT_SCHEMA_URI,
    AlignedTextBodyV1,
    AlignedSpan,
    AlignedSpanBodyV1,
    AlignedTrackV1,
    Level,
    SpanTime,
)
from lacing.model import Annotation, MediaRef, Provenance
from lacing.store import IntervalAnnotationStore, MemoryStore
from lacing.tier import Tier, TierStereotype
from lacing.time import (
    LossyTimeConversionError,
    QuantizeMode,
    RationalTime,
    TimeInterval,
)

GENERATED_BY = str(adapter_generator_id("aligned-track", "1.0.0"))
MS_PER_SECOND = 1000
DEFAULT_RATE = MS_PER_SECOND
LEVEL_TIERS: Mapping[str, str] = {
    "section": "sections",
    "line": "lines",
    "word": "words",
    "syllable": "syllables",
    "phone": "phones",
}
"""The tier each level lives on in a store."""
TEXT_TIER = "text"
"""The tier of the one annotation that holds a track's text."""

#: What :class:`~lacing.tracks.subtitle.SubtitleBuilder` writes, as levels.
_LEGACY_LEVELS: Mapping[str, Level] = {
    "annot://schema/song-section/v1": "section",
    "annot://schema/lyric-line/v1": "line",
    "annot://schema/word/v1": "word",
}
_LINE_SEPARATOR = "\n"
_INLINE_SEPARATOR = " "


# ---------------------------------------------------------------------------
# wire document -> store
# ---------------------------------------------------------------------------


def from_aligned_track(
    track: AlignedTrackV1,
    store: IntervalAnnotationStore | None = None,
    *,
    rate: int = DEFAULT_RATE,
    attribution: str = "anonymous",
    tiers: Mapping[str, str] = LEVEL_TIERS,
    text_tier: str = TEXT_TIER,
) -> IntervalAnnotationStore:
    """The track as annotations in ``store`` (a new ``MemoryStore`` by default).

    One tier per level present (``tiers`` names them, each ``INCLUDED_IN`` the
    nearest coarser level present; a tier the store already has is kept), and
    one annotation on ``text_tier`` holding the text. Millisecond times become
    ``RationalTime`` at ``rate``, which must hold a millisecond exactly (else
    ``LossyTimeConversionError``). One track per asset: a store that already
    holds one for ``track.asset_id`` raises ``ValueError``.
    """
    store = MemoryStore() if store is None else store
    if any(
        a.body_schema_uri == TEXT_SCHEMA_URI
        and isinstance(a.reference, MediaRef)
        and a.reference.asset_id == track.asset_id
        for a in store.all()
    ):
        raise ValueError(
            f"the store already holds an aligned track for {track.asset_id!r}"
        )
    present = [level for level in LEVELS if any(s.level == level for s in track.spans)]
    for i, level in enumerate(present):
        parent = tiers[present[i - 1]] if i else None
        _ensure_tier(store, tiers[level], parent)
    _ensure_tier(store, text_tier, None)

    now = RationalTime.now(rate)
    provenance = Provenance(
        was_generated_by=GENERATED_BY,
        was_attributed_to=attribution,
        generated_at_time=now,
        activity="import",
    )

    def add(tier, interval, body, uri, *, id=None, confidence=None):
        store.add(
            Annotation(
                id=id or uuid4(),
                tier=tier,
                reference=MediaRef(asset_id=track.asset_id, interval=interval),
                body=body.model_dump(mode="json"),
                body_schema_uri=uri,
                provenance=provenance,
                confidence=confidence,
            )
        )

    starts = [s.start_ms for s in track.spans]
    ends = [s.end_ms for s in track.spans]
    extent = TimeInterval(
        _from_ms(min(starts, default=0), rate), _from_ms(max(ends, default=0), rate)
    )
    add(
        text_tier,
        extent,
        AlignedTextBodyV1(text=track.text, language=track.language),
        TEXT_SCHEMA_URI,
    )
    ids = [uuid4() for _ in track.spans]
    for i, span in enumerate(track.spans):
        body = AlignedSpanBodyV1(
            level=span.level,
            chars=span.chars,
            label=span.label,
            time=span.time,
            text=None if span.chars is None else track.text[slice(*span.chars)],
            parent_id=None if span.parent is None else ids[span.parent],
        )
        interval = TimeInterval(
            _from_ms(span.start_ms, rate), _from_ms(span.end_ms, rate)
        )
        add(
            tiers[span.level],
            interval,
            body,
            SPAN_SCHEMA_URI,
            id=ids[i],
            confidence=span.time.confidence,
        )
    return store


def _ensure_tier(store: IntervalAnnotationStore, name: str, parent: str | None):
    if store.get_tier(name) is None:
        store.add_tier(
            Tier(
                name,
                stereotype=(
                    TierStereotype.INCLUDED_IN if parent else TierStereotype.NONE
                ),
                parent=parent,
            )
        )


def _from_ms(ms: int, rate: int) -> RationalTime:
    return RationalTime.from_seconds(Fraction(ms, MS_PER_SECOND), rate=rate)


# ---------------------------------------------------------------------------
# store -> wire document
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Row:
    """One span read from a store, before it is placed in the document."""

    id: UUID
    start: int
    end: int
    level: str
    text: str | None
    label: str | None
    time: SpanTime
    chars: tuple[int, int] | None
    parent_id: UUID | None
    order: int

    @property
    def depth(self) -> int:
        return LEVELS.index(self.level)

    @property
    def key(self) -> tuple[int, int, int, int]:
        return (self.start, -self.end, self.depth, self.order)


def to_aligned_track(
    store: IntervalAnnotationStore,
    *,
    asset_id: str,
    language: str | None = None,
    quantize: QuantizeMode | None = None,
) -> AlignedTrackV1:
    """The spans of ``store`` about ``asset_id`` as a wire document.

    Args:
        store: A store with aligned-span annotations (what
            :func:`from_aligned_track` writes) and/or the sections, lines and
            words of a ``SubtitleBuilder`` (read as ``imported`` times, with
            the generator as source, since the builder does not say whether
            they were measured).
        asset_id: The media whose annotations to export.
        language: BCP 47 tag for the document; defaults to the stored text's.
        quantize: ``None`` (the default) raises ``LossyTimeConversionError``
            for a time that is not a whole millisecond; ``"round"`` (ties to
            even, unlike JavaScript's ``Math.round``), ``"floor"`` or
            ``"ceil"`` quantizes it.
    """
    rows, stored = _read(store, asset_id, quantize)
    ordered, parents = _pre_order(rows)
    if stored is None:
        text, chars = _layout(ordered, parents)
        stored_language = None
    else:
        text, stored_language = stored.text, stored.language
        chars = _consistent_chars([r.chars for r in ordered], parents, len(text))
    spans = [
        AlignedSpan(
            level=r.level,
            chars=chars[i],
            label=r.label,
            time=r.time,
            start_ms=r.start,
            end_ms=r.end,
            parent=parents[i],
        )
        for i, r in enumerate(ordered)
    ]
    return AlignedTrackV1(
        asset_id=asset_id,
        text=text,
        language=language or stored_language,
        spans=spans,
    )


def _consistent_chars(
    chars: list[tuple[int, int] | None], parents: list[int | None], size: int
) -> list[tuple[int, int] | None]:
    """``chars`` with those dropped that the document would refuse: outside the
    text, or outside the parent's. An edited store (a parent deleted, a span
    moved) can hold them; an export degrades, it does not fail."""
    kept: list[tuple[int, int] | None] = []
    for c, parent in zip(chars, parents):
        outer = None if parent is None else kept[parent]
        if c is not None and (
            c[1] > size
            or (outer is not None and not outer[0] <= c[0] <= c[1] <= outer[1])
        ):
            c = None
        kept.append(c)
    return kept


def _ms(t: RationalTime, quantize: QuantizeMode | None) -> int:
    ms = t.to_fraction() * MS_PER_SECOND
    if ms.denominator == 1:
        return int(ms)
    if quantize is None:
        raise LossyTimeConversionError(
            f"{t!r} is not a whole number of milliseconds (pass quantize=)"
        )
    return {"round": round, "floor": math.floor, "ceil": math.ceil}[quantize](ms)


def _read(
    store: IntervalAnnotationStore, asset_id: str, quantize: QuantizeMode | None
) -> tuple[list[_Row], AlignedTextBodyV1 | None]:
    """The span rows about ``asset_id``, and the stored text (the first one)."""
    rows: list[_Row] = []
    stored: AlignedTextBodyV1 | None = None
    for a in store.all():
        interval = a.interval
        if interval is None or not (
            isinstance(a.reference, MediaRef) and a.reference.asset_id == asset_id
        ):
            continue
        uri = a.body_schema_uri
        if uri == TEXT_SCHEMA_URI:
            stored = stored or AlignedTextBodyV1.model_validate(a.body)
            continue
        start, end = _ms(interval.start, quantize), _ms(interval.end, quantize)
        if uri == SPAN_SCHEMA_URI:
            b = AlignedSpanBodyV1.model_validate(a.body)
            row = _Row(a.id, start, end, b.level, b.text, b.label, b.time, b.chars,
                       b.parent_id, len(rows))  # fmt: skip
        elif uri in _LEGACY_LEVELS:
            level = _LEGACY_LEVELS[uri]
            confidence = a.confidence
            if confidence is None:
                confidence = a.body.get("confidence")
            time = SpanTime(
                kind="imported",
                confidence=confidence,
                source=a.provenance.was_generated_by,
            )
            is_section = level == "section"
            row = _Row(
                a.id, start, end, level,
                None if is_section else a.body.get("text"),
                a.body.get("label") if is_section else None,
                time, None, None, len(rows),
            )  # fmt: skip
        else:
            continue
        rows.append(row)
    return rows, stored


def _pre_order(rows: list[_Row]) -> tuple[list[_Row], list[int | None]]:
    """``rows`` in pre-order, with each one's parent as an index in that order.

    A parent is the row a body names (``parent_id``) if it is there and of a
    coarser level, else the innermost row of a coarser level that encloses it.
    """
    by_id = {r.id: r for r in rows}
    ordered = sorted(rows, key=lambda r: r.key)
    inferred = _enclosing(ordered)
    parent_of: dict[UUID, UUID | None] = {}
    for r, found in zip(ordered, inferred):
        named = by_id.get(r.parent_id) if r.parent_id else None
        chosen = named if named is not None and named.depth < r.depth else found
        parent_of[r.id] = chosen.id if chosen is not None else None
    children: dict[UUID | None, list[_Row]] = {}
    for r in ordered:
        children.setdefault(parent_of[r.id], []).append(r)
    out: list[_Row] = []
    stack = list(reversed(children.get(None, [])))
    while stack:
        r = stack.pop()
        out.append(r)
        stack.extend(reversed(children.get(r.id, [])))
    position = {r.id: i for i, r in enumerate(out)}
    return out, [
        None if parent_of[r.id] is None else position[parent_of[r.id]] for r in out
    ]


def _enclosing(ordered: list[_Row]) -> list[_Row | None]:
    """For each row of ``ordered`` (by :attr:`_Row.key`), its parent in time.

    The innermost earlier row of a coarser level that contains it (one stack
    per level); failing that, the coarser row that overlaps it most (an
    aligner's word a few milliseconds outside its line is still that line's).
    """
    stacks: list[list[_Row]] = [[] for _ in LEVELS]
    found: list[_Row | None] = []
    for r in ordered:
        for stack in stacks:  # a row that ended before this one starts is done
            while stack and stack[-1].end < r.start:
                stack.pop()
        coarser = [c for d in range(r.depth - 1, -1, -1) for c in reversed(stacks[d])]
        found.append(next((c for c in coarser if c.end >= r.end), None))
        stacks[r.depth].append(r)
    by_level = _LevelIndex(ordered)
    return [parent or by_level.most_overlapping(r) for r, parent in zip(ordered, found)]


class _LevelIndex:
    """Rows per level, by start, for the "which coarser row overlaps most" query."""

    def __init__(self, ordered: list[_Row]) -> None:
        self._rows: list[list[_Row]] = [[] for _ in LEVELS]
        for r in ordered:  # already by start
            self._rows[r.depth].append(r)
        self._starts = [[r.start for r in rows] for rows in self._rows]
        self._longest = [
            max((r.end - r.start for r in rows), default=0) for rows in self._rows
        ]

    def most_overlapping(self, r: _Row) -> _Row | None:
        """The row of a coarser level sharing the most time with ``r`` (the
        innermost level on a tie); ``None`` if none shares any."""
        best, best_overlap = None, 0
        for d in range(r.depth - 1, -1, -1):
            rows, starts = self._rows[d], self._starts[d]
            hi = bisect_right(starts, r.end)
            lo = bisect_left(starts, r.start - self._longest[d])
            for c in rows[lo:hi]:
                overlap = min(r.end, c.end) - max(r.start, c.start)
                if overlap > best_overlap:
                    best, best_overlap = c, overlap
        return best


def _layout(
    ordered: list[_Row], parents: list[int | None]
) -> tuple[str, list[tuple[int, int] | None]]:
    """The track text and each span's ``chars``, for a store that holds none.

    The coarsest of line, word, syllable that has text sets the text (joined
    by newlines for lines, spaces otherwise); a finer span is searched, in
    order, inside its parent's range; anything else has no ``chars``.
    """
    texts = [r.text for r in ordered]
    chars: list[tuple[int, int] | None] = [None] * len(ordered)
    for top in ("line", "word", "syllable"):
        members = [i for i, r in enumerate(ordered) if r.level == top and texts[i]]
        if members:
            break
    else:
        return "", chars
    separator = _LINE_SEPARATOR if top == "line" else _INLINE_SEPARATOR
    text = separator.join(texts[i] for i in members)  # type: ignore[misc]
    folded = text.lower() if len(text.lower()) == len(text) else text
    cursor = 0
    for i in members:
        size = len(texts[i])  # type: ignore[arg-type]
        chars[i] = (cursor, cursor + size)
        cursor += size + len(separator)
    finer = LEVELS.index(top) + 1
    resume: dict[int, int] = {}
    for i, r in enumerate(ordered):
        parent = parents[i]
        if r.depth < finer or not texts[i] or parent is None or chars[parent] is None:
            continue
        lo, hi = chars[parent]  # type: ignore[misc]
        wanted = texts[i]
        start = max(resume.get(parent, lo), lo)
        at = text.find(wanted, start, hi)  # type: ignore[arg-type]
        if at < 0:
            at = folded.find(wanted.lower(), start, hi)  # type: ignore[union-attr]
        if at >= 0:
            chars[i] = (at, at + len(wanted))  # type: ignore[arg-type]
            resume[parent] = at + len(wanted)  # type: ignore[arg-type]
    return text, chars
