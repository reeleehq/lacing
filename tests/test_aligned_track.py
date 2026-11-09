"""Aligned tracks: the wire model, the store converters, the golden vectors (lacing#107)."""

from __future__ import annotations

import json
import time as _time
from uuid import uuid4
from pathlib import Path

import pytest
from pydantic import ValidationError

import lacing.bodies  # noqa: F401  registers
from lacing.bodies.aligned_track import (
    SPAN_SCHEMA_URI,
    TEXT_SCHEMA_URI,
    TRACK_SCHEMA_URI,
    AlignedSpan,
    AlignedTrackV1,
    SpanTime,
)
from lacing.schema import json_schema
from lacing.store import MemoryStore
from lacing.time import LossyTimeConversionError, RationalTime, TimeInterval
from lacing.tracks.aligned import from_aligned_track, to_aligned_track
from lacing.tracks.subtitle import SubtitleBuilder

GOLDEN = Path(__file__).parent / "golden" / "aligned_track_v1.json"
ASSET = "song/audio.mp3"


@pytest.fixture
def golden() -> AlignedTrackV1:
    return AlignedTrackV1.model_validate_json(GOLDEN.read_text())


def _t(level, start, end, **kw):
    return AlignedSpan(
        level=level, start_ms=start, end_ms=end, time=SpanTime(kind="imported"), **kw
    )


# -- golden vectors -----------------------------------------------------------


def test_the_golden_document_round_trips_through_a_store(golden):
    store = from_aligned_track(golden)
    assert to_aligned_track(store, asset_id=ASSET, language="en") == golden


def test_the_golden_document_is_its_own_json(golden):
    assert json.loads(golden.model_dump_json()) == json.loads(GOLDEN.read_text())


@pytest.mark.parametrize("rate, ticks", [(1000, 1001), (24000, 24024), (48000, 48048)])
def test_milliseconds_become_exact_rational_times(golden, rate, ticks):
    store = from_aligned_track(golden, rate=rate)
    ends = {a.interval.end for a in store.all()}
    assert RationalTime(ticks, rate) in ends


def test_a_rate_that_cannot_hold_a_millisecond_is_refused(golden):
    with pytest.raises(LossyTimeConversionError):
        from_aligned_track(golden, rate=24)


def test_a_time_that_is_not_a_whole_millisecond_is_refused_unless_quantized(golden):
    store = from_aligned_track(golden, rate=48000)
    odd = MemoryStore()
    odd.add_tier(next(iter(store.tiers())))
    a = next(x for x in store.all() if x.body_schema_uri == SPAN_SCHEMA_URI)
    refs = a.reference.model_copy(
        update={
            "interval": TimeInterval(RationalTime(1, 48000), RationalTime(49, 48000))
        }
    )
    odd.add(a.model_copy(update={"reference": refs}))
    with pytest.raises(LossyTimeConversionError):
        to_aligned_track(odd, asset_id=ASSET)
    track = to_aligned_track(odd, asset_id=ASSET, quantize="ceil")
    assert (track.spans[0].start_ms, track.spans[0].end_ms) == (1, 2)


# -- the store side -----------------------------------------------------------


def test_one_tier_per_level_each_inside_the_coarser_one(golden):
    tiers = {t.name: t for t in from_aligned_track(golden).tiers()}
    assert list(tiers) == ["sections", "lines", "words", "syllables", "phones", "text"]
    assert tiers["sections"].parent is None
    assert tiers["phones"].parent == "syllables"


def test_a_store_body_validates_against_its_schema(golden):
    store = from_aligned_track(golden)
    assert {a.body_schema_uri for a in store.all()} == {
        SPAN_SCHEMA_URI,
        TEXT_SCHEMA_URI,
    }
    word = next(a for a in store.all() if a.tier == "words")
    assert word.body["text"] == "the" and word.confidence == 0.98


