"""OpenTimelineIO (OTIO) adapter — NLE / video editing interchange.

OTIO is the Academy Software Foundation's standard for video timeline
interchange. Per OSS-DOC, lacing's ``RationalTime`` design is directly
inspired by OTIO's — this adapter is the place where that parity pays
off.

Mapping
-------
OTIO                                     ↔ lacing
``Timeline``                             ↔ a project (one OTIO file = one store)
``Track``                                ↔ a tier (track ``name`` becomes tier name)
``Clip``                                 ↔ ``Annotation`` (interval = source_range
                                            offset onto the track timeline)
``Clip.media_reference.target_url``      ↔ ``MediaRef.asset_id``
``Marker`` (on Track or Clip)            ↔ point ``Annotation``
``Clip.metadata`` / ``Marker.metadata``  ↔ ``body['otio_metadata']``
``MarkerColor``                          ↔ ``body['color']``

Time
----
OTIO ``RationalTime`` has lacing's ``(value, rate)`` shape but stores both
members as doubles. No time crosses this adapter as float seconds
(lacing#134):

- **dump** writes each lacing time with its own integers,
  ``opentime.RationalTime(value=t.value, rate=t.rate)``. Gap and clip
  durations are computed exactly, at the least common multiple of the
  rates involved, so a 48 kHz or ``30000``-rate NTSC timeline survives.
  Integers at or above 2**53 are not exact as doubles and raise
  ``LossyTimeConversionError``.
- **load** turns each OTIO double into an exact ``Fraction`` once, at the
  boundary (:func:`_otio_double_to_fraction`): an integral double is that
  integer; otherwise the simplest rational with denominator at most
  ``1001`` whose nearest double *is* that double, which recovers values
  such as ``1/3`` and NTSC rates written as ``24000/1001``
  (``23.976023976023978``); failing that, the double's exact binary value.
  Track positions accumulate as ``Fraction`` seconds and are quantised once
  to the requested ``rate`` with ``RationalTime.from_seconds``, which raises
  ``LossyTimeConversionError`` when a time is not exact at that rate (it
  never rounds).

Lossy on dump
-------------
- Per-annotation provenance (``was_attributed_to``, ``was_derived_from``)
  is dropped — OTIO carries no per-clip annotator field.
- Confidence is dropped — OTIO has no equivalent.
- Track effects + transitions are dropped — out of lacing's scope.
- Clips are emitted with an ``ExternalReference`` whose ``target_url``
  is the ``MediaRef.asset_id``.

Spec: https://opentimelineio.readthedocs.io/
"""

from __future__ import annotations

import math
import os
from fractions import Fraction
from typing import Any
from uuid import uuid4

from lacing.adapters import adapter_generator_id, register_adapter
from lacing.adapters._common import iter_with_media_intervals
from lacing.model import Annotation, MediaRef, Provenance
from lacing.store import IntervalAnnotationStore, MemoryStore
from lacing.tier import Tier
from lacing.time import (
    DEFAULT_RATE,
    LossyTimeConversionError,
    RationalTime,
    TimeInterval,
)

ADAPTER_NAME = "otio"
# 1.1.0: dumped times keep lacing's own rate instead of milliseconds (lacing#134).
ADAPTER_VERSION = "1.1.0"
GENERATED_BY = str(adapter_generator_id(ADAPTER_NAME, ADAPTER_VERSION))
BODY_SCHEMA_URI_CLIP = "annot://schema/otio-clip/v1"
BODY_SCHEMA_URI_MARKER = "annot://schema/otio-marker/v1"
DEFAULT_ASSET_ID = "otio:unspecified"

_MAX_RECOVERED_DENOMINATOR = 1001
"""Largest denominator :func:`_otio_double_to_fraction` recovers from a
non-integral double. ``1001`` covers the NTSC family (``k * 1000 / 1001``)."""

_MAX_EXACT_DOUBLE_INT = 2**53
"""Integers with magnitude below this are exactly representable as doubles."""


def _require_otio():
    try:
        import opentimelineio
    except ImportError as exc:
        raise ImportError(
            "OTIO adapter requires opentimelineio. Install with: "
            "pip install 'lacing[otio]'  (or directly: pip install opentimelineio)"
        ) from exc
    return opentimelineio


