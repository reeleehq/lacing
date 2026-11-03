# lacing.bodies.song_section

Body schema for a section of a song (intro, verse, chorus) on a sections tier.

URI: `annot://schema/song-section/v1`. Written by
[`lacing.tracks.subtitle.SubtitleBuilder`](lacing.tracks.subtitle.html.md#lacing.tracks.subtitle.SubtitleBuilder). Permissive: a caller’s own
descriptors (`extra=`) are kept, so a body this schema accepts today stays
accepted.

### Classes

| [`SongSectionBodyV1`](#lacing.bodies.song_section.SongSectionBodyV1)(\*, label[, title, energy, ...])   | A labelled section of a song, with optional descriptors.   |
|-------------------------------------------------------------------------------------------------------|------------------------------------------------------------|

### *class* lacing.bodies.song_section.SongSectionBodyV1(, label, title=None, energy=None, mood=None, \*\*extra_data)

Bases: `SchemaModel`

A labelled section of a song, with optional descriptors.

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'allow', 'frozen': True}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].