def test_a_subtitle_builder_store_exports_with_imported_times():
    store = MemoryStore()
    with SubtitleBuilder(store, asset_id=ASSET) as b:
        b.line(
            "hello world", 0.0, 1.0, words=[("hello", 0.0, 0.4), ("world", 0.4, 1.0)]
        )
    track = to_aligned_track(store, asset_id=ASSET)
    assert track.text == "hello world"
    assert [(s.level, s.chars, s.parent) for s in track.spans] == [
        ("line", (0, 11), None),
        ("word", (0, 5), 0),
        ("word", (6, 11), 0),
    ]
    assert {s.time.kind for s in track.spans} == {"imported"}
    assert {s.time.source for s in track.spans} == {"processor:lacing.tracks.subtitle"}


def test_another_assets_annotations_are_not_exported(golden):
    store = from_aligned_track(golden)
    assert to_aligned_track(store, asset_id="other.mp3").spans == []


def test_a_repeated_word_is_found_in_reading_order():
    track = AlignedTrackV1(
        asset_id=ASSET,
        text="la la la",
        spans=[
            _t("line", 0, 3000, chars=(0, 8)),
            _t("word", 0, 1000, chars=(0, 2), parent=0),
            _t("word", 1000, 2000, chars=(3, 5), parent=0),
            _t("word", 2000, 3000, chars=(6, 8), parent=0),
        ],
    )
    assert to_aligned_track(from_aligned_track(track), asset_id=ASSET) == track


def test_a_container_comes_before_what_it_holds_when_starts_tie():
    track = AlignedTrackV1(
        asset_id=ASSET,
        text="a",
        spans=[
            _t("line", 0, 1000, chars=(0, 1)),
            _t("word", 0, 500, chars=(0, 1), parent=0),
        ],
    )
    store = from_aligned_track(track)
    assert to_aligned_track(store, asset_id=ASSET).spans[0].level == "line"


# -- the wire model -----------------------------------------------------------


@pytest.mark.parametrize(
    "spans, why",
    [
        ([_t("line", 0, 1, chars=(0, 99))], "exceed the text"),
        ([_t("line", 0, 1), _t("word", 0, 1, parent=1)], "not earlier"),
        ([_t("word", 0, 1), _t("line", 0, 1, parent=0)], "coarser"),
    ],
)
def test_invalid_documents_are_refused(spans, why):
    with pytest.raises(ValidationError, match=why):
        AlignedTrackV1(asset_id=ASSET, text="ab", spans=spans)


@pytest.mark.parametrize(
    "kwargs, why",
    [
        ({"start_ms": 5, "end_ms": 1}, "ends before"),
        ({"start_ms": 0, "end_ms": 1, "chars": (3, 1)}, "0 <= start"),
        ({"start_ms": -1, "end_ms": 1}, "greater than or equal"),
    ],
)
def test_an_invalid_span_is_refused(kwargs, why):
    with pytest.raises(ValidationError, match=why):
        AlignedSpan(level="line", time=SpanTime(kind="measured"), **kwargs)


def test_extra_fields_and_unknown_levels_are_refused():
    with pytest.raises(ValidationError):
        AlignedSpan(
            level="paragraph", start_ms=0, end_ms=1, time=SpanTime(kind="measured")
        )
    with pytest.raises(ValidationError):
        SpanTime(kind="guessed")
    with pytest.raises(ValidationError):
        SpanTime(kind="measured", confidence=1.5)


def test_the_json_schema_is_the_contract_for_the_typescript_side():
    schema = json_schema(TRACK_SCHEMA_URI)
    assert set(schema["required"]) == {"asset_id", "text"}
    span = schema["$defs"]["AlignedSpan"]
    assert span["properties"]["level"]["enum"] == [
        "section",
        "line",
        "word",
        "syllable",
        "phone",
    ]
    assert span["properties"]["start_ms"]["type"] == "integer"
    assert schema["$defs"]["SpanTime"]["properties"]["kind"]["enum"] == [
        "measured",
        "interpolated",
        "imported",
    ]


