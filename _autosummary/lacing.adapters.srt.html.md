# lacing.adapters.srt

SubRip (`.srt`) adapter.

SubRip is the plainest caption format: a flat sequence of cues, each one an
index line, a timing line, and one or more text lines, separated by blank
lines:

```default
1
00:00:01,000 --> 00:00:02,500
Hello world

2
00:00:02,500 --> 00:00:04,000 X1:100 X2:500 Y1:40 Y2:80
Second cue
on two lines
```

We map cues to a single tier named `cues` (override with `tier=`), tier
stereotype `NONE` (SubRip has no hierarchy). Each cue becomes one
`Annotation` whose body (`annot://schema/srt-cue/v1`) holds:

> {“text”: str, “index”: int | None}

`index` is the cue number as written in the source (`None` when a cue has
no index line); it is informational only, since SubRip indices are positional.

Parsing is tolerant of what real files do: UTF-8 with or without a BOM, CRLF
or CR line endings, extra or whitespace-only blank lines between cues, a
missing final blank line, `.` instead of `,` before the milliseconds, a
missing index line, a missing blank line between cues (an index line directly
followed by a timing line starts a new cue), and the trailing `X1:… X2:…
Y1:… Y2:…` position coordinates of some writers, which are ignored. A timing
line that does not parse raises `ValueError` naming its line number.

Lossy fields on dump:
: Provenance, confidence, schema URIs, and tier metadata are dropped, as are
  the source indices (cues are renumbered 1..N in start, then end, order)
  and position coordinates (never kept on load). Any annotation with a
  time interval (any reference kind) and a `text` body is emitted, so WebVTT cues dump to
  SubRip too, losing their WebVTT `id` and `settings`. Blank lines inside
  a cue’s text cannot be represented (a blank line ends a cue) and are
  dropped. Negative times cannot be written and raise `ValueError`.

Time discipline:
: SubRip timestamps are integer milliseconds, `HH:MM:SS,mmm`. They are
  parsed as integers and converted exactly to `RationalTime` at `rate`
  (default 1000; `rate` must hold a millisecond exactly, or loading raises
  `LossyTimeConversionError`). No float is ever involved. On dump, a time
  finer than a millisecond is **truncated** to the millisecond (the floor,
  for non-negative times): truncation is monotone, so every dumped cue keeps
  `start <= end`; a sub-millisecond cue may become zero-length. WebVTT
  uses the same rule (`lacing.adapters._cues`).

There is no formal SubRip specification; the de facto description is
[https://en.wikipedia.org/wiki/SubRip#Format](https://en.wikipedia.org/wiki/SubRip#Format).

### Functions

| [`dump`](#lacing.adapters.srt.dump)(store[, target, tier])             | Write annotations as SubRip.                                        |
|------------------------------------------------------------------------------------------|---------------------------------------------------------------------|
| [`load`](#lacing.adapters.srt.load)(source, \*[, rate, asset_id, ...]) | Parse a SubRip file, or SubRip bytes or text, into a `MemoryStore`. |

### lacing.adapters.srt.dump(store, target=None, , tier=None, \*\*\_kwargs)

Write annotations as SubRip.

* **Parameters:**
  * **store** ([`IntervalAnnotationStore`](lacing.store.base.html.md#lacing.store.base.IntervalAnnotationStore)) – Source store. Every annotation with a time interval (any reference kind) and a
    readable text (`lacing.adapters._common.display_text()`:
    `text`, else `title`) is emitted,
    sorted by start then end, and numbered 1..N in that order.
  * **target** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Output path. If None, returns bytes (UTF-8, no BOM, `\n`).
  * **tier** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Restrict export to this tier. None = export all tiers.
* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### lacing.adapters.srt.load(source, , rate=1000, asset_id='srt:unspecified', attribution='anonymous', tier='cues', \*\*\_kwargs)

Parse a SubRip file, or SubRip bytes or text, into a `MemoryStore`.

* **Parameters:**
  * **source** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes) | [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike)) – Bytes (UTF-8, BOM tolerated), a path, or inline text. A
    `str` containing a newline or `-->` is inline text; any other
    `str` is read as a path when one exists there.
  * **rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Rate of every `RationalTime` produced; must hold a millisecond.
  * **asset_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The `MediaRef.asset_id` the cues annotate.
  * **attribution** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `Provenance.was_attributed_to` of every cue.
  * **tier** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Name of the tier the cues go in.
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – On a malformed cue, naming the line number.
* **Return type:**
  [`IntervalAnnotationStore`](lacing.store.base.html.md#lacing.store.base.IntervalAnnotationStore)
