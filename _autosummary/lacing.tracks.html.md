# lacing.tracks

High-level “track-shaped” facades on top of `lacing`.

A `track` is an opinionated bundle of tiers that shows up in the wild
together. `subtitle` is the canonical example: `sections`,
`lines`, `words` over one audio asset, with a builder that hides
the `Annotation` / `MediaRef` / `Provenance` plumbing and a
query layer that takes `float` seconds instead of `RationalTime`.

These facades sit *on top of* the core store/tier/annotation API —
they don’t introduce new storage. Anything you can build with a
track facade can be built with the raw API; the facade just makes
the common case ergonomic and consistent.

### Functions

| [`from_aligned_track`](#lacing.tracks.from_aligned_track)(track[, store, rate, ...])   | The track as annotations in `store` (a new `MemoryStore` by default).                                                                                                                                       |
|--------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`register_subtitle_schemas`](#lacing.tracks.register_subtitle_schemas)()                     | Deprecated no-op: the section, line and word schemas are built-in bodies, registered when this module (or [`lacing.bodies`](lacing.bodies.html.md#module-lacing.bodies)) is imported. |
| [`to_aligned_track`](#lacing.tracks.to_aligned_track)(store, \*, asset_id[, ...])    | The spans of `store` about `asset_id` as a wire document.                                                                                                                                                   |

### Classes

| [`SubtitleBuilder`](#lacing.tracks.SubtitleBuilder)(store, \*, asset_id[, rate, ...])   | Builder for `(sections, lines, words)` tiers over one asset.   |
|------------------------------------------------------------------------------------------------------|----------------------------------------------------------------|
| [`SubtitleTrack`](#lacing.tracks.SubtitleTrack)(store, \*, asset_id[, rate])          | Read-side facade for `(sections, lines, words)` over an asset. |

### *class* lacing.tracks.SubtitleBuilder(store, , asset_id, rate=1000, was_generated_by='processor:lacing.tracks.subtitle', was_attributed_to='lacing', ensure_tiers=True)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Builder for `(sections, lines, words)` tiers over one asset.

The builder is a context manager *only as a convenience*; it has no
transactional semantics. Calling `.section()` / `.line()` /
`.word()` writes immediately, in the order given.

* **Parameters:**
  * **store** ([`IntervalAnnotationStore`](lacing.store.base.html.md#lacing.store.base.IntervalAnnotationStore)) – Any `IntervalAnnotationStore` (memory, sqlite, postgres).
  * **asset_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The `MediaRef.asset_id` to attach every annotation
    to. Typically a path or content-hash of the audio file.
  * **rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Tick rate for time intervals. Defaults to 1000 (ms).
  * **was_generated_by** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `Provenance.was_generated_by`. Defaults to
    `"processor:lacing.tracks.subtitle"`.
  * **was_attributed_to** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `Provenance.was_attributed_to`.
  * **ensure_tiers** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – When True (default), creates the three tiers if
    they don’t exist. Pass False if your store uses different
    tier names and you’ve created them yourself.

#### add(, tier, body_schema_uri, body, start_s, end_s)

Add an annotation to `tier` with explicit schema/body.

* **Return type:**
  `_BuiltAnnotation`

#### line(text, start_s, end_s, , line_index=None, section='', words=(), extra=None)

Add a lyric line. `words` is an optional list of
`(text, start, end)` or `(text, start, end, confidence)`
tuples that will be inserted on the `words` tier.

* **Return type:**
  `_BuiltAnnotation`

#### section(label, start_s, end_s, , title='', energy='', mood='', extra=None)

Add a song section.

* **Return type:**
  `_BuiltAnnotation`

#### word(text, start_s, end_s, , line_index=None, confidence=None, extra=None)

Add one word. `confidence` goes in the body and on the envelope
(`Annotation.confidence`, which `low_confidence_review` reads).

* **Return type:**
  `_BuiltAnnotation`

### *class* lacing.tracks.SubtitleTrack(store, , asset_id, rate=1000)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Read-side facade for `(sections, lines, words)` over an asset.

Methods take `float` seconds; conversions to `RationalTime` are
handled internally. Returned annotations are sorted by start time.

* **Parameters:**
  * **store** ([`IntervalAnnotationStore`](lacing.store.base.html.md#lacing.store.base.IntervalAnnotationStore)) – Any `IntervalAnnotationStore`.
  * **asset_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – When set, query results are filtered to annotations
    whose `MediaRef.asset_id` equals this value. Pass
    `None` to ignore asset filtering (rarely what you want).
  * **rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Tick rate used to build query intervals.

#### lines_in(start_s, end_s)

Lines that overlap `[start_s, end_s]`.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### sections_covering(t)

Sections whose interval contains `t` (typically one).

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### words_in(start_s, end_s)

Words that overlap `[start_s, end_s]`.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

### lacing.tracks.from_aligned_track(track, store=None, , rate=1000, attribution='anonymous', tiers={'line': 'lines', 'phone': 'phones', 'section': 'sections', 'syllable': 'syllables', 'word': 'words'}, text_tier='text')

The track as annotations in `store` (a new `MemoryStore` by default).

One tier per level present (`tiers` names them, each `INCLUDED_IN` the
nearest coarser level present; a tier the store already has is kept), and
one annotation on `text_tier` holding the text. Millisecond times become
`RationalTime` at `rate`, which must hold a millisecond exactly (else
`LossyTimeConversionError`). One track per asset: a store that already
holds one for `track.asset_id` raises `ValueError`.

* **Return type:**
  [`IntervalAnnotationStore`](lacing.store.base.html.md#lacing.store.base.IntervalAnnotationStore)

### lacing.tracks.register_subtitle_schemas()

Deprecated no-op: the section, line and word schemas are built-in bodies,
registered when this module (or [`lacing.bodies`](lacing.bodies.html.md#module-lacing.bodies)) is imported.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### lacing.tracks.to_aligned_track(store, , asset_id, language=None, quantize=None)

The spans of `store` about `asset_id` as a wire document.

* **Parameters:**
  * **store** ([`IntervalAnnotationStore`](lacing.store.base.html.md#lacing.store.base.IntervalAnnotationStore)) – A store with aligned-span annotations (what
    [`from_aligned_track()`](#lacing.tracks.from_aligned_track) writes) and/or the sections, lines and
    words of a `SubtitleBuilder` (read as `imported` times, with
    the generator as source, since the builder does not say whether
    they were measured).
  * **asset_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The media whose annotations to export.
  * **language** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – BCP 47 tag for the document; defaults to the stored text’s.
  * **quantize** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Literal`](https://docs.python.org/3/library/typing.html#typing.Literal)[`'round'`, `'floor'`, `'ceil'`]]) – `None` (the default) raises `LossyTimeConversionError`
    for a time that is not a whole millisecond; `"round"` (ties to
    even, unlike JavaScript’s `Math.round`), `"floor"` or
    `"ceil"` quantizes it.
* **Return type:**
  [`AlignedTrackV1`](lacing.bodies.aligned_track.html.md#lacing.bodies.aligned_track.AlignedTrackV1)

### Modules

| [`aligned`](lacing.tracks.aligned.html.md#module-lacing.tracks.aligned)   | Aligned tracks: one text, spans at every level, in a store and on the wire.   |
|-----------------------------------------------------------------------------------------|-------------------------------------------------------------------------------|
| [`subtitle`](lacing.tracks.subtitle.html.md#module-lacing.tracks.subtitle) | Subtitle / lyric / caption tracks — the (sections, lines, words) trio.        |