# -- the findings of the adversarial review of the first cut ---------------------


def test_a_word_straying_outside_its_line_keeps_its_parent_and_chars():
    # an aligner's word 10 ms before an imported line: the normal case
    track = AlignedTrackV1(
        asset_id=ASSET,
        text="hello world",
        spans=[
            _t("line", 1000, 2000, chars=(0, 11)),
            _t("word", 990, 1500, chars=(0, 5), parent=0),
        ],
    )
    assert to_aligned_track(from_aligned_track(track), asset_id=ASSET) == track


def test_a_stored_text_keeps_separators_and_untimed_text():
    track = AlignedTrackV1(
        asset_id=ASSET,
        text="the cat. sat down",
        language="en",
        spans=[
            _t("line", 0, 1000, chars=(0, 8)),
            _t("line", 1000, 2000, chars=(9, 17)),
        ],
    )
    assert to_aligned_track(from_aligned_track(track), asset_id=ASSET) == track


def test_a_section_with_chars_keeps_them():
    track = AlignedTrackV1(
        asset_id=ASSET,
        text="la la",
        spans=[
            _t("section", 0, 2000, chars=(0, 5), label="v"),
            _t("line", 0, 1000, chars=(0, 2), parent=0),
        ],
    )
    assert to_aligned_track(from_aligned_track(track), asset_id=ASSET) == track


def test_equal_intervals_do_not_reparent_the_words():
    track = AlignedTrackV1(
        asset_id=ASSET,
        text="a b",
        spans=[
            _t("line", 0, 1000, chars=(0, 1)),
            _t("word", 0, 500, chars=(0, 1), parent=0),
            _t("line", 0, 1000, chars=(2, 3)),
            _t("word", 0, 500, chars=(2, 3), parent=2),
        ],
    )
    assert to_aligned_track(from_aligned_track(track), asset_id=ASSET) == track


def test_chars_of_a_legacy_store_ignore_case_and_punctuation():
    store = MemoryStore()
    with SubtitleBuilder(store, asset_id=ASSET) as b:
        b.line(
            "Hello, world!",
            0.0,
            1.0,
            words=[("hello", 0.0, 0.5), ("world", 0.5, 1.0)],
        )
    track = to_aligned_track(store, asset_id=ASSET)
    assert [s.chars for s in track.spans] == [(0, 13), (0, 5), (7, 12)]


def test_a_legacy_zero_confidence_is_kept():
    store = MemoryStore()
    with SubtitleBuilder(store, asset_id=ASSET) as b:
        b.line("a", 0.0, 1.0, words=[("a", 0.0, 1.0)])
    word = next(a for a in store.all() if a.tier == "words")
    store.add(
        word.model_copy(
            update={"id": uuid4(), "body": {**word.body, "confidence": 0.0}}
        )
    )
    confidences = {
        s.time.confidence for s in to_aligned_track(store, asset_id=ASSET).spans
    }
    assert 0.0 in confidences


def test_a_ten_thousand_span_export_is_fast():
    n = 10_000
    spans = [_t("line", 0, n * 10, chars=(0, 0))] + [
        _t("word", i * 10, i * 10 + 10, chars=(0, 0), parent=0) for i in range(n)
    ]
    track = AlignedTrackV1(asset_id=ASSET, text="", spans=spans)
    store = from_aligned_track(track)
    started = _time.perf_counter()
    assert len(to_aligned_track(store, asset_id=ASSET).spans) == n + 1
    assert _time.perf_counter() - started < 5  # was 5.8 s at 10k when quadratic


def test_the_document_is_open_to_fields_it_does_not_know():
    raw = json.loads(GOLDEN.read_text())
    raw["speaker_count"] = 2
    raw["spans"][0]["mood"] = "calm"
    raw["spans"][0]["time"]["method"] = "dtw"
    assert AlignedTrackV1.model_validate(raw).spans[0].level == "section"
    schema = json_schema(TRACK_SCHEMA_URI)
    assert "additionalProperties" not in schema
    assert "additionalProperties" not in schema["$defs"]["AlignedSpan"]


