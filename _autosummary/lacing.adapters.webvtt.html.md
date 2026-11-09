# lacing.adapters.webvtt

WebVTT (W3C TimedText) adapter.

WebVTT is a flat caption format: one stream of cues, no tier hierarchy.
Cues have a start time, an end time, optional id and settings, and a payload
(text with limited inline markup).

We map cues to a single tier named `cues` (override with `tier=`).
Each cue becomes one `Annotation` whose body holds:

> {“text”: str, “id”: str | None, “settings”: dict[str, str]}

Lossy fields on dump:
: Provenance, confidence, schema URIs, and tier metadata are dropped.
  Only the text, id (if present), and settings are emitted. Blank lines
  inside a cue’s text are dropped (a blank line ends a cue), and a negative
  time raises `ValueError` (WebVTT has none). A cue payload may not contain
  `-->` (a player would read it as a new cue’s timing line), so it is
  written `--&gt;`, which renders as `-->`; payloads are kept raw on load,
  so it reads back as `--&gt;` (lacing#129). A cue id with `-->` or a
  line break cannot be written at all and raises `ValueError`.

Time discipline:
: WebVTT timestamps are `HH:MM:SS.mmm` or `MM:SS.mmm` (with milliseconds).
  Parsing goes through integer milliseconds to avoid float ingestion. Default
  rate is 1000 (millisecond precision); override with `rate=` if your
  project uses a different canonical rate. On dump, sub-millisecond times
  are truncated to the millisecond (shared with SubRip, see
  `lacing.adapters._cues`).

Spec: [https://www.w3.org/TR/webvtt1/](https://www.w3.org/TR/webvtt1/)

### Functions

| [`dump`](#lacing.adapters.webvtt.dump)(store[, target, tier, lines_tier])   | Write annotations as WebVTT.                              |
|--------------------------------------------------------------------------------------------|-----------------------------------------------------------|
| [`load`](#lacing.adapters.webvtt.load)(source, \*[, rate, asset_id, ...])   | Parse a WebVTT file or string/bytes into a `MemoryStore`. |

### lacing.adapters.webvtt.dump(store, target=None, , tier=None, lines_tier='lines', \*\*\_kwargs)

Write annotations as WebVTT.

* **Parameters:**
  * **store** ([`IntervalAnnotationStore`](lacing.store.base.html.md#lacing.store.base.IntervalAnnotationStore)) – Source store. Only annotations from `tier` (from the tiers
    `tier` chooses) with a time interval (any reference kind) and readable
    text (`lacing.adapters._common.display_text()`: `text`,
    else `title`) are emitted, sorted by start then
    end.
  * **target** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Output path. If None, returns bytes (UTF-8).
  * **tier** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Write only this tier. None (the default) writes the `lines`
    tier when the store has one, else every top-level tier
    (`lacing.adapters._cues.select_cue_annotations()`); only
    annotations with a readable text count.
  * **lines_tier** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Name of the tier that holds the lines (for a store whose
    lines tier was loaded under another name).
* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### lacing.adapters.webvtt.load(source, , rate=1000, asset_id='webvtt:unspecified', attribution='anonymous', tier='cues', encoding=None, \*\*\_kwargs)

Parse a WebVTT file or string/bytes into a `MemoryStore`.

`encoding`: text encoding of a file or of bytes; `None` sniffs a BOM
(UTF-8, UTF-16, UTF-32) and otherwise reads UTF-8 (`"cp1252"` for a
file without a BOM).

* **Return type:**
  [`IntervalAnnotationStore`](lacing.store.base.html.md#lacing.store.base.IntervalAnnotationStore)
