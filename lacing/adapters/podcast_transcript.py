"""Podcasting 2.0 ``podcast:transcript`` JSON adapter.

The JSON transcript format of the Podcast Namespace: a version and a list of
timed dialogue segments, at any granularity from whole turns down to single
words::

    {
      "version": "1.0.0",
      "segments": [
        {"speaker": "Darth Vader", "startTime": 0.5, "endTime": 0.75, "body": "I"},
        {"speaker": "Darth Vader", "startTime": 1, "endTime": 1.25, "body": "am"}
      ]
    }

Spec: the ``<podcast:transcript>`` tag,
https://github.com/Podcastindex-org/podcast-namespace/blob/main/docs/tags/transcript.md,
and its JSON section in
https://github.com/Podcastindex-org/podcast-namespace/blob/main/docs/examples/transcripts/transcripts.md#json
(elements ``version``, ``segments``, ``speaker``, ``startTime``, ``endTime``
"if available", ``body``).

We map segments to a single tier named ``segments`` (override with
``tier=``), stereotype ``NONE`` (the format has no hierarchy). Each segment
becomes one ``Annotation`` whose body (``annot://schema/podcast-transcript-segment/v1``)
holds::

    {"text": str, "speaker": str | None}

plus ``"end_inferred": True`` when the segment had no ``endTime``, and
``"extra": {...}`` holding any other fields of the segment with their values
(numbers that are not times as plain JSON numbers of the same value; see
"Numbers" below).

End times:
    ``endTime`` is optional in the spec. A segment without one (or with
    ``"endTime": null``) ends where the next *later* segment starts (segments
    sharing a start all end at the next later start); the last one is a
    point (``start == end``). The body records that the end was inferred,
    and :func:`dump` leaves ``endTime`` out again while the end is still the
    inferred one, so such files round-trip. A ``null`` ``speaker`` is an
    absent one, and the dump leaves it out.

Time discipline:
    Times are JSON numbers of seconds. They are read as exact ``Decimal``
    values (``json.loads(..., parse_float=Decimal)``, never ``float``), then
    converted exactly to ``RationalTime``. With ``rate=None`` (the default)
    the rate is the smallest power of ten, at least 1000, that holds every
    time in the file exactly: ``1.001`` is ``RationalTime(1001, 1000)``, a
    file with ``0.0000625`` (a sample at 16 kHz) is read at rate ``10**7``,
    and JavaScript float noise such as ``0.30000000000000004`` at
    ``10**17``, so every file is read without loss. An explicit ``rate``
    that cannot hold a time (``0.0005`` at rate 1000) raises
    ``LossyTimeConversionError`` naming the segment and the rate that would
    hold every time. On dump a time is written as an exact decimal when it
    has a terminating expansion, else truncated to the millisecond, which
    keeps the order of times (see
    :func:`lacing.adapters._podcast.seconds_number`).

Numbers:
    A number that is not a time is kept as the nearest ``float`` and written
    back as that value (``1.50`` is written ``1.5``; a PHP-style
    ``48.858092999999997`` becomes ``48.858093``, as any JSON reader reads it).
    ``NaN``, ``Infinity`` and ``1e400`` (not finite) are refused on load,
    naming the segment and the field. Bodies stay plain JSON, which a SQLite store
    or the server needs.

Lossy fields on dump:
    Provenance, confidence, schema URIs and tier metadata are dropped. The
    ``version`` is always written as ``1.0.0``; other top-level fields of a
    loaded file are not kept. Any annotation with a time interval (any
    reference kind) and a string ``text`` body is written as a segment, with
    its ``speaker`` when the body has a string one, so SubRip, WebVTT and LRC
    cues dump to a transcript too (losing their own body fields). Segments
    are written in start, then end, order.

Media type and extension:
    The spec serves transcripts as plain ``application/json``, which says
    nothing about the format, so this adapter registers no media type (a
    ``find_adapter(media_type="application/json")`` finds no adapter). It
    registers the compound extension ``.transcript.json``; a bare ``.json``
    stays with the W3C Web Annotation adapter. Pass ``format=`` otherwise.

Malformed input raises ``ValueError`` naming the segment index
(``segments[3]``): a document that is not a JSON object, ``segments`` missing
or not a list, a segment that is not an object, a missing or non-string
``body``, a non-string ``speaker``, a ``startTime`` that is missing, an
``endTime`` or ``startTime`` that is not a number, negative or not finite, an
``endTime`` before its ``startTime``, a number in another field that a float
cannot hold exactly, or a non-string ``version``.
"""

from __future__ import annotations

import os
from fractions import Fraction
from typing import Any
from uuid import uuid4

from lacing.adapters import adapter_generator_id, register_adapter
from lacing.adapters._common import import_provenance, iter_with_intervals
from lacing.adapters._podcast import (
    END_INFERRED_KEY,
    TimedItem,
    dated_items,
    load_podcast_json,
    parse_document,
    plain_json,
    time_fields,
    write_json,
)
from lacing.model import Annotation, MediaRef
from lacing.store import IntervalAnnotationStore, MemoryStore
from lacing.tier import Tier
from lacing.time import RationalTime

