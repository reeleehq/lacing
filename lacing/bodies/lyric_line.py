"""Body schema for one line of lyrics or subtitles on a lines tier.

URI: ``annot://schema/lyric-line/v1``. Written by
:class:`lacing.tracks.subtitle.SubtitleBuilder` and the LRC adapter. Permissive:
a caller's own fields (``extra=``) are kept, so a body this schema accepts today
stays accepted.
"""

from __future__ import annotations

from pydantic import Field

from lacing.json_schema import SchemaModel
from lacing.schema import register_body_schema


class LyricLineBodyV1(SchemaModel):
    """A line of text, with its position in the song."""

    model_config = {"frozen": True, "extra": "allow"}

    text: str = Field(..., description="The line as sung or shown.")
    line_index: int | None = Field(
        None, ge=0, description="Index of the line in the song or file."
    )
    section: str | None = Field(
        None, description="Label of the song section the line belongs to."
    )


register_body_schema("annot://schema/lyric-line/v1", LyricLineBodyV1)
