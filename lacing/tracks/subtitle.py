"""Subtitle / lyric / caption tracks — the (sections, lines, words) trio.

``SubtitleBuilder`` lets callers add sections, lines, and words to a
store with float seconds and a single ``asset_id``, instead of
hand-rolling ``Annotation`` / ``MediaRef`` / ``Provenance`` /
``TimeInterval``. ``SubtitleTrack`` provides matching read-side
convenience: ``lines_in(window)``, ``words_in(window)``,
``sections_covering(t)``.

Body schemas are conventional URIs:

- ``annot://schema/song-section/v1`` — ``{label, title?, energy?, mood?}``
- ``annot://schema/lyric-line/v1`` — ``{text, line_index?, section?}``
- ``annot://schema/word/v1`` — ``{text, line_index?, confidence?}``, the
   built-in strict :mod:`lacing.bodies.word` schema, registered on import.

All three are built-in body schemas (:mod:`lacing.bodies`), registered on
import. Sections and lines are permissive (a caller's ``extra=`` keys are
kept); ``word/v1`` is strict, so wherever bodies are validated
(``validate_body``, the server) a word's ``extra=`` keys must be fields of that
schema: use :meth:`SubtitleBuilder.add` with your own URI for anything else.

Quick start::

    from lacing import MemoryStore
    from lacing.tracks.subtitle import SubtitleBuilder, SubtitleTrack

    store = MemoryStore()
    with SubtitleBuilder(store, asset_id="song/audio.mp3") as b:
        b.section("intro", 0.0, 12.5)
        b.line("I came down to the river", 12.5, 16.2,
               section="verse_1", words=[
                   ("I",     12.5, 12.7),
                   ("came",  12.7, 13.0),
                   ("down",  13.0, 13.3),
               ])

    track = SubtitleTrack(store, asset_id="song/audio.mp3")
    chorus_lines = track.lines_in(35.0, 55.0)
    section_at_42 = track.sections_covering(42.0)
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence
from uuid import UUID, uuid4

from pydantic import BaseModel

import lacing.bodies  # noqa: F401  registers the section, line and word schemas
from lacing.bodies.lyric_line import LyricLineBodyV1
from lacing.bodies.song_section import SongSectionBodyV1

from lacing.allen import AllenRelation
from lacing.model import Annotation, MediaRef, Provenance
from lacing.store.base import IntervalAnnotationStore
from lacing.tier import Tier, TierStereotype
from lacing.time import RationalTime, TimeInterval


SECTIONS_TIER = "sections"
LINES_TIER = "lines"
WORDS_TIER = "words"

SECTION_SCHEMA_URI = "annot://schema/song-section/v1"
LINE_SCHEMA_URI = "annot://schema/lyric-line/v1"
WORD_SCHEMA_URI = "annot://schema/word/v1"

DEFAULT_RATE = 1000  # ms-precision is plenty for sung-text alignment

#: Mapping of body URI → minimal example body: an inline reference for
#: callers building outside the builder. Each validates against its schema
#: (``SUBTITLE_BODY_MODELS``, or the built-in ``word/v1``).
BUILT_IN_BODY_SCHEMAS: dict[str, dict[str, Any]] = {
    SECTION_SCHEMA_URI: {
        "label": "verse_1",
        "title": "verse 1",
        "energy": "medium",
        "mood": "wistful",
    },
    LINE_SCHEMA_URI: {
        "text": "I came down to the river",
        "line_index": 0,
        "section": "verse_1",
    },
    WORD_SCHEMA_URI: {"text": "river", "line_index": 0, "confidence": 0.94},
}


def _interval(start_s: float, end_s: float, rate: int) -> TimeInterval:
    """Float seconds → ``TimeInterval`` at ``rate`` ticks/second.

    Rounds each end to the nearest tick with lacing's exact rule
    (:meth:`RationalTime.from_seconds_lossy`, as
    :meth:`TimeInterval.from_seconds_lossy` does), so a value like ``14.2``
    at rate=1000 doesn't trip the strict "lossy decimal" guard. An empty or
    reversed range is widened to one tick after its start: a section, line
    or word must have a duration.
    """
    if not (rate > 0):
        raise ValueError(f"rate must be positive (got {rate})")
    start = RationalTime.from_seconds_lossy(start_s, rate=rate)
    end = RationalTime.from_seconds_lossy(end_s, rate=rate)
    if end.value <= start.value:
        end = RationalTime(start.value + 1, rate)
    return TimeInterval(start, end)


@dataclass(frozen=True, slots=True, kw_only=True)
class _BuiltAnnotation:
    """Receipt for an inserted annotation — useful in tests + telemetry."""

    id: UUID
    tier: str
    start_s: float
    end_s: float


#: The section and line schemas, registered on import of :mod:`lacing.bodies`
#: (lacing#144). Words use the built-in ``word/v1`` schema.
SUBTITLE_BODY_MODELS: dict[str, type[BaseModel]] = {
    SECTION_SCHEMA_URI: SongSectionBodyV1,
    LINE_SCHEMA_URI: LyricLineBodyV1,
}


def register_subtitle_schemas() -> None:
    """Deprecated no-op: the section, line and word schemas are built-in bodies,
    registered when this module (or :mod:`lacing.bodies`) is imported."""
    warnings.warn(
        "register_subtitle_schemas() is a no-op: song-section/v1, lyric-line/v1 "
        "and word/v1 are built-in body schemas, registered on import (lacing#144).",
        DeprecationWarning,
        stacklevel=2,
    )


class SubtitleBuilder:
    """Builder for ``(sections, lines, words)`` tiers over one asset.

    The builder is a context manager *only as a convenience*; it has no
    transactional semantics. Calling ``.section()`` / ``.line()`` /
    ``.word()`` writes immediately, in the order given.

    Args:
        store: Any ``IntervalAnnotationStore`` (memory, sqlite, postgres).
        asset_id: The ``MediaRef.asset_id`` to attach every annotation
            to. Typically a path or content-hash of the audio file.
        rate: Tick rate for time intervals. Defaults to 1000 (ms).
        was_generated_by: ``Provenance.was_generated_by``. Defaults to
            ``"processor:lacing.tracks.subtitle"``.
        was_attributed_to: ``Provenance.was_attributed_to``.
        ensure_tiers: When True (default), creates the three tiers if
            they don't exist. Pass False if your store uses different
            tier names and you've created them yourself.
    """

    def __init__(
        self,
        store: IntervalAnnotationStore,
        *,
        asset_id: str,
        rate: int = DEFAULT_RATE,
        was_generated_by: str = "processor:lacing.tracks.subtitle",
        was_attributed_to: str = "lacing",
        ensure_tiers: bool = True,
    ) -> None:
        self._store = store
        self._asset_id = asset_id
        self._rate = rate
        self._provenance = Provenance(
            was_generated_by=was_generated_by,
            was_attributed_to=was_attributed_to,
            generated_at_time=RationalTime.now(rate),
        )
        if ensure_tiers:
            self._ensure_tiers()

    # --- ergonomic write paths -------------------------------------------

    def section(
        self,
        label: str,
        start_s: float,
        end_s: float,
        *,
        title: str = "",
        energy: str = "",
        mood: str = "",
        extra: dict[str, Any] | None = None,
    ) -> _BuiltAnnotation:
        """Add a song section."""
        body: dict[str, Any] = {"label": label}
        if title:
            body["title"] = title
        if energy:
            body["energy"] = energy
        if mood:
            body["mood"] = mood
        if extra:
            body.update(extra)
        return self._add(SECTIONS_TIER, SECTION_SCHEMA_URI, start_s, end_s, body)

    def line(
        self,
        text: str,
        start_s: float,
        end_s: float,
        *,
        line_index: int | None = None,
        section: str = "",
        words: Sequence[
            tuple[str, float, float] | tuple[str, float, float, float]
        ] = (),
        extra: dict[str, Any] | None = None,
    ) -> _BuiltAnnotation:
        """Add a lyric line. ``words`` is an optional list of
        ``(text, start, end)`` or ``(text, start, end, confidence)``
        tuples that will be inserted on the ``words`` tier.
        """
        body: dict[str, Any] = {"text": text}
        if line_index is not None:
            body["line_index"] = line_index
        if section:
            body["section"] = section
        if extra:
            body.update(extra)
        receipt = self._add(LINES_TIER, LINE_SCHEMA_URI, start_s, end_s, body)
        for w in words:
            if len(w) == 3:
                wtext, wstart, wend = w
                wconf = None
            elif len(w) == 4:
                wtext, wstart, wend, wconf = w
            else:
                raise ValueError(
                    f"word tuples must be (text, start, end[, confidence]); got {w!r}"
                )
            self.word(
                wtext,
                wstart,
                wend,
                line_index=line_index,
                confidence=wconf,
            )
        return receipt

    def word(
        self,
        text: str,
        start_s: float,
        end_s: float,
        *,
        line_index: int | None = None,
        confidence: float | None = None,
        extra: dict[str, Any] | None = None,
    ) -> _BuiltAnnotation:
        """Add one word. ``confidence`` goes in the body and on the envelope
        (``Annotation.confidence``, which ``low_confidence_review`` reads)."""
        body: dict[str, Any] = {"text": text}
        if line_index is not None:
            body["line_index"] = line_index
        if confidence is not None:
            confidence = float(confidence)
            body["confidence"] = confidence
        if extra:
            body.update(extra)
        return self._add(
            WORDS_TIER, WORD_SCHEMA_URI, start_s, end_s, body, confidence=confidence
        )

    # --- low-level escape hatch ------------------------------------------

    def add(
        self,
        *,
        tier: str,
        body_schema_uri: str,
        body: dict[str, Any],
        start_s: float,
        end_s: float,
    ) -> _BuiltAnnotation:
        """Add an annotation to ``tier`` with explicit schema/body."""
        return self._add(tier, body_schema_uri, start_s, end_s, body)

    # --- context manager (no transactional semantics) --------------------

    def __enter__(self) -> "SubtitleBuilder":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    # --- internals -------------------------------------------------------

    def _ensure_tiers(self) -> None:
        existing = {t.name for t in self._store.tiers()}
        if SECTIONS_TIER not in existing:
            self._store.add_tier(Tier(name=SECTIONS_TIER))
        if LINES_TIER not in existing:
            self._store.add_tier(
                Tier(
                    name=LINES_TIER,
                    stereotype=TierStereotype.INCLUDED_IN,
                    parent=SECTIONS_TIER,
                )
            )
        if WORDS_TIER not in existing:
            self._store.add_tier(
                Tier(
                    name=WORDS_TIER,
                    stereotype=TierStereotype.INCLUDED_IN,
                    parent=LINES_TIER,
                )
            )

    def _add(
        self,
        tier: str,
        schema_uri: str,
        start_s: float,
        end_s: float,
        body: dict[str, Any],
        *,
        confidence: float | None = None,
    ) -> _BuiltAnnotation:
        ann_id = uuid4()
        self._store.add(
            Annotation(
                id=ann_id,
                tier=tier,
                reference=MediaRef(
                    asset_id=self._asset_id,
                    interval=_interval(start_s, end_s, self._rate),
                ),
                body=body,
                body_schema_uri=schema_uri,
                provenance=self._provenance,
                confidence=confidence,
            )
        )
        return _BuiltAnnotation(id=ann_id, tier=tier, start_s=start_s, end_s=end_s)


class SubtitleTrack:
    """Read-side facade for ``(sections, lines, words)`` over an asset.

    Methods take ``float`` seconds; conversions to ``RationalTime`` are
    handled internally. Returned annotations are sorted by start time.

    Args:
        store: Any ``IntervalAnnotationStore``.
        asset_id: When set, query results are filtered to annotations
            whose ``MediaRef.asset_id`` equals this value. Pass
            ``None`` to ignore asset filtering (rarely what you want).
        rate: Tick rate used to build query intervals.
    """

    def __init__(
        self,
        store: IntervalAnnotationStore,
        *,
        asset_id: str | None,
        rate: int = DEFAULT_RATE,
    ) -> None:
        self._store = store
        self._asset_id = asset_id
        self._rate = rate

    # --- queries ---------------------------------------------------------

    def lines_in(self, start_s: float, end_s: float) -> list[Annotation]:
        """Lines that overlap ``[start_s, end_s]``."""
        return self._tier_in(LINES_TIER, start_s, end_s)

    def words_in(self, start_s: float, end_s: float) -> list[Annotation]:
        """Words that overlap ``[start_s, end_s]``."""
        return self._tier_in(WORDS_TIER, start_s, end_s)

    def sections_covering(self, t: float) -> list[Annotation]:
        """Sections whose interval contains ``t`` (typically one)."""
        # Use a tiny interval at t; "contains" semantics emerge naturally
        # via intersect over a degenerate window.
        eps = 1.0 / self._rate / 2  # half a tick — doesn't snap to neighbour
        return self._tier_in(SECTIONS_TIER, t, t + eps)

    def all_lines(self) -> list[Annotation]:
        return self._tier_all(LINES_TIER)

    def all_words(self) -> list[Annotation]:
        return self._tier_all(WORDS_TIER)

    def all_sections(self) -> list[Annotation]:
        return self._tier_all(SECTIONS_TIER)

    # --- internals -------------------------------------------------------

    def _tier_in(self, tier: str, start_s: float, end_s: float) -> list[Annotation]:
        window = _interval(start_s, end_s, self._rate)
        results = [
            ann for ann in self._store.at_tier(tier, window) if self._asset_matches(ann)
        ]
        results.sort(key=lambda a: a.reference.interval.start.to_seconds())
        return results

    def _tier_all(self, tier: str) -> list[Annotation]:
        results = [ann for ann in self._store.by_tier(tier) if self._asset_matches(ann)]
        results.sort(key=lambda a: a.reference.interval.start.to_seconds())
        return results

    def _asset_matches(self, ann: Annotation) -> bool:
        if self._asset_id is None:
            return True
        return ann.reference.asset_id == self._asset_id