ADAPTER_NAME = "podcast_transcript"
ADAPTER_VERSION = "1.0.0"
GENERATED_BY = str(adapter_generator_id(ADAPTER_NAME, ADAPTER_VERSION))
BODY_SCHEMA_URI = "annot://schema/podcast-transcript-segment/v1"
DEFAULT_TIER_NAME = "segments"
DEFAULT_ASSET_ID = "podcast-transcript:unspecified"
EXTENSION = ".transcript.json"
FORMAT_VERSION = "1.0.0"
FORMAT_NAME = "podcast transcript JSON"
EXTRA_KEY = "extra"

_SEGMENT_FIELDS = ("speaker", "startTime", "endTime", "body")


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------


def _segment_body(item: TimedItem) -> dict[str, Any]:
    """The annotation body of one segment, its fields validated."""
    fields, where = item.fields, item.where
    text = fields.get("body")
    if not isinstance(text, str):
        raise ValueError(f"{where}: body must be a string, got {text!r}")
    speaker = fields.get("speaker")
    if speaker is not None and not isinstance(speaker, str):
        raise ValueError(f"{where}: speaker must be a string, got {speaker!r}")
    body: dict[str, Any] = {"text": text, "speaker": speaker}
    extra = {
        k: plain_json(v, where=f"{where}.{k}")
        for k, v in fields.items()
        if k not in _SEGMENT_FIELDS
    }
    if extra:
        body[EXTRA_KEY] = extra
    if item.end_inferred:
        body[END_INFERRED_KEY] = True
    return body


def load(
    source: str | bytes | os.PathLike,
    *,
    rate: int | None = None,
    rounding: str | None = None,
    asset_id: str = DEFAULT_ASSET_ID,
    attribution: str = "anonymous",
    tier: str = DEFAULT_TIER_NAME,
    **_kwargs: Any,
) -> IntervalAnnotationStore:
    """Parse a podcast transcript JSON file, bytes or text into a ``MemoryStore``.

    Args:
        source: Bytes (UTF-8), a path, or inline JSON text.
        rate: Rate of every ``RationalTime`` produced. ``None`` (the default)
            picks the smallest power of ten, at least 1000, at which every
            time in the file is exact, up to ``10**9`` (a store's limit); an
            explicit rate must hold every time exactly, unless ``rounding``.
        rounding: ``None`` (exact or raise), or a
            :meth:`~lacing.time.RationalTime.from_seconds_lossy` mode
            (``"round"``, ``"floor"``, ``"ceil"``) to quantise times instead,
            for files with float noise (``12.300000000000001``).
        asset_id: The ``MediaRef.asset_id`` the segments annotate.
        attribution: ``Provenance.was_attributed_to`` of every segment.
        tier: Name of the tier the segments go in.

    Raises:
        ValueError: On malformed input, naming the segment index.
    """
    doc = parse_document(
        load_podcast_json(source, format_name=FORMAT_NAME),
        rate=rate,
        kind="segments",
        rounding=rounding,
    )
    bodies = [_segment_body(item) for item in doc.items]

    store = MemoryStore()
    store.add_tier(Tier(tier))
    now = RationalTime.now(doc.rate)
    for item, body in zip(doc.items, bodies):
        store.add(
            Annotation(
                id=uuid4(),
                tier=tier,
                reference=MediaRef(asset_id=asset_id, interval=item.interval),
                body=body,
                body_schema_uri=BODY_SCHEMA_URI,
                provenance=import_provenance(
                    GENERATED_BY, attribution, generated_at=now
                ),
            )
        )
    return store


# ---------------------------------------------------------------------------
# dump
# ---------------------------------------------------------------------------


def _has_text(a: Annotation) -> bool:
    return isinstance(a.body, dict) and isinstance(a.body.get("text"), str)


def _segment(a: Annotation, inferred_end: Fraction) -> dict[str, Any]:
    body = a.body
    seg: dict[str, Any] = {}
    speaker = body.get("speaker")
    if isinstance(speaker, str):
        seg["speaker"] = speaker
    seg.update(
        time_fields(
            a, inferred_end, end_was_inferred=body.get(END_INFERRED_KEY) is True
        )
    )
    seg["body"] = body["text"]
    extra = body.get(EXTRA_KEY)
    if isinstance(extra, dict):
        seg.update({k: v for k, v in extra.items() if k not in _SEGMENT_FIELDS})
    return seg


def dump(
    store: IntervalAnnotationStore,
    target: str | os.PathLike | None = None,
    *,
    tier: str | None = None,
    **_kwargs: Any,
) -> bytes | None:
    """Write annotations as podcast transcript JSON.

    Args:
        store: Source store. Every annotation with a time interval (any
            reference kind) and a string ``text`` body is written as a
            segment, sorted by start then end.
        target: Output path. If None, returns bytes (UTF-8 JSON).
        tier: Restrict export to this tier. None = export all tiers.

    Raises:
        ValueError: For a negative time, which the format cannot hold.
    """
    anns = (
        a
        for a in iter_with_intervals(store)
        if (tier is None or a.tier == tier) and _has_text(a)
    )
    segments = [_segment(a, end) for a, end in dated_items(anns)]
    return write_json({"version": FORMAT_VERSION, "segments": segments}, target)


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------


register_adapter(
    name=ADAPTER_NAME,
    version=ADAPTER_VERSION,
    load=load,
    dump=dump,
    extensions=(EXTENSION,),
    media_types=(),  # the spec's application/json is not distinctive
    body_schema_uris=(BODY_SCHEMA_URI,),
    description=(
        "Podcasting 2.0 podcast:transcript JSON. Timed segments with an "
        "optional speaker, no tier hierarchy."
    ),
)
