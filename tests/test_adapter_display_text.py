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
        ({"text": "hi", "title": "T", "name": "N"}, "hi"),
        ({"title": "T", "name": "N"}, "T"),
        ({"text": None, "name": "N"}, "N"),
        ({"text": ""}, ""),  # an empty cue stays a cue
        ({"text": 5}, "5"),
        ({"version": "1.2.0", "fields": {"title": "Ep"}}, None),
        ({"tags": [{"key": "ti", "value": "Song"}]}, None),
        ({"name": {"first": "A"}}, None),
        ("not a mapping", None),
        (None, None),
    ],
)
def test_display_text(body, expected):
    assert display_text(body) == expected


def test_display_text_keys_set_the_preference():
    body = {"text": "a", "title": "T"}
    assert display_text(body, keys=("title", "text")) == "T"
    assert display_text(body, keys=("name",)) is None


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


def test_webvtt_text_still_wins_and_round_trips():
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhello\n"
    assert webvtt.dump(webvtt.load(vtt)).decode().strip().endswith("hello")