def test_a_child_whose_chars_leave_its_parents_is_refused():
    with pytest.raises(ValidationError, match="leave its parent"):
        AlignedTrackV1(
            asset_id=ASSET,
            text="abcdef",
            spans=[
                _t("line", 0, 9, chars=(0, 3)),
                _t("word", 0, 9, chars=(2, 5), parent=0),
            ],
        )


def test_converting_into_a_store_keeps_its_existing_tiers(golden):
    store = MemoryStore()
    from lacing.tier import Tier

    store.add_tier(Tier("words"))
    from_aligned_track(golden, store)
    assert store.get_tier("words").stereotype.value == "NONE"


def test_two_assets_in_one_store_export_separately(golden):
    store = from_aligned_track(golden)
    other = golden.model_copy(update={"asset_id": "other.mp3"})
    from_aligned_track(other, store)
    assert to_aligned_track(store, asset_id=ASSET) == golden
    assert to_aligned_track(store, asset_id="other.mp3") == other


# -- the re-review: edited stores degrade, jittered legacy words keep a parent ---


def _overlapping_lines_with_a_word():
    return AlignedTrackV1(
        asset_id=ASSET,
        text="hello world",
        spans=[
            _t("line", 0, 1000, chars=(0, 5)),
            _t("word", 600, 900, chars=(0, 5), parent=0),
            _t("line", 500, 1500, chars=(6, 11)),
        ],
    )


def test_an_export_survives_a_deleted_parent():
    store = from_aligned_track(_overlapping_lines_with_a_word())
    line = next(
        a for a in store.all() if a.tier == "lines" and a.body["chars"] == [0, 5]
    )
    store.remove(line.id)
    track = to_aligned_track(store, asset_id=ASSET)  # must not raise
    word = next(s for s in track.spans if s.level == "word")
    assert word.chars is None  # re-parented under the other line: chars dropped


def test_a_dangling_or_self_parent_id_falls_back_to_time():
    store = from_aligned_track(_overlapping_lines_with_a_word())
    word = next(a for a in store.all() if a.tier == "words")
    for bad in (uuid4(), word.id):
        body = {**word.body, "parent_id": str(bad)}
        edited = MemoryStore()
        for a in store.all():
            edited.add(a.model_copy(update={"body": body}) if a.id == word.id else a)
        assert to_aligned_track(edited, asset_id=ASSET).spans


def test_a_legacy_word_a_little_outside_its_line_still_has_a_parent():
    store = MemoryStore()
    with SubtitleBuilder(store, asset_id=ASSET) as b:
        b.line("hello world", 1.0, 2.0)
        b.word("hello", 0.99, 1.4)
        b.word("world", 1.4, 2.01)
    track = to_aligned_track(store, asset_id=ASSET)
    assert [(s.level, s.parent, s.chars) for s in track.spans] == [
        ("line", None, (0, 11)),
        ("word", 0, (0, 5)),
        ("word", 0, (6, 11)),
    ]


def test_a_word_inside_a_nested_line_goes_to_the_innermost_containing_line():
    store = MemoryStore()
    with SubtitleBuilder(store, asset_id=ASSET) as b:
        b.line("outer", 0.0, 3.0)
        b.line("inner", 0.1, 0.2)
        b.word("outer", 1.5, 2.0)
    spans = to_aligned_track(store, asset_id=ASSET).spans
    word = next(s for s in spans if s.level == "word")
    assert spans[word.parent].end_ms == 3000


def test_a_second_import_for_the_same_asset_is_refused(golden):
    store = from_aligned_track(golden)
    with pytest.raises(ValueError, match="already holds"):
        from_aligned_track(golden, store)
