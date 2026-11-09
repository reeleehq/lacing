# lacing.tracks.aligned

Aligned tracks: one text, spans at every level, in a store and on the wire.

The wire document is [`lacing.bodies.aligned_track.AlignedTrackV1`](lacing.bodies.aligned_track.html.md#lacing.bodies.aligned_track.AlignedTrackV1)
(integer milliseconds, the text stored once, a time-provenance on every span,
exported as JSON Schema for the TypeScript side). A store holds the same spans
as annotations (`RationalTime` intervals) on one tier per level, with the
`annot://schema/aligned-span/v1` body. Two converters, exact both ways:

- [`from_aligned_track()`](#lacing.tracks.aligned.from_aligned_track): a wire document into a store;
- [`to_aligned_track()`](#lacing.tracks.aligned.to_aligned_track): a store into a wire document. It reads the spans
  of the aligned-span body and also, as `imported` times, what
  [`lacing.tracks.subtitle.SubtitleBuilder`](lacing.tracks.subtitle.html.md#lacing.tracks.subtitle.SubtitleBuilder) writes (sections, lines,
  > words), so a store that exists today can be exported without a rewrite.

```pycon
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
```

A store keeps what the document says, so the round trip is exact: the text on
one `aligned-text` annotation, and on each span’s body its `chars` and the
`id` of its parent’s annotation. A store that never held a track (a
`SubtitleBuilder` one) has neither, and an export works them out: the
parent is the innermost enclosing span of a coarser level, and the text is the
lines joined by newlines (else the words, or the syllables, joined by spaces),
a finer span being located, in order, in its parent’s range (ignoring case).
Spans come out in pre-order: a parent, then what it holds, siblings by start,
then end, then level; the round trip is exact for a document in that order
(the validator does not require it, so another order comes back reordered).
A stored `parent_id` or `chars` an edit made inconsistent (a parent
deleted, a span moved) is dropped on export, not an error.

### Module Attributes

| [`LEVEL_TIERS`](#lacing.tracks.aligned.LEVEL_TIERS)   | The tier each level lives on in a store.                  |
|----------------------------------------------------------------|-----------------------------------------------------------|
| [`TEXT_TIER`](#lacing.tracks.aligned.TEXT_TIER)     | The tier of the one annotation that holds a track's text. |

### Functions

| [`from_aligned_track`](#lacing.tracks.aligned.from_aligned_track)(track[, store, rate, ...])   | The track as annotations in `store` (a new `MemoryStore` by default).   |
|--------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------|
| [`to_aligned_track`](#lacing.tracks.aligned.to_aligned_track)(store, \*, asset_id[, ...])    | The spans of `store` about `asset_id` as a wire document.               |

### lacing.tracks.aligned.LEVEL_TIERS *: [Mapping](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [str](https://docs.python.org/3/builtins/stdtypes.html#str)]* *= {'line': 'lines', 'phone': 'phones', 'section': 'sections', 'syllable': 'syllables', 'word': 'words'}*

The tier each level lives on in a store.

### lacing.tracks.aligned.TEXT_TIER *= 'text'*

The tier of the one annotation that holds a track’s text.

### lacing.tracks.aligned.from_aligned_track(track, store=None, , rate=1000, attribution='anonymous', tiers={'line': 'lines', 'phone': 'phones', 'section': 'sections', 'syllable': 'syllables', 'word': 'words'}, text_tier='text')

The track as annotations in `store` (a new `MemoryStore` by default).

One tier per level present (`tiers` names them, each `INCLUDED_IN` the
nearest coarser level present; a tier the store already has is kept), and
one annotation on `text_tier` holding the text. Millisecond times become
`RationalTime` at `rate`, which must hold a millisecond exactly (else
`LossyTimeConversionError`). One track per asset: a store that already
holds one for `track.asset_id` raises `ValueError`.

* **Return type:**
  [`IntervalAnnotationStore`](lacing.store.base.html.md#lacing.store.base.IntervalAnnotationStore)

### lacing.tracks.aligned.to_aligned_track(store, , asset_id, language=None, quantize=None)

The spans of `store` about `asset_id` as a wire document.

* **Parameters:**
  * **store** ([`IntervalAnnotationStore`](lacing.store.base.html.md#lacing.store.base.IntervalAnnotationStore)) – A store with aligned-span annotations (what
    [`from_aligned_track()`](#lacing.tracks.aligned.from_aligned_track) writes) and/or the sections, lines and
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
