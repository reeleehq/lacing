"""Aligned tracks: the wire model, the store converters, the golden vectors (lacing#107)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import lacing.bodies  # noqa: F401  registers
from lacing.bodies.aligned_track import (
    SPAN_SCHEMA_URI,
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
    a = next(iter(store.all()))
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
    assert list(tiers) == ["sections", "lines", "words", "syllables", "phones"]
    assert tiers["sections"].parent is None
    assert tiers["phones"].parent == "syllables"


def test_a_store_body_validates_against_its_schema(golden):
    store = from_aligned_track(golden)
    assert {a.body_schema_uri for a in store.all()} == {SPAN_SCHEMA_URI}
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
