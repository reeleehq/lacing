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

Reading order: spans are listed by start, then end descending (a container
before what it holds), then level (coarse first), so a parent is always
earlier than its children. A span's ``parent`` is the innermost enclosing span
of a coarser level. ``chars`` are recomputed on export, not stored: the text is
the lines joined by newlines (else the words, or the syllables, joined by
spaces), and a finer span is located in its parent's range, in order. A
track whose spans are not in reading order (a word repeated out of order in
its line) can come back with different ``chars`` for the repeated text.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from fractions import Fraction
from uuid import uuid4

from lacing.adapters import adapter_generator_id
from lacing.bodies.aligned_track import (
    LEVELS,
    SPAN_SCHEMA_URI,
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
) -> IntervalAnnotationStore:
    """The spans of ``track`` as annotations in ``store`` (a new ``MemoryStore``
    by default), on one tier per level present (``tiers`` names them).

    Each level's tier is ``INCLUDED_IN`` the nearest coarser level present.
    Millisecond times become ``RationalTime`` at ``rate``, which must hold a
    millisecond exactly (else ``LossyTimeConversionError``).
    """
    store = MemoryStore() if store is None else store
    present = [level for level in LEVELS if any(s.level == level for s in track.spans)]
    for i, level in enumerate(present):
        parent = tiers[present[i - 1]] if i else None
        store.add_tier(
            Tier(
                tiers[level],
                stereotype=(
                    TierStereotype.INCLUDED_IN if parent else TierStereotype.NONE
                ),
                parent=parent,
            )
        )
    now = RationalTime.now(rate)
    for span in track.spans:
        interval = TimeInterval(
            _from_ms(span.start_ms, rate), _from_ms(span.end_ms, rate)
        )
        body = AlignedSpanBodyV1(
            level=span.level,
            label=span.label,
            time=span.time,
            text=None if span.chars is None else track.text[slice(*span.chars)],
        )
        store.add(
            Annotation(
                id=uuid4(),
                tier=tiers[span.level],
                reference=MediaRef(asset_id=track.asset_id, interval=interval),
                body=body.model_dump(mode="json"),
                body_schema_uri=SPAN_SCHEMA_URI,
                provenance=Provenance(
                    was_generated_by=GENERATED_BY,
                    was_attributed_to=attribution,
                    generated_at_time=now,
                    activity="import",
                ),
                confidence=span.time.confidence,
            )
        )
    return store


def _from_ms(ms: int, rate: int) -> RationalTime:
    return RationalTime.from_seconds(Fraction(ms, MS_PER_SECOND), rate=rate)


# ---------------------------------------------------------------------------
# store -> wire document
# ---------------------------------------------------------------------------


def to_aligned_track(
    store: IntervalAnnotationStore,
    *,
    asset_id: str,
    language: str | None = None,
    quantize: QuantizeMode | None = None,
) -> AlignedTrackV1:
    """The spans of ``store`` about ``asset_id`` as a wire document.

    Args:
        store: A store with aligned-span annotations and/or the sections,
            lines and words of a ``SubtitleBuilder`` (those read as
            ``imported`` times, with the generator as source).
        asset_id: The media whose annotations to export.
        language: BCP 47 tag to put on the document.
        quantize: ``None`` (the default) raises ``LossyTimeConversionError``
            for a time that is not a whole millisecond; ``"round"``,
            ``"floor"`` or ``"ceil"`` quantizes it.
    """
    rows = sorted(
        (
            (_ms(iv.start, quantize), _ms(iv.end, quantize), span, order)
            for order, (iv, span) in enumerate(_span_rows(store, asset_id))
        ),
        key=lambda r: (r[0], -r[1], LEVELS.index(r[2][0]), r[3]),
    )
    levels = [r[2][0] for r in rows]
    texts = [r[2][1] for r in rows]
    parents = _parents([(r[0], r[1], lv) for r, lv in zip(rows, levels)])
    text, chars = _layout(levels, texts, parents)
    spans = [
        AlignedSpan(
            level=levels[i],
            chars=chars[i],
            label=rows[i][2][2],
            time=rows[i][2][3],
            start_ms=rows[i][0],
            end_ms=rows[i][1],
            parent=parents[i],
        )
        for i in range(len(rows))
    ]
    return AlignedTrackV1(asset_id=asset_id, text=text, language=language, spans=spans)


