# lacing.adapters.podcast_transcript

Podcasting 2.0 `podcast:transcript` JSON adapter.

The JSON transcript format of the Podcast Namespace: a version and a list of
timed dialogue segments, at any granularity from whole turns down to single
words:

```default
{
  "version": "1.0.0",
  "segments": [
    {"speaker": "Darth Vader", "startTime": 0.5, "endTime": 0.75, "body": "I"},
    {"speaker": "Darth Vader", "startTime": 1, "endTime": 1.25, "body": "am"}
  ]
}
```

Spec: the `<podcast:transcript>` tag,
[https://github.com/Podcastindex-org/podcast-namespace/blob/main/docs/tags/transcript.md](https://github.com/Podcastindex-org/podcast-namespace/blob/main/docs/tags/transcript.md),
and its JSON section in
[https://github.com/Podcastindex-org/podcast-namespace/blob/main/docs/examples/transcripts/transcripts.md#json](https://github.com/Podcastindex-org/podcast-namespace/blob/main/docs/examples/transcripts/transcripts.md#json)
(elements `version`, `segments`, `speaker`, `startTime`, `endTime`
“if available”, `body`).

We map segments to a single tier named `segments` (override with
`tier=`), stereotype `NONE` (the format has no hierarchy). Each segment
becomes one `Annotation` whose body (`annot://schema/podcast-transcript-segment/v1`)
holds:

```default
{"text": str, "speaker": str | None}
```

plus `"end_inferred": True` when the segment had no `endTime`, and
`"extra": {...}` holding any other fields of the segment with their values
(numbers that are not times as plain JSON numbers of the same value; see
“Numbers” below).

End times:
: `endTime` is optional in the spec. A segment without one (or with
  `"endTime": null`) ends where the next *later* segment starts (segments
  sharing a start all end at the next later start); the last one is a
  point (`start == end`). The body records that the end was inferred,
  and [`dump()`](#lacing.adapters.podcast_transcript.dump) leaves `endTime` out again while the end is still the
  inferred one, so such files round-trip. A `null` `speaker` is an
  absent one, and the dump leaves it out.

Time discipline:
: Times are JSON numbers of seconds. They are read as exact `Decimal`
  values (`json.loads(..., parse_float=Decimal)`, never `float`), then
  converted exactly to `RationalTime`. With `rate=None` (the default)
  the rate is the smallest power of ten, at least 1000, that holds every
  time in the file exactly: `1.001` is `RationalTime(1001, 1000)`, a
  file with `0.0000625` (a sample at 16 kHz) is read at rate `10**7`,
  and JavaScript float noise such as `0.30000000000000004` at
  `10**17`, so every file is read without loss. An explicit `rate`
  that cannot hold a time (`0.0005` at rate 1000) raises
  `LossyTimeConversionError` naming the segment and the rate that would
  hold every time. On dump a time is written as an exact decimal when it
  has a terminating expansion, else truncated to the millisecond, which
  keeps the order of times (see
  `lacing.adapters._podcast.seconds_number()`).

Numbers:
: A number that is not a time is kept as the nearest `float` and written
  back as that value (`1.50` is written `1.5`; a PHP-style
  `48.858092999999997` becomes `48.858093`, as any JSON reader reads it).
  `NaN`, `Infinity` and `1e400` (not finite) are refused on load,
  naming the segment and the field. Bodies stay plain JSON, which a SQLite store
  or the server needs.

Lossy fields on dump:
: Provenance, confidence, schema URIs and tier metadata are dropped. The
  `version` is always written as `1.0.0`; other top-level fields of a
  loaded file are not kept. Any annotation with a time interval (any
  reference kind) and a string `text` body is written as a segment, with
  its `speaker` when the body has a string one, so SubRip, WebVTT and LRC
  cues dump to a transcript too (losing their own body fields). Segments
  are written in start, then end, order.

Media type and extension:
: The spec serves transcripts as plain `application/json`, which says
  nothing about the format, so this adapter registers no media type (a
  `find_adapter(media_type="application/json")` finds no adapter). It
  registers the compound extension `.transcript.json`; a bare `.json`
  stays with the W3C Web Annotation adapter. Pass `format=` otherwise.

Malformed input raises `ValueError` naming the segment index
(`segments[3]`): a document that is not a JSON object, `segments` missing
or not a list, a segment that is not an object, a missing or non-string
`body`, a non-string `speaker`, a `startTime` that is missing, an
`endTime` or `startTime` that is not a number, negative or not finite, an
`endTime` before its `startTime`, a number in another field that a float
cannot hold exactly, or a non-string `version`.

### Functions

| [`dump`](#lacing.adapters.podcast_transcript.dump)(store[, target, tier])                       | Write annotations as podcast transcript JSON.                             |
|----------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------|
| [`load`](#lacing.adapters.podcast_transcript.load)(source, \*[, rate, rounding, asset_id, ...]) | Parse a podcast transcript JSON file, bytes or text into a `MemoryStore`. |

### lacing.adapters.podcast_transcript.dump(store, target=None, , tier=None, \*\*\_kwargs)

Write annotations as podcast transcript JSON.

* **Parameters:**
  * **store** ([`IntervalAnnotationStore`](lacing.store.base.html.md#lacing.store.base.IntervalAnnotationStore)) – Source store. Every annotation with a time interval (any
    reference kind) and a string `text` body is written as a
    segment, sorted by start then end.
  * **target** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Output path. If None, returns bytes (UTF-8 JSON).
  * **tier** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Restrict export to this tier. None = export all tiers.
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – For a negative time, which the format cannot hold.
* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### lacing.adapters.podcast_transcript.load(source, , rate=None, rounding=None, asset_id='podcast-transcript:unspecified', attribution='anonymous', tier='segments', \*\*\_kwargs)

Parse a podcast transcript JSON file, bytes or text into a `MemoryStore`.

* **Parameters:**
  * **source** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes) | [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike)) – Bytes (UTF-8), a path, or inline JSON text.
  * **rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Rate of every `RationalTime` produced. `None` (the default)
    picks the smallest power of ten, at least 1000, at which every
    time in the file is exact, up to `10**9` (a store’s limit); an
    explicit rate must hold every time exactly, unless `rounding`.
  * **rounding** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – `None` (exact or raise), or a
    [`from_seconds_lossy()`](lacing.time.html.md#lacing.time.RationalTime.from_seconds_lossy) mode
    (`"round"`, `"floor"`, `"ceil"`) to quantise times instead,
    for files with float noise (`12.300000000000001`).
  * **asset_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The `MediaRef.asset_id` the segments annotate.
  * **attribution** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `Provenance.was_attributed_to` of every segment.
  * **tier** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Name of the tier the segments go in.
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – On malformed input, naming the segment index.
* **Return type:**
  [`IntervalAnnotationStore`](lacing.store.base.html.md#lacing.store.base.IntervalAnnotationStore)
