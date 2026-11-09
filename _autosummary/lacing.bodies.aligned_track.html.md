# lacing.bodies.aligned_track

The aligned-track wire model and its store body (lacing#107).

Timed text at every granularity — sections, lines, words, syllables, phones —
as **one** document that a TypeScript player (or any non-Python consumer)
reads through the exported JSON Schema (`lacing/schema/aligned-track/v1.json`,
then Zod, under a version pin, the way lacing-ui consumes the other schemas).

Three schemas, one set of span fields:

- `annot://schema/aligned-track/v1` ([`AlignedTrackV1`](#lacing.bodies.aligned_track.AlignedTrackV1)): the \*\*wire
  document\*\*. The text is stored once (`text`); each span points into it with
  `chars` offsets instead of repeating it, says how its times were obtained
  ([`SpanTime`](#lacing.bodies.aligned_track.SpanTime): `measured`, `interpolated` or `imported`, with
  confidence and source), and names its `parent` span. Times are \*\*integer
  milliseconds\*\*; `RationalTime` stays the persisted form
  ([`lacing.tracks.aligned`](lacing.tracks.aligned.html.md#module-lacing.tracks.aligned) converts, exactly, both ways).
- `annot://schema/aligned-span/v1` ([`AlignedSpanBodyV1`](#lacing.bodies.aligned_track.AlignedSpanBodyV1)): the body of
  one span’s annotation in a store (the interval is the annotation’s), which
  keeps the surface `text` beside the span fields so generic consumers
  (`display_text`, the cue writers) read it, and the `chars` and
  `parent_id` that make an export exact.
- `annot://schema/aligned-text/v1` ([`AlignedTextBodyV1`](#lacing.bodies.aligned_track.AlignedTextBodyV1)): the track’s
  text, stored once in a store as well, on one annotation spanning the asset.

Levels run from coarse to fine ([`LEVELS`](#lacing.bodies.aligned_track.LEVELS)); a span’s parent is of a coarser
level and comes earlier in `spans` (a pre-order listing: a parent, then
what it holds, siblings by start). A child may stray a few milliseconds
outside its parent in time (an aligner’s word against an imported line), so
containment in time is not required; containment in `chars` is.

The document is **open**: readers ignore fields they do not know (the models
use `extra="ignore"`, so the exported schema does not forbid additional
properties and a pinned Zod mirror stays lenient). `level` and `kind` are
closed enums: a new value is a new major version (`v2`), not a field a v1
reader would mis-handle. `chars` count Unicode code points, **not** JavaScript
string indices: in TypeScript, index `Array.from(text)`.

### Module Attributes

| [`LEVELS`](#lacing.bodies.aligned_track.LEVELS)   | the order of the levels in a track.   |
|-----------------------------------------------------------|---------------------------------------|

### Classes

| [`AlignedSpan`](#lacing.bodies.aligned_track.AlignedSpan)(\*, level[, chars, label, parent])    | One span of the wire document.                                          |
|----------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------|
| [`AlignedSpanBodyV1`](#lacing.bodies.aligned_track.AlignedSpanBodyV1)(\*, level[, chars, label, ...]) | The body of one span's annotation (its interval is the annotation's).   |
| [`AlignedTextBodyV1`](#lacing.bodies.aligned_track.AlignedTextBodyV1)(\*, text[, language])           | The text of a track, stored once, on one annotation spanning the asset. |
| [`AlignedTrackV1`](#lacing.bodies.aligned_track.AlignedTrackV1)(\*, asset_id, text[, ...])         | An aligned text: the text once, and its spans at every level.           |
| [`SpanTime`](#lacing.bodies.aligned_track.SpanTime)(\*, kind[, confidence, source])          | How a span's times were obtained.                                       |

### *class* lacing.bodies.aligned_track.AlignedSpan(, level, chars=None, label=None, time, start_ms, end_ms, parent=None)

Bases: `_SpanFields`, `SchemaModel`

One span of the wire document.

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'ignore', 'frozen': True}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].

### *class* lacing.bodies.aligned_track.AlignedSpanBodyV1(, level, chars=None, label=None, time, text=None, parent_id=None)

Bases: `_SpanFields`, `SchemaModel`

The body of one span’s annotation (its interval is the annotation’s).

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'forbid', 'frozen': True}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].

### *class* lacing.bodies.aligned_track.AlignedTextBodyV1(, text, language=None)

Bases: `SchemaModel`

The text of a track, stored once, on one annotation spanning the asset.

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'forbid', 'frozen': True}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].

### *class* lacing.bodies.aligned_track.AlignedTrackV1(\*, asset_id, text, language=None, spans=<factory>)

Bases: `SchemaModel`

An aligned text: the text once, and its spans at every level.

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'ignore', 'frozen': True}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].

### lacing.bodies.aligned_track.LEVELS *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), ...]* *= ('section', 'line', 'word', 'syllable', 'phone')*

the order of the levels in a track.

* **Type:**
  Coarse to fine

### *class* lacing.bodies.aligned_track.SpanTime(, kind, confidence=None, source=None)

Bases: `SchemaModel`

How a span’s times were obtained.

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'ignore', 'frozen': True}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].