def _ms(t: RationalTime, quantize: QuantizeMode | None) -> int:
    ms = t.to_fraction() * MS_PER_SECOND
    if ms.denominator == 1:
        return int(ms)
    if quantize is None:
        raise LossyTimeConversionError(
            f"{t!r} is not a whole number of milliseconds (pass quantize=)"
        )
    return {"round": round, "floor": math.floor, "ceil": math.ceil}[quantize](ms)


def _span_rows(
    store: IntervalAnnotationStore, asset_id: str
) -> Iterator[tuple[TimeInterval, tuple[str, str | None, str | None, SpanTime]]]:
    """``(interval, (level, text, label, time))`` of each span about the asset."""
    for a in store.all():
        interval = a.interval
        if interval is None or not (
            isinstance(a.reference, MediaRef) and a.reference.asset_id == asset_id
        ):
            continue
        if a.body_schema_uri == SPAN_SCHEMA_URI:
            body = AlignedSpanBodyV1.model_validate(a.body)
            yield interval, (body.level, body.text, body.label, body.time)
        elif a.body_schema_uri in _LEGACY_LEVELS:
            level = _LEGACY_LEVELS[a.body_schema_uri]
            time = SpanTime(
                kind="imported",
                confidence=a.confidence or a.body.get("confidence"),
                source=a.provenance.was_generated_by,
            )
            label = a.body.get("label") if level == "section" else None
            text = None if level == "section" else a.body.get("text")
            yield interval, (level, text, label, time)


def _parents(rows: list[tuple[int, int, str]]) -> list[int | None]:
    """The innermost earlier span of a coarser level that encloses each span."""
    parents: list[int | None] = []
    for i, (start, end, level) in enumerate(rows):
        depth = LEVELS.index(level)
        best: int | None = None
        for j in range(i - 1, -1, -1):
            s, e, lv = rows[j]
            if LEVELS.index(lv) < depth and s <= start and end <= e:
                if best is None or LEVELS.index(lv) > LEVELS.index(rows[best][2]):
                    best = j
        parents.append(best)
    return parents


def _layout(
    levels: list[str], texts: list[str | None], parents: list[int | None]
) -> tuple[str, list[tuple[int, int] | None]]:
    """The track text and each span's ``chars`` in it.

    The coarsest of line, word, syllable that has text sets the text (joined
    by newlines for lines, spaces otherwise); a finer span is searched, in
    order, inside its parent's range; anything else has no ``chars``.
    """
    chars: list[tuple[int, int] | None] = [None] * len(levels)
    for top in ("line", "word", "syllable"):
        members = [i for i, lv in enumerate(levels) if lv == top and texts[i]]
        if members:
            break
    else:
        return "", chars
    separator = _LINE_SEPARATOR if top == "line" else _INLINE_SEPARATOR
    text = separator.join(texts[i] for i in members)  # type: ignore[misc]
    cursor = 0
    for i in members:
        chars[i] = (cursor, cursor + len(texts[i]))  # type: ignore[arg-type]
        cursor += len(texts[i]) + len(separator)  # type: ignore[arg-type]
    finer = LEVELS.index(top) + 1
    resume: dict[int | None, int] = {}
    for i, lv in enumerate(levels):
        if LEVELS.index(lv) < finer or not texts[i]:
            continue
        parent = parents[i]
        if parent is None or chars[parent] is None:
            continue
        lo, hi = chars[parent]  # type: ignore[misc]
        at = text.find(texts[i], max(resume.get(parent, lo), lo), hi)  # type: ignore[arg-type]
        if at >= 0:
            chars[i] = (at, at + len(texts[i]))  # type: ignore[arg-type]
            resume[parent] = at + len(texts[i])  # type: ignore[arg-type]
    return text, chars
