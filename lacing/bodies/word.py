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
    """

    model_config = {"frozen": True, "extra": "forbid"}

    text: str = Field(..., description="Surface form of the word.")
    speaker: str | None = Field(None, description="Optional speaker identifier.")
    line_index: int | None = Field(
        None,
        ge=0,
        description="Index of the line (lyric, subtitle cue) holding the word.",
    )
    confidence: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Recognizer or aligner confidence in [0, 1].",
    )


register_body_schema("annot://schema/word/v1", WordBodyV1)