def _otio_double_to_fraction(x: float) -> Fraction:
    """The exact rational an OTIO double stands for — the load boundary rule.

    - An integral double is that integer (the usual case: ``24.0``,
      ``48000.0``, ``1001.0``).
    - Otherwise, the simplest rational with denominator at most
      ``_MAX_RECOVERED_DENOMINATOR`` whose nearest double is exactly ``x``.
      Rationals with such small denominators are far apart compared with the
      spacing of doubles, so at most one of them rounds to ``x``: this
      recovers ``1/3`` from ``0.333...`` and ``24000/1001`` from
      ``23.976023976023978``, the values the writer meant.
    - Otherwise, the exact binary value of ``x``.

    No step rounds: every result converts back to ``x`` exactly.
    """
    exact = Fraction(x)  # exact binary value; raises on nan/inf
    if exact.denominator == 1:
        return exact
    simple = exact.limit_denominator(_MAX_RECOVERED_DENOMINATOR)
    if float(simple) == x:
        return simple
    return exact


def _otio_seconds(t) -> Fraction:
    """An ``opentime.RationalTime`` as exact ``Fraction`` seconds."""
    return _otio_double_to_fraction(t.value) / _otio_double_to_fraction(t.rate)


def _otio_rationaltime_to_lacing(t, rate: int) -> RationalTime:
    """Convert an ``opentime.RationalTime`` to lacing's, at ``rate``.

    Raises ``LossyTimeConversionError`` when the time is not exact at ``rate``.
    """
    return RationalTime.from_seconds(_otio_seconds(t), rate=rate)


def _lacing_to_otio_rationaltime(t: RationalTime, otio_module) -> Any:
    """Convert a lacing ``RationalTime`` to OTIO's, keeping its integers.

    Raises ``LossyTimeConversionError`` if ``value`` or ``rate`` is too large
    to be held exactly by OTIO's doubles.
    """
    if abs(t.value) >= _MAX_EXACT_DOUBLE_INT or t.rate >= _MAX_EXACT_DOUBLE_INT:
        raise LossyTimeConversionError(
            f"{t!r} cannot be held exactly by OTIO's double-based RationalTime"
        )
    return otio_module.opentime.RationalTime(value=t.value, rate=t.rate)


def _exact_at_common_rate(seconds: Fraction, *times: RationalTime) -> RationalTime:
    """``seconds`` at the least common multiple of the rates of ``times``.

    Exact by construction when ``seconds`` is a sum or difference of
    ``times``.
    """
    return RationalTime.from_seconds(seconds, rate=math.lcm(*(t.rate for t in times)))


def _media_url(clip) -> str | None:
    media_ref = getattr(clip, "media_reference", None)
    if media_ref is None:
        return None
    target_url = getattr(media_ref, "target_url", None)
    if target_url:
        return str(target_url)
    return None


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------


