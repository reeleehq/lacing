# lacing.adapters.otio

OpenTimelineIO (OTIO) adapter — NLE / video editing interchange.

OTIO is the Academy Software Foundation’s standard for video timeline
interchange. Per OSS-DOC, lacing’s `RationalTime` design is directly
inspired by OTIO’s — this adapter is the place where that parity pays
off.

## Mapping

OTIO                                     ↔ lacing
`Timeline`                             ↔ a project (one OTIO file = one store)
`Track`                                ↔ a tier (track `name` becomes tier name)
`Clip`                                 ↔ `Annotation` (interval = source_range

> offset onto the track timeline)

`Clip.media_reference.target_url`      ↔ `MediaRef.asset_id`
`Marker` (on Track or Clip)            ↔ point `Annotation`
`Clip.metadata` / `Marker.metadata`  ↔ `body['otio_metadata']`
`MarkerColor`                          ↔ `body['color']`

## Time

OTIO `RationalTime` has lacing’s `(value, rate)` shape but stores both
members as doubles. No time crosses this adapter as float seconds
(lacing#134):

- **dump** writes each lacing time with its own integers,
  `opentime.RationalTime(value=t.value, rate=t.rate)`. Gap and clip
  durations are computed exactly, at the least common multiple of the
  rates involved, so a 48 kHz or `30000`-rate NTSC timeline survives.
  Integers at or above 2\*\*53 are not exact as doubles and raise
  `LossyTimeConversionError`.
- **load** turns each OTIO double into an exact `Fraction` once, at the
  boundary (`_otio_double_to_fraction()`): an integral double is that
  integer; otherwise the rational closest to it with denominator at most
  `1001` whose nearest double *is* that double, which recovers values
  such as `1/3` and NTSC rates written as `24000/1001`
  (`23.976023976023978`); failing that, the double’s exact binary value.
  Track positions accumulate as `Fraction` seconds and are quantised once
  to the requested `rate` with `RationalTime.from_seconds`, which raises
  `LossyTimeConversionError` when a time is not exact at that rate (it
  never rounds).

## Lossy on dump

- Per-annotation provenance (`was_attributed_to`, `was_derived_from`)
  is dropped — OTIO carries no per-clip annotator field.
- Confidence is dropped — OTIO has no equivalent.
- Track effects + transitions are dropped — out of lacing’s scope.
- Clips are emitted with an `ExternalReference` whose `target_url`
  is the `MediaRef.asset_id`.

Spec: [https://opentimelineio.readthedocs.io/](https://opentimelineio.readthedocs.io/)

### Functions

| [`dump`](#lacing.adapters.otio.dump)(store[, target, name])                     | Serialize `store` as an OTIO file.           |
|--------------------------------------------------------------------------------------------------|----------------------------------------------|
| [`load`](#lacing.adapters.otio.load)(source, \*[, rate, asset_id, attribution]) | Load an OTIO file/JSON into a `MemoryStore`. |

### lacing.adapters.otio.dump(store, target=None, , name='lacing', \*\*\_kwargs)

Serialize `store` as an OTIO file.

Each tier becomes one Track. Annotations whose body has
`kind=='marker'` are emitted as `Marker``s on the track at their
interval start. Annotations whose body has ``kind=='clip'` (or no
explicit kind) become Clips with `ExternalReference` to the
`asset_id` and `source_range` matching the lacing interval.

#### NOTE
lacing intervals are absolute positions; OTIO clips are
sequential within a track. We sort + place clips back-to-back per
tier; gaps between intervals become explicit `Gap` items.

* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### lacing.adapters.otio.load(source, , rate=24000, asset_id=None, attribution='anonymous', \*\*\_kwargs)

Load an OTIO file/JSON into a `MemoryStore`.

Each track becomes a tier. Each clip becomes one `Annotation` with
`MediaRef` pointing at the clip’s media reference (or the
`asset_id` override). Markers on the timeline or on a clip become point
`Annotation``s on a ``markers` tier; markers on a track stay on that
track’s tier, which is where [`dump()`](#lacing.adapters.otio.dump) writes a tier’s points.

* **Parameters:**
  * **source** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes) | [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike)) – Path or bytes containing OTIO JSON.
  * **rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Rate of the loaded times. Every OTIO time must be exact at
    it; otherwise `LossyTimeConversionError` is raised.
  * **asset_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Override media reference for every clip. None = use
    each clip’s own `media_reference.target_url`.
  * **attribution** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `Provenance.was_attributed_to` value.
* **Return type:**
  [`IntervalAnnotationStore`](lacing.store.base.html.md#lacing.store.base.IntervalAnnotationStore)
