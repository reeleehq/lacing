# lacing.bodies.lyric_line

Body schema for one line of lyrics or subtitles on a lines tier.

URI: `annot://schema/lyric-line/v1`. Written by
[`lacing.tracks.subtitle.SubtitleBuilder`](lacing.tracks.subtitle.html.md#lacing.tracks.subtitle.SubtitleBuilder) and the LRC adapter. Permissive:
a caller’s own fields (`extra=`) are kept.

### Classes

| [`LyricLineBodyV1`](#lacing.bodies.lyric_line.LyricLineBodyV1)(\*, text[, line_index, section])   | A line of text, with its position in the song.   |
|-----------------------------------------------------------------------------------------------------|--------------------------------------------------|

### *class* lacing.bodies.lyric_line.LyricLineBodyV1(, text, line_index=None, section=None, \*\*extra_data)

Bases: `SchemaModel`

A line of text, with its position in the song.

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'allow', 'frozen': True}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].