def load(
    source: str | bytes | os.PathLike,
    *,
    rate: int = DEFAULT_RATE,
    asset_id: str | None = None,
    attribution: str = "anonymous",
    **_kwargs: Any,
) -> IntervalAnnotationStore:
    """Load an OTIO file/JSON into a ``MemoryStore``.

    Each track becomes a tier. Each clip becomes one ``Annotation`` with
    ``MediaRef`` pointing at the clip's media reference (or the
    ``asset_id`` override). Markers on the timeline or on a clip become point
    ``Annotation``s on a ``markers`` tier; markers on a track stay on that
    track's tier, which is where :func:`dump` writes a tier's points.

    Args:
        source: Path or bytes containing OTIO JSON.
        rate: Rate of the loaded times. Every OTIO time must be exact at
            it; otherwise ``LossyTimeConversionError`` is raised.
        asset_id: Override media reference for every clip. None = use
            each clip's own ``media_reference.target_url``.
        attribution: ``Provenance.was_attributed_to`` value.
    """
    otio = _require_otio()
    timeline = _open_timeline(source, otio)

    store = MemoryStore()
    seen_tiers: set[str] = set()
    now = RationalTime.now(rate)

    def _ensure_tier(name: str) -> None:
        if name not in seen_tiers:
            store.add_tier(Tier(name))
            seen_tiers.add(name)

    # --- timeline-level markers --------------------------------------
    for marker in getattr(timeline.tracks, "markers", []) or []:
        _add_marker_annotation(
            store,
            marker,
            tier_name="markers",
            asset_id=asset_id or DEFAULT_ASSET_ID,
            rate=rate,
            attribution=attribution,
            now=now,
            ensure_tier=_ensure_tier,
            otio_module=otio,
        )

    # --- per-track clips + markers -----------------------------------
    for track in timeline.tracks:
        tier_name = track.name or "untitled"
        _ensure_tier(tier_name)

        # Walk children, accumulating the track position as exact seconds.
        cursor = Fraction(0)
        for child in track:
            if hasattr(child, "source_range") and child.source_range is not None:
                duration = _otio_seconds(child.source_range.duration)
            elif hasattr(child, "duration"):
                try:
                    duration = _otio_seconds(child.duration())
                except Exception:  # pragma: no cover  — defensive
                    duration = Fraction(0)
            else:
                duration = Fraction(0)

            schema = getattr(child, "schema_name", lambda: "")()
            if schema.startswith("Clip"):
                clip_asset = asset_id or _media_url(child) or f"otio:clip:{child.name}"
                interval = TimeInterval(
                    RationalTime.from_seconds(cursor, rate=rate),
                    RationalTime.from_seconds(cursor + duration, rate=rate),
                )

                clip_metadata = (
                    dict(child.metadata) if hasattr(child, "metadata") else {}
                )
                store.add(
                    Annotation(
                        id=uuid4(),
                        tier=tier_name,
                        reference=MediaRef(asset_id=clip_asset, interval=interval),
                        body={
                            "name": child.name,
                            "kind": "clip",
                            "otio_metadata": clip_metadata,
                        },
                        body_schema_uri=BODY_SCHEMA_URI_CLIP,
                        provenance=Provenance(
                            was_generated_by=GENERATED_BY,
                            was_attributed_to=attribution,
                            generated_at_time=now,
                            activity="import",
                        ),
                    )
                )

                # Markers on this clip — placed at clip-relative source_range start
                # offset onto the track timeline.
                if child.source_range is not None:
                    clip_source_start = _otio_seconds(child.source_range.start_time)
                else:
                    clip_source_start = Fraction(0)
                for marker in getattr(child, "markers", []) or []:
                    marker_start_in_clip = _otio_seconds(marker.marked_range.start_time)
                    marker_track_pos = cursor + (
                        marker_start_in_clip - clip_source_start
                    )
                    _add_marker_annotation(
                        store,
                        marker,
                        tier_name="markers",
                        asset_id=clip_asset,
                        rate=rate,
                        attribution=attribution,
                        now=now,
                        track_pos=marker_track_pos,
                        ensure_tier=_ensure_tier,
                        otio_module=otio,
                    )

            cursor += duration

        # Markers on the track itself: where dump puts a tier's point
        # annotations, so they come back on that tier (lacing#132).
        for marker in getattr(track, "markers", []) or []:
            _add_marker_annotation(
                store,
                marker,
                tier_name=tier_name,
                asset_id=asset_id or DEFAULT_ASSET_ID,
                rate=rate,
                attribution=attribution,
                now=now,
                ensure_tier=_ensure_tier,
                otio_module=otio,
            )

    return store


def _add_marker_annotation(
    store: MemoryStore,
    marker,
    *,
    tier_name: str,
    asset_id: str,
    rate: int,
    attribution: str,
    now: RationalTime,
    ensure_tier,
    otio_module,
    track_pos: Fraction | None = None,
) -> None:
    """Insert a point Annotation for an OTIO Marker.

    ``track_pos`` is the marker's track position in exact seconds; ``None``
    means use the marker's own ``marked_range.start_time``.
    """
    ensure_tier(tier_name)

    if track_pos is not None:
        t = RationalTime.from_seconds(track_pos, rate=rate)
    else:
        t = _otio_rationaltime_to_lacing(marker.marked_range.start_time, rate)

    color = getattr(marker, "color", None)
    color_str = str(color) if color else None

    metadata = dict(marker.metadata) if hasattr(marker, "metadata") else {}

    store.add(
        Annotation(
            id=uuid4(),
            tier=tier_name,
            reference=MediaRef(asset_id=asset_id, interval=TimeInterval.point(t)),
            body={
                "name": marker.name,
                "kind": "marker",
                "color": color_str,
                "otio_metadata": metadata,
            },
            body_schema_uri=BODY_SCHEMA_URI_MARKER,
            provenance=Provenance(
                was_generated_by=GENERATED_BY,
                was_attributed_to=attribution,
                generated_at_time=now,
                activity="import",
            ),
        )
    )


def _open_timeline(source: str | bytes | os.PathLike, otio_module):
    if isinstance(source, (bytes, bytearray)):
        text = bytes(source).decode("utf-8")
        return otio_module.adapters.read_from_string(text, adapter_name="otio_json")
    if isinstance(source, str):
        s = source.lstrip()
        if s.startswith("{"):
            return otio_module.adapters.read_from_string(
                source, adapter_name="otio_json"
            )
    return otio_module.adapters.read_from_file(os.fspath(source))


# ---------------------------------------------------------------------------
# dump
# ---------------------------------------------------------------------------


