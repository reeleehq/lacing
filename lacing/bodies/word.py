"""Body schema for word-level annotations (e.g., transcription, forced alignment).

URI: ``annot://schema/word/v1``
"""

from __future__ import annotations

from pydantic import Field

from lacing.json_schema import SchemaModel
from lacing.schema import register_body_schema


class WordBodyV1(SchemaModel):
    """A single word annotation.

    The ``text`` is the surface form as it appears in the source media.
    ``line_index`` and ``confidence`` are what transcription, forced alignment
    and :class:`lacing.tracks.subtitle.SubtitleBuilder` record per word (both
    added in lacing#122, additively: every older word body still validates).
    """

    model_config = {"frozen": True, "extra": "forbid"}

    text: str = Field(..., description="Surface form of the word.")
    speaker: str | None = Field(None, description="Optional speaker identifier.")
    line_index: int | None = Field(
        None, description="Index of the line (lyric, subtitle cue) holding the word."
    )
    confidence: float | None = Field(
        None, description="Recognizer or aligner confidence, typically in [0, 1]."
    )


register_body_schema("annot://schema/word/v1", WordBodyV1)
