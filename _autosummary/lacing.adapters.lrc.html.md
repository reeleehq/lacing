# lacing.adapters.lrc

LRC (`.lrc`) lyrics adapter: plain LRC and enhanced LRC with word timing.

An LRC file is a list of time-tagged lyric lines, plus ID tags:

```default
[ar:Some Artist]
[ti:Some Title]
[length: 3:20]
[offset:+250]
[00:12.00]I came down to the river
[00:15.30][01:02.00]chorus, sung twice
[00:18.75]<00:18.75>Word <00:19.10>by <00:19.40>word
```

Tiers and bodies (the names lacing’s lyric tracks already use,
[`lacing.tracks.subtitle`](lacing.tracks.subtitle.html.md#module-lacing.tracks.subtitle)):

- `lines` (stereotype `NONE`): one annotation per time tag, body
  `annot://schema/lyric-line/v1` `{"text": str}`. A line with several time
  tags (`[00:15.30][01:02.00]chorus`) becomes one annotation per tag, all
  with the same text. Leading and trailing blanks of the text are stripped; a
  tag with no text (`[01:30.00]`) is a line with text `""`, the usual LRC
  way to clear the display. Lines may overlap (see the end times below).
- `words` (stereotype `INCLUDED_IN` `lines`, only when the file has word
  stamps): one annotation per `<mm:ss.xx>word` segment, body
  `annot://schema/word/v1` `{"text": str}`. Text before a line’s first word
  stamp is a word starting at the line’s time; a stamp followed only by blanks
  ends the previous word without starting one. LRC has no escape, so a literal
  `<mm:ss.xx>` inside lyric text is read as a word stamp.
- `tags` (stereotype `NONE`, only when the file has ID tags): **one**
  metadata annotation, a point at time 0, body `annot://schema/lrc-tags/v1`
  `{"tags": [{"key": str, "value": str}, ...]}`, every ID tag in file order
  with its key and value exactly as written (`[length: 3:20]` keeps the value
  `" 3:20"`). [`dump()`](#lacing.adapters.lrc.dump) writes these tags back verbatim, one per row. They
  live on one annotation rather than in every line body because they describe
  the file, not a line, and so that a store from another format (SubRip,
  WebVTT) dumps without inventing any.

End times (LRC has none):
: A line ends where the next *later* line starts (lines sharing a start, as
  in bilingual files, all end at the next later start). The last line ends
  at `[length:]` when the file gives one at or after its start, else it is
  a point (`start == end`); a `[length:]` before the last line is only a
  hint and is ignored. A word ends at the next word stamp of its line, or,
  for the last word, at its line’s end (a point when that end is before the
  word starts, as in a last line that is itself a point). When a line has
  several time tags, its word stamps (absolute times) are read once, against
  the latest of those tags at or before the first word stamp (the first tag
  if none). That line is then widened to hold its words, since the words
  tier is `INCLUDED_IN` the lines tier: it starts at its first word when
  that word is stamped before the line’s tag, and it ends at its last word
  when that word is sung past the next line’s start (karaoke files do both).
  A widened line overlaps its neighbours.

Offset:
: `[offset:+/-ms]` shifts every line and word time; `+` makes lyrics
  appear *sooner*, so a time is the tag minus the offset. The primary source
  is ffmpeg’s LRC demuxer (`libavformat/lrcdec.c`:
  `sub->pts = ts_start - lrc->ts_offset`); Wikipedia agrees
  ([https://en.wikipedia.org/wiki/LRC_(file_format](https://en.wikipedia.org/wiki/LRC_(file_format)): “with `+` causing
  lyrics to appear sooner”). It applies to the whole file wherever the tag
  stands; `[length:]` is a media duration and is not shifted; an empty
  `[offset:]` is 0. A time the offset makes negative (`[offset:+500]`
  with a `[00:00.00]Artist - Title` line, a common file) is clamped to 0
  where ffmpeg lets the negative time through; the clamped time is \*\*not
  exact\*\*, and it dumps as the offset itself (`[00:00.50]`). On dump the
  offset tag is written back and the times are shifted back by it, so a file
  with an offset round-trips.

Time discipline:
: Tags are `[mm:ss.xx]` or `[mm:ss.xxx]` (`.`, `,` or `:` before
  the fraction; one to three fraction digits are read as a decimal fraction
  of a second, and `[mm:ss]` is a whole second). Every time is parsed as
  integer milliseconds and converted exactly to `RationalTime` at `rate`
  (default 1000; it must hold a millisecond, or loading raises
  `LossyTimeConversionError`), via `lacing.adapters._cues`. No float
  is involved. [`dump()`](#lacing.adapters.lrc.dump) writes centiseconds by default
  (`precision="cs"`, `[mm:ss.xx]`, what LRC players expect) or
  milliseconds (`precision="ms"`). Finer times are **truncated** (the
  floor, for the non-negative times LRC holds): truncation is monotone, so
  written lines and word stamps keep their order.

Lossy fields on dump:
: End times are not written (except that `[length:]` tags pass through,
  and a word’s end is stamped when it is not implied), so a line’s end
  becomes the next line’s start (or its last word’s end); gaps between lines
  are lost. Provenance, confidence, schema URIs and tier metadata are
  dropped. A line’s text, and a word’s, is written on one line: a multi-line
  text (a SubRip cue) has its lines joined by a space, blank ones dropped.
  By default (`tier=None`) the lines are the `lines` tier when the store
  has text annotations on it, and otherwise every annotation with a time
  interval and a `text` body on any tier but the words tier, so SubRip and
  WebVTT cues dump to LRC. Word annotations on the words tier become word
  stamps in the line that holds them (among the lines whose interval
  contains the word, the one starting latest); a word no line holds is
  dropped, and so is a word the line’s text does not contain (in order):
  the line’s text is always written as it is, never replaced by its words.
  Text between two words is read back as part of the earlier word, and text
  before the first word as a word of its own. A word overlapping the next
  one is cut at the next word’s start. A line text that itself starts with
  a `[mm:ss.xx]` clock reads back as another time tag.

Lenient input, as ffmpeg’s demuxer is: a line with no leading time tag or ID
tag (stray text, a bare `[Chorus]`) is skipped; after a line’s first time
tag, the first bracket that is not a clock (`[00:01.00][2x] la`) starts the
text; several ID tags may share a line (`[ar:A][ti:T]`). Malformed input
raises `ValueError` naming the line number: a line whose first bracket
claims to be a time (`[` digits `:`) but is not a valid clock; a bad word
stamp; a bad `[offset:]` or `[length:]` value, or either tag twice; text
after ID tags; word stamps going backwards.

### Functions

| [`dump`](#lacing.adapters.lrc.dump)(store[, target, tier, words_tier, ...])   | Write annotations as LRC (enhanced LRC when there are words).   |
|-------------------------------------------------------------------------------------------------|-----------------------------------------------------------------|
| [`load`](#lacing.adapters.lrc.load)(source, \*[, rate, asset_id, ...])        | Parse an LRC file, or LRC bytes or text, into a `MemoryStore`.  |

### lacing.adapters.lrc.dump(store, target=None, , tier=None, words_tier='words', precision='cs', \*\*\_kwargs)

Write annotations as LRC (enhanced LRC when there are words).

ID tags (from `annot://schema/lrc-tags/v1` annotations) come first,
verbatim; then one `[mm:ss.xx]text` row per line, sorted by start then
end; word annotations on `words_tier` become `<mm:ss.xx>` stamps in
the line holding them. With an `[offset:]` tag, times are shifted back
by it, so that loading applies it again.

* **Parameters:**
  * **store** ([`IntervalAnnotationStore`](lacing.store.base.html.md#lacing.store.base.IntervalAnnotationStore)) – Source store. Lines are annotations with a time interval and a
    `text` body (an LRC line, a SubRip or WebVTT cue, or any other).
  * **target** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Output path. If None, returns bytes (UTF-8, no BOM, `\n`).
  * **tier** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – The tier whose texts are the lines. None (the default) means the
    `lines` tier when the store has text annotations on it (so a
    phones or notes tier beside it is not written as lyrics), and
    otherwise every tier but `words_tier`.
  * **words_tier** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Tier whose annotations are written as word stamps.
  * **precision** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `"cs"` (`[mm:ss.xx]`, default) or `"ms"`
    (`[mm:ss.xxx]`); finer times are truncated.
* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### lacing.adapters.lrc.load(source, , rate=1000, asset_id='lrc:unspecified', attribution='anonymous', tier='lines', words_tier='words', tags_tier='tags', encoding=None, \*\*\_kwargs)

Parse an LRC file, or LRC bytes or text, into a `MemoryStore`.

Lines go on `tier`, word stamps on `words_tier`, ID tags on one
annotation on `tags_tier` (see the module docstring for end times and
the offset sign).

* **Parameters:**
  * **source** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes) | [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike)) – Bytes (UTF-8, BOM tolerated), a path, or inline text. A
    `str` with a line break, or starting with `[`, is inline text;
    any other `str` is read as a path when a file exists there.
  * **rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Rate of every `RationalTime` produced; must hold a millisecond.
  * **asset_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The `MediaRef.asset_id` the lyrics annotate.
  * **attribution** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `Provenance.was_attributed_to` of every annotation.
  * **tier** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Name of the lines tier.
  * **words_tier** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Name of the words tier (created only for enhanced LRC).
  * **tags_tier** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Name of the ID-tag tier (created only when there are tags).
  * **encoding** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Text encoding of a file or of bytes. `None` sniffs a BOM
    (UTF-8, UTF-16, UTF-32) and otherwise reads UTF-8; name one
    (`"cp1252"`) for a file without a BOM.
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – On malformed input, naming the line number.
* **Return type:**
  [`IntervalAnnotationStore`](lacing.store.base.html.md#lacing.store.base.IntervalAnnotationStore)
