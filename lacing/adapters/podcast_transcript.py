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
``"extra": {...}`` holding any other fields of the segment verbatim (numbers
that are not times as plain JSON numbers).

End times:
    ``endTime`` is optional in the spec. A segment without one ends where the
    next *later* segment starts (segments sharing a start all end at the next
    later start); the last one is a point (``start == end``). The body records
    that the end was inferred, and :func:`dump` leaves ``endTime`` out again
    while the end is still the inferred one, so such files round-trip.

Time discipline:
    Times are JSON numbers of seconds. They are read as exact ``Decimal``
    values (``json.loads(..., parse_float=Decimal)``, never ``float``), then
    converted exactly to ``RationalTime`` at ``rate`` (default 1000): ``1.001``
    is ``RationalTime(1001, 1000)``. A time the rate cannot hold exactly
    (``0.0005`` at rate 1000) raises ``LossyTimeConversionError``. On dump a
    time is written as an exact decimal when it has a terminating expansion,
    else truncated to the millisecond, which keeps the order of times (see
    :func:`lacing.adapters._podcast.seconds_number`).

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
``body``, a non-string ``speaker``, a ``startTime`` or ``endTime`` that is
missing, not a number, negative or not finite, an ``endTime`` before its
``startTime``, or a non-string ``version``.
"""

from __future__ import annotations

import os
from fractions import Fraction
from pathlib import Path
from typing import Any
from uuid import uuid4

from lacing.adapters import adapter_generator_id, register_adapter
from lacing.adapters._common import iter_with_intervals
from lacing.adapters._cues import interval_sort_key
from lacing.adapters._podcast import (
    END_INFERRED_KEY,
    dumps_json,
    inferred_ends,
    load_podcast_json,
    parse_seconds,
    plain_json,
    seconds_number,
)
from lacing.model import Annotation, MediaRef, Provenance
from lacing.store import IntervalAnnotationStore, MemoryStore
from lacing.tier import Tier
from lacing.time import RationalTime, TimeInterval

ADAPTER_NAME = "podcast_transcript"
ADAPTER_VERSION = "1.0.0"
GENERATED_BY = str(adapter_generator_id(ADAPTER_NAME, ADAPTER_VERSION))
BODY_SCHEMA_URI = "annot://schema/podcast-transcript-segment/v1"
DEFAULT_TIER_NAME = "segments"
DEFAULT_RATE = 1000
DEFAULT_ASSET_ID = "podcast-transcript:unspecified"
EXTENSION = ".transcript.json"
FORMAT_VERSION = "1.0.0"
FORMAT_NAME = "podcast transcript JSON"
EXTRA_KEY = "extra"

_SEGMENT_FIELDS = ("speaker", "startTime", "endTime", "body")


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------


def _parse_segment(seg: Any, rate: int, *, index: int) -> dict[str, Any]:
    """``{"start", "end" (or None), "body"}`` of one segment, validated."""
    where = f"segments[{index}]"
    if not isinstance(seg, dict):
        raise ValueError(f"{where}: a segment must be an object, got {seg!r}")
    if "startTime" not in seg:
        raise ValueError(f"{where}: missing startTime")
    text = seg.get("body")
    if not isinstance(text, str):
        raise ValueError(f"{where}: body must be a string, got {text!r}")
    speaker = seg.get("speaker")
    if speaker is not None and not isinstance(speaker, str):
        raise ValueError(f"{where}: speaker must be a string, got {speaker!r}")
    start = parse_seconds(seg["startTime"], rate, where=f"{where}.startTime")
    end = None
    if "endTime" in seg:
        end = parse_seconds(seg["endTime"], rate, where=f"{where}.endTime")
        if end < start:
            raise ValueError(f"{where}: endTime {seg['endTime']} is before startTime")
    body: dict[str, Any] = {"text": text, "speaker": speaker}
    extra = {k: plain_json(v) for k, v in seg.items() if k not in _SEGMENT_FIELDS}
    if extra:
        body[EXTRA_KEY] = extra
    return {"start": start, "end": end, "body": body}


def _parse(data: dict, rate: int) -> list[dict[str, Any]]:
    version = data.get("version")
    if version is not None and not isinstance(version, str):
        raise ValueError(f"version must be a string, got {version!r}")
    segments = data.get("segments")
    if not isinstance(segments, list):
        raise ValueError(f"segments must be a list, got {segments!r}")
    parsed = [_parse_segment(s, rate, index=i) for i, s in enumerate(segments)]
    ends = inferred_ends([p["start"].to_fraction() for p in parsed])
    for p, end in zip(parsed, ends):
        if p["end"] is None:
            p["end"] = RationalTime.from_seconds(end, rate=rate)  # a start: exact
            p["body"][END_INFERRED_KEY] = True
    return parsed


def load(
    source: str | bytes | os.PathLike,
    *,
    rate: int = DEFAULT_RATE,
    asset_id: str = DEFAULT_ASSET_ID,
    attribution: str = "anonymous",
    tier: str = DEFAULT_TIER_NAME,
    **_kwargs: Any,
) -> IntervalAnnotationStore:
    """Parse a podcast transcript JSON file, bytes or text into a ``MemoryStore``.

    Args:
        source: Bytes (UTF-8), a path, or inline JSON text.
        rate: Rate of every ``RationalTime`` produced; every time in the file
            must be exact at this rate.
        asset_id: The ``MediaRef.asset_id`` the segments annotate.
        attribution: ``Provenance.was_attributed_to`` of every segment.
        tier: Name of the tier the segments go in.

    Raises:
        ValueError: On malformed input, naming the segment index.
    """
    segments = _parse(load_podcast_json(source, format_name=FORMAT_NAME), rate)

    store = MemoryStore()
    store.add_tier(Tier(tier))
    now = RationalTime.now(rate)
    for seg in segments:
        store.add(
            Annotation(
                id=uuid4(),
                tier=tier,
                reference=MediaRef(
                    asset_id=asset_id, interval=TimeInterval(seg["start"], seg["end"])
                ),
                body=seg["body"],
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


def _has_text(a: Annotation) -> bool:
    return isinstance(a.body, dict) and isinstance(a.body.get("text"), str)


def _segment(a: Annotation, inferred_end: Fraction) -> dict[str, Any]:
    body = a.body
    iv = a.interval
    assert iv is not None  # iter_with_intervals filters
    seg: dict[str, Any] = {}
    speaker = body.get("speaker")
    if isinstance(speaker, str):
        seg["speaker"] = speaker
    seg["startTime"] = seconds_number(iv.start)
    keeps_inferred_end = (
        body.get(END_INFERRED_KEY) is True and iv.end.to_fraction() == inferred_end
    )
    if not keeps_inferred_end:
        seg["endTime"] = seconds_number(iv.end)
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
    anns = [
        a
        for a in iter_with_intervals(store)
        if (tier is None or a.tier == tier) and _has_text(a)
    ]
    anns.sort(key=interval_sort_key)
    ends = inferred_ends([a.interval.start.to_fraction() for a in anns])  # type: ignore[union-attr]
    doc = {
        "version": FORMAT_VERSION,
        "segments": [_segment(a, end) for a, end in zip(anns, ends)],
    }
    blob = dumps_json(doc)
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
    media_types=(),  # the spec's application/json is not distinctive
    body_schema_uris=(BODY_SCHEMA_URI,),
    description=(
        "Podcasting 2.0 podcast:transcript JSON. Timed segments with an "
        "optional speaker, no tier hierarchy."
    ),
)
