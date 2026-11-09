# lacing.adapters.ass

ASS / SSA (Advanced SubStation Alpha) subtitle adapter, with karaoke timing.

An ASS file is a set of `[Section]` blocks; the timed text is in `[Events]`,
whose `Format:` line names the comma-separated fields of each event, the
text field last (so the text may hold commas):

```default
[Script Info]
ScriptType: v4.00+
PlayResX: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, ...
Style: Default,Arial,48,&H00FFFFFF,...

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.50,Default,,0,0,0,,Hello, {\i1}world{\i0}\Nline two
Dialogue: 0,0:00:04.00,0:00:06.00,Karaoke,,0,0,0,,{\k50}Ka{\kf40}ra{\ko60}o{\k50}ke
Comment: 0,0:00:07.00,0:00:08.00,Default,,0,0,0,,a note, not shown
```

Tiers and bodies (the `lines`/`words` names of lacing’s lyric tracks,
[`lacing.tracks.subtitle`](lacing.tracks.subtitle.html.md#module-lacing.tracks.subtitle), so ASS, LRC, SubRip and WebVTT convert into one
another out of the box):

- `lines` (stereotype `NONE`): one annotation per `Dialogue` event,
  body `annot://schema/ass-event/v1`:
  ```default
  {"text": str, "raw": str, "style": str, "fields": {name: str}, "index": int}
  ```

  `raw` is the text field verbatim, override tags and all; `text` is what
  it reads as: override blocks `{...}` removed, `\N` and `\n` as a
  newline, `\h` as a no-break space (U+00A0), and a vector drawing (the
  text between `{\p1}`, any `\p<n>` with `n > 0`, and `{\p0}`) as
  nothing, so a drawing-only event has an empty `text`. `style` is the
  `Style` field. `fields` holds every other field of the event (`Layer`, `Name`,
  `MarginL`, `MarginR`, `MarginV`, `Effect`, or `Marked` in SSA)
  verbatim, keyed by its name in the `Format:` line. `index` is the
  event’s position in `[Events]` (dialogues and comments counted together),
  which [`dump()`](#lacing.adapters.ass.dump) uses to write events back in file order, since a
  renderer resolves collisions in that order.
  **One tier for all styles, the style in the body**, rather than one tier per
  style: ASS styles are presentation, events of one style overlap freely, and
  one lines tier lets the words tier be `INCLUDED_IN` a single parent.
- `words` (stereotype `INCLUDED_IN` `lines`, only when some dialogue has
  karaoke tags): one annotation per karaoke syllable, body
  `annot://schema/ass-syllable/v1`
  `{"text": str, "karaoke": "k" | "K" | "kf" | "ko", "event": int,
  "ordinal": int}`.
  `text` is the syllable’s text (what follows its tag up to the next
  karaoke tag), stripped of blanks; `karaoke` the tag that timed it;
  `event` the `index` of its line; `ordinal` its place among that
  line’s syllables (from 0), which [`dump()`](#lacing.adapters.ass.dump) writes them back in, since
  times tie (`{\k0}`, syllables cut at the event’s end) and `\kt` can
  move a later syllable before an earlier one. A word body without
  `ordinal` (another source’s) is ordered by time. A syllable whose text
  is blank (a lead-in `{\k50}` pause, or 

  ```
  ``
  ```

  {k20} 

  ```
  ``
  ```

  ) is a gap, not a word.
- `comments` (stereotype `NONE`, only when the file has some): one
  annotation per `Comment` event, with the same body as a dialogue. Comment
  events are not shown by a renderer; they are kept (on their own tier, so
  that they are flagged and other formats’ writers can leave them out with
  `tier=`), and their karaoke tags are not read as syllables (Aegisub’s
  karaoke templater comments out the timed originals).
- `script` (stereotype `NONE`): **one** metadata annotation, a point at
  time 0, body `annot://schema/ass-script/v1`:
  ```default
  {"sections": [{"name": str | None, "lines": [str]}],
   "events": {"name": str, "position": int, "format": [str], "lines": [str]}}
  ```

  Every section but `[Events]` (`[Script Info]`, `[V4+ Styles]` or
  `[V4 Styles]`, `[Fonts]`, `[Graphics]`, `[Aegisub Project Garbage]`,
  anything else) with its non-blank lines verbatim, in file order (a `None`
  name holds lines before the first header); where `[Events]` stood among
  them; its `Format:` field names; and its other lines (`;` comments,
  `Picture:`, `Sound:`, `Movie:`, `Command:`) verbatim. [`dump()`](#lacing.adapters.ass.dump)
  writes all of this back. Inside `[Fonts]` and `[Graphics]` a bracketed
  line made only of uuencode characters is data, not a section header,
  unless it names a known section (`[EVENTS]`, `[Script Info]`, a styles
  section, `[Fonts]`, `[Graphics]`, in any case). `load(keep_sections=)`
  keeps only the named sections: `[Fonts]`/`[Graphics]` can be megabytes
  and `[Aegisub Project Garbage]` holds local file paths.

Karaoke:
: `{\k<cs>}`, `{\K<cs>}` (= `\kf`), `{\kf<cs>}` and `{\ko<cs>}`
  each start a syllable lasting `<cs>` centiseconds; syllables follow one
  another from the event start, so a syllable’s start is the event start
  plus the durations before it, exactly. `{\kt<cs>}` moves the start of
  the next syllable to `<cs>` after the event start (libass 0.17+). A
  decimal duration (`\k12.5`) is read exactly too. A tag with no value
  (`{\k}`) lasts 100 centiseconds (`\kt`: 0), as in libass; a
  negative or malformed one raises, naming the line. A syllable that runs
  past its event’s end is cut at the end (one that starts at or after it
  becomes a point there), so the words tier stays `INCLUDED_IN` the
  lines tier; its tag stays in `raw`.

Time discipline:
: Event times are strictly `H:MM:SS.cc`: exactly two centisecond digits,
  minutes and seconds below 60, so `0:00:01.5` and `0:60:00.00` raise
  (libass is laxer). They are integer centiseconds, read as integers and
  converted exactly to `RationalTime` at `rate` (default 1000; `rate`
  must hold the times exactly, a centisecond and any decimal karaoke
  duration, or loading raises `LossyTimeConversionError` naming the
  line). No float is
  involved. [`dump()`](#lacing.adapters.ass.dump) writes centiseconds: a finer time is **truncated**
  to the centisecond (the floor, for the non-negative times ASS holds), and
  karaoke durations are differences of truncated times, so truncation is
  monotone (every event keeps `start <= end`, syllables keep their order
  and never get a negative duration) and the times read back are exactly the
  truncated ones. A negative time raises `ValueError`.

dump:
: Writes `[Script Info]`, a styles section and `[Events]` from the
  script metadata when the store has it (`script_info=` when it has no
  `[Script Info]`, `default_style=`, Aegisub’s `Default`, when there
  are no styles, and `event_format=` when it has no `[Events]` format),
  then one `Dialogue:` per line and one `Comment:` per
  comment, ASS events in their `index` order, others after them by time.
  Any annotation with a time interval and a `text` body can be a line
  (by default the `lines` tier when it has text annotations, otherwise
  every top-level tier but the words and comments tiers, as the SubRip and
  WebVTT writers choose), so SubRip, WebVTT
  and LRC cues dump to ASS, their newlines written as `\N`. A line whose
  `raw` still reads as its `text` is written from `raw`, override tags
  kept; when the `text` was edited, the `text` wins and the tags are
  lost. Karaoke tags come from the word annotations inside a line (an ASS
  syllable goes back to its own event; any other word, an LRC word stamp
  for one, to the latest-starting line that holds it in time and in text,
  the rule LRC uses): when they are the syllables `raw` already encodes,
  `raw` is written as is; otherwise `raw`’s karaoke tags are replaced
  by `{\k..}` tags (the word’s own `karaoke` kind, `k` by default)
  placed before each word found in the text, in order, with an empty
  `{\k..}` filling a gap before a word and a word cut at the next one’s
  start. The text is never replaced by its words.

Lossy fields on dump:
: Provenance, confidence, schema URIs and tier metadata are dropped. Blank
  lines are not kept, and a `Format:` line is written with `", "`
  between names; `[Events]` lines other than events are written after its
  `Format:` line; an event field not in the target `Format:` is dropped
  (a missing one is written as Aegisub writes it empty: `0` for layer and
  margins, empty otherwise). A word no line holds, or one not found in its
  line’s text, is dropped; text between two words reads back as part of
  the earlier one. ASS has no escape: a `{...}` or a `\N`, `\n`,
  `\h` in a plain text (a SubRip `{\an8}`, say) is written through and
  reads back as an override block or a break. A comma or line break in a
  non-text field, or a line break in `raw`, cannot be written and raises
  `ValueError`.

Malformed input raises `ValueError` naming the line number: a line in
`[Events]` that is not `Key: value` or a `;` comment, a second or late
`Format:` line, a `Format:` without `Start`, `End` or `Text` last, an
event with too few fields, a bad time, an event ending before it starts, a
bad karaoke duration. Input with no `[Events]` section is not ASS and raises
too (an empty input included). `[Events]` without a `Format:` line uses
the default one (with `Layer`; with `Marked` under `[V4 Styles]`), as
libass does, and [`dump()`](#lacing.adapters.ass.dump) then writes it.

Sources: the format specification “Sub Station Alpha v4.00+ Script Format”
([http://www.tcax.org/docs/ass-specs.htm](http://www.tcax.org/docs/ass-specs.htm)), Aegisub’s override-tag reference
([https://aegisub.org/docs/latest/ass_tags/](https://aegisub.org/docs/latest/ass_tags/), for `\k`, `\K`, `\kf`,
`\ko`, `\N`, `\n`, `\h`), and libass’s reader
([https://github.com/libass/libass](https://github.com/libass/libass), `libass/ass.c` and
`libass/ass_parse.c`) for what real files do.

### Functions

| [`dump`](#lacing.adapters.ass.dump)(store[, target, tier, words_tier, ...])   | Write annotations as an ASS (v4.00+) script.                                                                                         |
|-------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------|
| [`load`](#lacing.adapters.ass.load)(source, \*[, rate, asset_id, ...])        | Parse an ASS/SSA file, or ASS bytes or text, into a `MemoryStore`.                                                                   |
| [`plain_text`](#lacing.adapters.ass.plain_text)(raw)                                | What an ASS text reads as: override blocks removed, `\N` and `\n` as a newline, `\h` as a no-break space, a `\p` drawing as nothing. |

### lacing.adapters.ass.dump(store, target=None, , tier=None, words_tier='words', comments_tier='comments', script_info=('; Script generated by lacing', 'ScriptType: v4.00+'), default_style={'alignment': '2', 'backcolour': '&H00000000', 'borderstyle': '1', 'encoding': '1', 'fontname': 'Arial', 'fontsize': '20', 'marginl': '10', 'marginr': '10', 'marginv': '10', 'name': 'Default', 'outline': '2', 'outlinecolour': '&H00000000', 'primarycolour': '&H00FFFFFF', 'scalex': '100', 'scaley': '100', 'secondarycolour': '&H000000FF', 'shadow': '2', 'tertiarycolour': '&H00000000'}, event_format=('Layer', 'Start', 'End', 'Style', 'Name', 'MarginL', 'MarginR', 'MarginV', 'Effect', 'Text'), \*\*\_kwargs)

Write annotations as an ASS (v4.00+) script.

* **Parameters:**
  * **store** ([`IntervalAnnotationStore`](lacing.store.base.html.md#lacing.store.base.IntervalAnnotationStore)) – Source store. Lines are annotations with a time interval and a
    `text` body (an ASS dialogue, an LRC line, a SubRip or WebVTT
    cue, or any other); comments are those on `comments_tier`.
  * **target** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Output path. If None, returns bytes (UTF-8, no BOM, `\n`).
  * **tier** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – The tier whose texts are the dialogue lines. None (the default)
    means the `lines` tier when the store has text annotations on
    it, and otherwise every top-level tier (one with no parent
    constraint, as the SubRip and WebVTT writers choose) but
    `words_tier` and `comments_tier`.
  * **words_tier** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Tier whose annotations are written as karaoke tags.
  * **comments_tier** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Tier whose annotations are written as `Comment:`.
  * **script_info** ([`Sequence`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The `[Script Info]` lines written when the store has
    no ASS script metadata, or it has no such section.
  * **default_style** ([`Mapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The style written when the styles section has no
    `Style:` line: field values keyed by lowercased `Format:`
    name (`"0"` for a missing field); its `name` is also the
    style of every non-ASS line. Aegisub’s `Default` by default.
  * **event_format** ([`Sequence`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The `[Events]` `Format:` field names written when
    the store has no ASS script metadata (`Start`, `End` and
    `Text` last required; raises `ValueError` otherwise).
* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### lacing.adapters.ass.load(source, , rate=1000, asset_id='ass:unspecified', attribution='anonymous', tier='lines', words_tier='words', comments_tier='comments', script_tier='script', encoding=None, keep_sections=None, \*\*\_kwargs)

Parse an ASS/SSA file, or ASS bytes or text, into a `MemoryStore`.

Dialogue events go on `tier`, their karaoke syllables on `words_tier`,
comment events on `comments_tier`, the script’s other sections on one
annotation on `script_tier` (see the module docstring).

* **Parameters:**
  * **source** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes) | [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike)) – Bytes (see `encoding`), a path, or inline text. A
    `str` naming an existing file is read from it (even one named
    `"[Group] Show - 01.ass"`); any other `str` is inline text.
  * **rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Rate of every `RationalTime` produced; must hold a centisecond
    (and any decimal karaoke duration) exactly.
  * **asset_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The `MediaRef.asset_id` the events annotate.
  * **attribution** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `Provenance.was_attributed_to` of every annotation.
  * **tier** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Name of the lines (dialogue) tier.
  * **words_tier** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Name of the karaoke syllable tier (created only when
    there are syllables).
  * **comments_tier** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Name of the comment-event tier (created only when
    there are comments).
  * **script_tier** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Name of the script-metadata tier.
  * **encoding** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Text encoding of a file or of bytes. `None` sniffs a BOM
    (UTF-8, UTF-16, UTF-32) and otherwise reads UTF-8; name one
    (`"cp1252"`) for an older file without a BOM.
  * **keep_sections** ([`Iterable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterable)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)] | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Names of the non-`[Events]` sections the `script`
    annotation keeps verbatim (case-insensitive, e.g.
    `("Script Info", "V4+ Styles")`); `None` (the default) keeps
    them all. `[Fonts]` and `[Graphics]` can be megabytes of
    uuencoded data, and `[Aegisub Project Garbage]` holds local file
    paths, so name what you need before storing or sharing the result.
    [`dump()`](#lacing.adapters.ass.dump) writes defaults for a dropped `[Script Info]` or
    styles section.
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – On malformed input, naming the line number, and on input
      with no `[Events]` section. A `rate` that cannot hold a time
      or a karaoke duration raises `LossyTimeConversionError` (a
      `ValueError`) naming the line too.
* **Return type:**
  [`IntervalAnnotationStore`](lacing.store.base.html.md#lacing.store.base.IntervalAnnotationStore)

### lacing.adapters.ass.plain_text(raw)

What an ASS text reads as: override blocks removed, `\N` and `\n`
as a newline, `\h` as a no-break space, a `\p` drawing as nothing.

```pycon
>>> plain_text(r"Hello, {\i1}world{\i0}\Nline\htwo")
'Hello, world\nline\xa0two'
>>> plain_text(r"{\p1}m 0 0 l 100 0 100 100{\p0}Sign")
'Sign'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
