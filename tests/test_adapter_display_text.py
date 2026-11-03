"""Writers use one display-text rule (lacing#138): a chapter's title becomes a
cue, an episode's metadata does not become an empty one."""

from __future__ import annotations

import json

import pytest

from lacing.adapters import lrc, podcast_chapters, podcast_transcript, srt, webvtt
from lacing.adapters._common import display_text

CHAPTERS = json.dumps(
    {
        "version": "1.2.0",
        "title": "Episode 7 - Making Progress",
        "author": "John Doe",
        "chapters": [
            {"startTime": 0, "endTime": 10, "title": "Intro"},
            {"startTime": 10, "endTime": 20, "title": "Hearing Aids"},
            {"startTime": 20, "endTime": 30, "location": {"name": "Paris"}},
        ],
    }
)
TITLES = ["Intro", "Hearing Aids"]


@pytest.fixture
def chapters_store():
    return podcast_chapters.load(CHAPTERS)


@pytest.mark.parametrize(
    "body, expected",
    [
        ({"text": "hi", "title": "T"}, "hi"),
        ({"title": "T"}, "T"),
        ({"text": None, "title": "T"}, "T"),
        ({"text": ""}, ""),  # an empty cue stays a cue
        ({"text": "", "title": "T"}, ""),  # text present: it wins
        ({"title": "", "text": None}, None),  # a blank later key is passed over
        ({"text": 5}, "5"),
        ({"text": 1.5}, "1.5"),
        ({"text": True}, None),
        ({"text": ("a", "b")}, None),
        ({"text": b"x"}, None),
        ({"name": "A001_C003.mov", "kind": "clip"}, None),  # an OTIO clip
        ({"version": "1.2.0", "fields": {"title": "Ep"}}, None),
        ({"tags": [{"key": "ti", "value": "Song"}]}, None),
        ({"title": {"first": "A"}}, None),
        ("not a mapping", None),
        (None, None),
    ],
)
def test_display_text(body, expected):
    assert display_text(body) == expected


def test_display_text_keys_set_the_preference():
    body = {"text": "a", "title": "T", "name": "N"}
    assert display_text(body, keys=("title", "text")) == "T"
    assert display_text(body, keys=("name",)) == "N"
    assert display_text({"title": "", "text": "a"}, keys=("title", "text")) == ""


def test_chapters_to_srt_writes_titles_and_skips_metadata(chapters_store):
    out = srt.dump(chapters_store).decode()
    blocks = [b for b in out.split("\n\n") if b.strip()]
    assert [b.splitlines()[2] for b in blocks] == TITLES
    assert "Episode 7" not in out


def test_chapters_to_webvtt_writes_titles_and_no_empty_cues(chapters_store):
    out = webvtt.dump(chapters_store).decode()
    cues = [c for c in out.split("\n\n")[1:] if c.strip()]
    assert [c.splitlines()[-1] for c in cues] == TITLES
    assert "00:00:00.000 --> 00:00:00.000" not in out


def test_chapters_to_lrc_writes_titles(chapters_store):
    out = lrc.dump(chapters_store).decode()
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert [ln.split("]", 1)[1] for ln in lines] == TITLES


def test_podcast_transcript_keeps_speech_only(chapters_store):
    """A transcript segment is speech: a chapter title is not one (only
    ``text`` counts there, see test_adapter_podcast_transcript)."""
    doc = json.loads(podcast_transcript.dump(chapters_store))
    assert doc["segments"] == []


def test_text_wins_over_title_in_a_cue():
    from lacing.model import Annotation, MediaRef, Provenance
    from lacing.store import MemoryStore
    from lacing.time import RationalTime, TimeInterval

    from uuid import uuid4

    store = MemoryStore()
    store.add(
        Annotation(
            id=uuid4(),
            tier="t",
            reference=MediaRef(
                asset_id="a",
                interval=TimeInterval(RationalTime(1, 1), RationalTime(2, 1)),
            ),
            body={"text": "spoken", "title": "a title"},
            body_schema_uri="annot://schema/note/v1",
            provenance=Provenance(
                was_generated_by="user:t",
                was_attributed_to="t",
                generated_at_time=RationalTime(0, 1),
            ),
        )
    )
    for out in (srt.dump(store), webvtt.dump(store), lrc.dump(store)):
        assert "spoken" in out.decode() and "a title" not in out.decode()


def test_chapters_to_textgrid_labels_with_titles(chapters_store):
    pytest.importorskip("praatio")
    from lacing.adapters import textgrid

    out = textgrid.dump(chapters_store, format="short_textgrid").decode()
    for title in TITLES:
        assert f'"{title}"' in out


def test_chapters_to_eaf_labels_with_titles(chapters_store):
    pytest.importorskip("pympi")
    from lacing.adapters import eaf

    out = eaf.dump(chapters_store).decode()
    for title in TITLES:
        assert f"<ANNOTATION_VALUE>{title}</ANNOTATION_VALUE>" in out
