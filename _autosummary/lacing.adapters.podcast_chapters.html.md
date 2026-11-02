# lacing.adapters.podcast_chapters

Podcasting 2.0 `podcast:chapters` JSON adapter.

The JSON chapters format of the Podcast Namespace (version 1.2): a version,
optional episode fields, and a list of chapters, each with a start time and
optional end time, title, image, link, table-of-contents flag and location:

```default
{
  "version": "1.2.0",
  "author": "John Doe",
  "title": "Episode 7 - Making Progress",
  "chapters": [
    {"startTime": 0, "title": "Intro"},
    {"startTime": 168, "title": "Hearing Aids", "img": "https://example.com/a.jpg"},
    {"startTime": 4826, "toc": false,
     "location": {"name": "Eiffel Tower, Paris", "geo": "geo:48.858093,2.294694"}}
  ]
}
```

Spec: “JSON Chapters Format”, version 1.2,
[https://github.com/Podcastindex-org/podcast-namespace/blob/main/docs/examples/chapters/jsonChapters.md](https://github.com/Podcastindex-org/podcast-namespace/blob/main/docs/examples/chapters/jsonChapters.md),
referenced by the `<podcast:chapters>` tag,
[https://github.com/Podcastindex-org/podcast-namespace/blob/main/docs/tags/chapters.md](https://github.com/Podcastindex-org/podcast-namespace/blob/main/docs/tags/chapters.md).

Tiers and bodies:

- `chapters` (stereotype `NONE`; override with `tier=`): one annotation
  per chapter, body `annot://schema/podcast-chapter/v1`: every field of the
  chapter object except `startTime` and `endTime`, with its value and in
  file order (`title`, `img`, `url`, `toc`, `location`, and any
  field the spec does not name, such as the `value` of the spec’s complex
  example), so a chapter round-trips to the same JSON value (see “Numbers”).
  A `null` `title`, `img`, `url`, `toc` or `location` is an
  absent one: it is left out on load, and the dump leaves it out too.
  `"end_inferred": true` is added when the chapter had no `endTime` (a
  chapter that already has a field of that name is refused).
- `episode` (stereotype `NONE`; override with `episode_tier=`):
  **one** metadata annotation, a point at time 0, body
  `annot://schema/podcast-chapters-episode/v1`
  `{"version": str | None, "fields": {...}}`, where `fields` holds every
  other top-level field (`author`, `title`, `podcastName`,
  `description`, `fileName`, `waypoints`, and any unnamed one) with
  its value and in file order. These describe the file, not a chapter, so they live on
  one annotation rather than in every chapter body, the way the LRC adapter
  keeps its ID tags; a store from another format dumps without inventing any.

End times:
: `endTime` is optional, and `null` is the same as absent. A chapter
  without one ends where the next *later*
  chapter starts (chapters sharing a start all end at the next later
  start), whatever the order of the file (the spec assumes ascending
  `startTime`); the last chapter is a point (`start == end`).
  [`dump()`](#lacing.adapters.podcast_chapters.dump) leaves `endTime` out again for a chapter whose end was
  inferred and is still the one a reader would infer, and writes it
  otherwise, so a file round-trips and an edited end is kept.

Time discipline:
: Times are JSON numbers of seconds (“float precision” in the spec). They
  are read as exact `Decimal` values (`json.loads(...,
  parse_float=Decimal)`, never `float`), then converted exactly to
  `RationalTime`. With `rate=None` (the default) the rate is the
  smallest power of ten, at least 1000, that holds every time in the file
  exactly: `1.001` is `RationalTime(1001, 1000)`, and `0.0000625` or
  `0.30000000000000004` raise the rate rather than lose precision. An
  explicit `rate` that cannot hold a time raises
  `LossyTimeConversionError` naming the chapter and the rate that would
  hold every time. On dump a time is written as an exact decimal when it
  has a terminating expansion, else truncated to the millisecond, which
  keeps the order of times (see
  `lacing.adapters._podcast.seconds_number()`).

Numbers:
: A number that is not a time is kept as the nearest `float` and written
  back as that value (`1.50` is written `1.5`; a PHP-style
  `48.858092999999997` becomes `48.858093`, as any JSON reader reads it).
  `NaN`, `Infinity` and `1e400` (not finite) are refused on load,
  naming the chapter and the field. Bodies stay plain JSON, which a SQLite store
  or the server needs.

Lossy fields on dump:
: Provenance, confidence, schema URIs and tier metadata are dropped. The
  `version` is the episode annotation’s, else `1.2.0`. Without `tier=`,
  the annotations written as chapters are those with the chapter body
  schema; with `tier=`, every annotation of that tier with a time interval
  and an object body, its `title` taken from a string `title` field, else
  from a string `text` field (a WebVTT chapters track, a SubRip cue).
  Chapters are written in start, then end, order. Top-level fields are
  written before `chapters`.

Media type and extension:
: The spec says a chapters file “should be served with a Content-type of
  ‘application/json+chapters’”, which this adapter registers. It does not
  register the generic `application/json`. Its extension is the compound
  `.chapters.json`; a bare `.json` stays with the W3C Web Annotation
  adapter.

Malformed input raises `ValueError` naming the chapter index
(`chapters[3]`): a document that is not a JSON object, `chapters` missing
or not a list, a chapter that is not an object, a `startTime` or
`endTime` that is not a number, negative or not finite, an `endTime`
before its `startTime`, a `title`, `img` or `url` that is not a
string, a `toc` that is not a boolean, a `location` that is not an
object, a number a float cannot hold exactly, or a non-string `version`.

### Functions

| [`dump`](#lacing.adapters.podcast_chapters.dump)(store[, target, tier])                       | Write annotations as podcast chapters JSON.                             |
|----------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------|
| [`load`](#lacing.adapters.podcast_chapters.load)(source, \*[, rate, rounding, asset_id, ...]) | Parse a podcast chapters JSON file, bytes or text into a `MemoryStore`. |

### lacing.adapters.podcast_chapters.dump(store, target=None, , tier=None, \*\*\_kwargs)

Write annotations as podcast chapters JSON.

* **Parameters:**
  * **store** ([`IntervalAnnotationStore`](lacing.store.base.html.md#lacing.store.base.IntervalAnnotationStore)) – Source store. Chapters are its annotations with a time
    interval and the chapter body schema (or, with `tier`, every
    annotation of that tier with a time interval and an object body),
    sorted by start then end. The episode metadata annotation, if
    any, gives the version and top-level fields.
  * **target** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Output path. If None, returns bytes (UTF-8 JSON).
  * **tier** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Write the annotations of this tier as chapters (see above).
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – For a negative time, or for more than one episode
      metadata annotation.
* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### lacing.adapters.podcast_chapters.load(source, , rate=None, rounding=None, asset_id='podcast-chapters:unspecified', attribution='anonymous', tier='chapters', episode_tier='episode', \*\*\_kwargs)

Parse a podcast chapters JSON file, bytes or text into a `MemoryStore`.

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
  * **asset_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The `MediaRef.asset_id` the chapters annotate.
  * **attribution** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `Provenance.was_attributed_to` of every annotation.
  * **tier** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Name of the tier the chapters go in.
  * **episode_tier** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Name of the tier of the episode metadata annotation.
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – On malformed input, naming the chapter index.
* **Return type:**
  [`IntervalAnnotationStore`](lacing.store.base.html.md#lacing.store.base.IntervalAnnotationStore)
