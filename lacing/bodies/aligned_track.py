"""The aligned-track wire model and its store body (lacing#107).

Timed text at every granularity — sections, lines, words, syllables, phones —
as **one** document that a TypeScript player (or any non-Python consumer)
reads through the exported JSON Schema (``lacing/schema/aligned-track/v1.json``,
then Zod, under a version pin, the way lacing-ui consumes the other schemas).

Three schemas, one set of span fields:

- ``annot://schema/aligned-track/v1`` (:class:`AlignedTrackV1`): the **wire
  document**. The text is stored once (``text``); each span points into it with
  ``chars`` offsets instead of repeating it, says how its times were obtained
  (:class:`SpanTime`: ``measured``, ``interpolated`` or ``imported``, with
  confidence and source), and names its ``parent`` span. Times are **integer
  milliseconds**; ``RationalTime`` stays the persisted form
  (:mod:`lacing.tracks.aligned` converts, exactly, both ways).
- ``annot://schema/aligned-span/v1`` (:class:`AlignedSpanBodyV1`): the body of
  one span's annotation in a store (the interval is the annotation's), which
  keeps the surface ``text`` beside the span fields so generic consumers
  (``display_text``, the cue writers) read it, and the ``chars`` and
  ``parent_id`` that make an export exact.
- ``annot://schema/aligned-text/v1`` (:class:`AlignedTextBodyV1`): the track's
  text, stored once in a store as well, on one annotation spanning the asset.

Levels run from coarse to fine (:data:`LEVELS`); a span's parent is of a coarser
level and comes earlier in ``spans`` (a pre-order listing: a parent, then
what it holds, siblings by start). A child may stray a few milliseconds
outside its parent in time (an aligner's word against an imported line), so
containment in time is not required; containment in ``chars`` is.

The document is **open**: readers ignore fields they do not know (the models
use ``extra="ignore"``, so the exported schema does not forbid additional
properties and a pinned Zod mirror stays lenient). ``level`` and ``kind`` are
closed enums: a new value is a new major version (``v2``), not a field a v1
reader would mis-handle. ``chars`` count Unicode code points, **not** JavaScript
string indices: in TypeScript, index ``Array.from(text)``.
"""

from __future__ import annotations

from typing import Literal, get_args
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from lacing.json_schema import SchemaModel
from lacing.schema import register_body_schema

Level = Literal["section", "line", "word", "syllable", "phone"]
LEVELS: tuple[str, ...] = get_args(Level)
"""Coarse to fine: the order of the levels in a track."""

TimeKind = Literal["measured", "interpolated", "imported"]
TIME_KINDS: tuple[str, ...] = get_args(TimeKind)

TRACK_SCHEMA_URI = "annot://schema/aligned-track/v1"
SPAN_SCHEMA_URI = "annot://schema/aligned-span/v1"
TEXT_SCHEMA_URI = "annot://schema/aligned-text/v1"


class SpanTime(SchemaModel):
    """How a span's times were obtained."""

    model_config = {"frozen": True, "extra": "ignore"}

    kind: TimeKind = Field(
        ...,
        description=(
            "``measured`` by an aligner or recognizer, ``interpolated`` between "
            "measured neighbours, or ``imported`` from a file or source that "
            "does not say."
        ),
    )
    confidence: float | None = Field(
        None, ge=0.0, le=1.0, description="Confidence in [0, 1], when known."
    )
    source: str | None = Field(
        None, description="What produced the times, e.g. ``model:whisperx@3``."
    )


class _SpanFields(BaseModel):
    """What a span says about itself, in the document and in a store."""

    level: Level = Field(..., description="Granularity of the span.")
    chars: tuple[int, int] | None = Field(
        None,
        description=(
            "``[start, end)`` offsets, in Unicode code points, into the track's "
            "``text``; ``None`` for a span with no surface text (a phone, a "
            "bare section)."
        ),
    )
    label: str | None = Field(
        None,
        description=(
            "Name of a span that is not surface text: a section label, a phone symbol."
        ),
    )
    time: SpanTime = Field(..., description="How the span's times were obtained.")

    @model_validator(mode="after")
    def _check_chars(self):
        if self.chars is not None and not 0 <= self.chars[0] <= self.chars[1]:
            raise ValueError(f"chars must be 0 <= start <= end, got {self.chars!r}")
        return self


class AlignedSpan(_SpanFields, SchemaModel):
    """One span of the wire document."""

    model_config = {"frozen": True, "extra": "ignore"}

    start_ms: int = Field(..., ge=0, description="Start, integer milliseconds.")
    end_ms: int = Field(..., ge=0, description="End, integer milliseconds.")
    parent: int | None = Field(
        None,
        ge=0,
        description=(
            "Index in ``spans`` of the enclosing span, of a coarser level and "
            "earlier in the list; ``None`` for a top-level span."
        ),
    )

    @model_validator(mode="after")
    def _check_times(self):
        if self.end_ms < self.start_ms:
            raise ValueError(
                f"span ends before it starts: {self.start_ms}..{self.end_ms}"
            )
        return self


class AlignedTrackV1(SchemaModel):
    """An aligned text: the text once, and its spans at every level."""

    model_config = {"frozen": True, "extra": "ignore"}

    asset_id: str = Field(..., description="The media the times refer to.")
    text: str = Field(
        ...,
        description="The full text, stored once; spans point into it by ``chars``.",
    )
    language: str | None = Field(None, description="BCP 47 tag, when known.")
    spans: list[AlignedSpan] = Field(
        default_factory=list,
        description=(
            "Spans in pre-order: a span, then the spans it holds; siblings by "
            "start, then end, then level. A parent is of a coarser level and "
            "comes earlier than its children."
        ),
    )

    @model_validator(mode="after")
    def _check_spans(self):
        size = len(self.text)
        for i, span in enumerate(self.spans):
            if span.chars is not None and span.chars[1] > size:
                raise ValueError(f"span {i}: chars {span.chars!r} exceed the text")
            if span.parent is None:
                continue
            if span.parent >= i:
                raise ValueError(f"span {i}: parent {span.parent} is not earlier")
            parent = self.spans[span.parent]
            if LEVELS.index(parent.level) >= LEVELS.index(span.level):
                raise ValueError(f"span {i}: parent is not of a coarser level")
            if (
                span.chars is not None
                and parent.chars is not None
                and not parent.chars[0]
                <= span.chars[0]
                <= span.chars[1]
                <= parent.chars[1]
            ):
                raise ValueError(f"span {i}: chars {span.chars!r} leave its parent's")
        return self


class AlignedSpanBodyV1(_SpanFields, SchemaModel):
    """The body of one span's annotation (its interval is the annotation's)."""

    model_config = {"frozen": True, "extra": "forbid"}

    text: str | None = Field(
        None, description="Surface text of the span, as ``text[chars]`` of its track."
    )
    parent_id: UUID | None = Field(
        None, description="``id`` of the annotation of the enclosing span, if any."
    )


class AlignedTextBodyV1(SchemaModel):
    """The text of a track, stored once, on one annotation spanning the asset."""

    model_config = {"frozen": True, "extra": "forbid"}

    text: str = Field(..., description="The full text the spans' ``chars`` index.")
    language: str | None = Field(None, description="BCP 47 tag, when known.")


register_body_schema(TRACK_SCHEMA_URI, AlignedTrackV1)
register_body_schema(SPAN_SCHEMA_URI, AlignedSpanBodyV1)
register_body_schema(TEXT_SCHEMA_URI, AlignedTextBodyV1)
