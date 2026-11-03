"""Body schema for a section of a song (intro, verse, chorus) on a sections tier.

URI: ``annot://schema/song-section/v1``. Written by
:class:`lacing.tracks.subtitle.SubtitleBuilder`. Permissive: a caller's own
descriptors (``extra=``) are kept, so a body this schema accepts today stays
accepted.
"""

from __future__ import annotations

from pydantic import Field

from lacing.json_schema import SchemaModel
from lacing.schema import register_body_schema


class SongSectionBodyV1(SchemaModel):
    """A labelled section of a song, with optional descriptors."""

    model_config = {"frozen": True, "extra": "allow"}

    label: str = Field(..., description="Section id, e.g. 'verse_1', 'chorus'.")
    title: str | None = Field(None, description="Display title, e.g. 'verse 1'.")
    energy: str | None = Field(None, description="Energy level, e.g. 'high'.")
    mood: str | None = Field(None, description="Mood, e.g. 'wistful'.")


register_body_schema("annot://schema/song-section/v1", SongSectionBodyV1)