def _otio_name(ann: Annotation) -> str:
    """The body's ``name`` for an OTIO clip or marker, ``""`` when it has none:
    OTIO's bindings refuse ``None`` (lacing#132)."""
    name = ann.body.get("name")
    return name if isinstance(name, str) else ""


def dump(
    store: IntervalAnnotationStore,
    target: str | os.PathLike | None = None,
    *,
    name: str = "lacing",
    **_kwargs: Any,
) -> bytes | None:
    """Serialize ``store`` as an OTIO file.

    Each tier becomes one Track. Annotations whose body has
    ``kind=='marker'`` are emitted as ``Marker``s on the track at their
    interval start. Annotations whose body has ``kind=='clip'`` (or no
    explicit kind) become Clips with ``ExternalReference`` to the
    ``asset_id`` and ``source_range`` matching the lacing interval.

    Note: lacing intervals are absolute positions; OTIO clips are
    sequential within a track. We sort + place clips back-to-back per
    tier; gaps between intervals become explicit ``Gap`` items.
    """
    otio = _require_otio()

    timeline = otio.schema.Timeline(name=name)
    by_tier: dict[str, list[Annotation]] = {}
    for ann in iter_with_media_intervals(store):
        by_tier.setdefault(ann.tier, []).append(ann)

    declared_tiers = []
    tiers_iter = getattr(store, "tiers", None)
    if callable(tiers_iter):
        declared_tiers = [t.name for t in tiers_iter()]
    referenced = list(by_tier.keys())
    seen: set[str] = set()
    ordered: list[str] = []
    for n in declared_tiers + referenced:
        if n not in seen:
            seen.add(n)
            ordered.append(n)

    for tier_name in ordered:
        anns = by_tier.get(tier_name, [])
        anns_sorted = sorted(anns, key=lambda a: a.interval.start.to_fraction())

        track = otio.schema.Track(name=tier_name)
        cursor: RationalTime | None = None  # end of the last item on the track
        for ann in anns_sorted:
            iv = ann.interval
            assert iv is not None
            start, end = iv.start, iv.end

            kind = ann.body.get("kind") if isinstance(ann.body, dict) else None
            if kind == "marker" or iv.is_point:
                # Markers can't go on a Track directly without a host —
                # attach to a Gap or the track itself.
                marker = otio.schema.Marker(
                    name=_otio_name(ann),
                    marked_range=otio.opentime.TimeRange(
                        start_time=_lacing_to_otio_rationaltime(start, otio),
                        duration=_lacing_to_otio_rationaltime(
                            RationalTime.zero(start.rate), otio
                        ),
                    ),
                )
                track.markers.append(marker)
                continue

            # Insert a gap if needed.
            if cursor is None:
                cursor = RationalTime.zero(start.rate)
            if start > cursor:
                gap = _exact_at_common_rate(
                    start.to_fraction() - cursor.to_fraction(), start, cursor
                )
                track.append(
                    otio.schema.Gap(
                        source_range=otio.opentime.TimeRange(
                            start_time=_lacing_to_otio_rationaltime(
                                RationalTime.zero(gap.rate), otio
                            ),
                            duration=_lacing_to_otio_rationaltime(gap, otio),
                        ),
                    )
                )
                cursor = start

            duration = _exact_at_common_rate(
                end.to_fraction() - start.to_fraction(), start, end
            )
            asset_url = ann.reference.asset_id  # type: ignore[union-attr]
            clip = otio.schema.Clip(
                name=_otio_name(ann),
                media_reference=otio.schema.ExternalReference(target_url=asset_url),
                source_range=otio.opentime.TimeRange(
                    start_time=_lacing_to_otio_rationaltime(
                        RationalTime.zero(duration.rate), otio
                    ),
                    duration=_lacing_to_otio_rationaltime(duration, otio),
                ),
            )
            track.append(clip)
            cursor = end

        timeline.tracks.append(track)

    if target is None:
        text = otio.adapters.write_to_string(timeline, adapter_name="otio_json")
        return text.encode("utf-8")

    otio.adapters.write_to_file(timeline, os.fspath(target))
    return None


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------


register_adapter(
    name=ADAPTER_NAME,
    version=ADAPTER_VERSION,
    load=load,
    dump=dump,
    extensions=(".otio",),
    media_types=("application/vnd.otio+json",),
    body_schema_uris=(BODY_SCHEMA_URI_CLIP, BODY_SCHEMA_URI_MARKER),
    description=(
        "OpenTimelineIO (Academy Software Foundation). Maps tracks to tiers, "
        "clips to interval annotations, and markers to point annotations. "
        "Times keep their integer (value, rate) both ways — no float seconds."
    ),
)
