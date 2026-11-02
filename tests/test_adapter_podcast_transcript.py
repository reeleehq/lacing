"""Tests for the Podcasting 2.0 podcast:transcript JSON adapter."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from lacing.adapters import (
    find_adapter,
    find_adapter_for_path,
    get_adapter,
    load as registry_load,
)
from lacing.adapters import podcast_transcript as adapter_module  # registers
from lacing.adapters import srt, web_annotation  # noqa: F401  registers
from lacing.model import Annotation, MediaRef, Provenance
from lacing.store import MemoryStore
from lacing.time import LossyTimeConversionError, RationalTime, TimeInterval


# The spec's example file, docs/examples/transcripts/example.json, verbatim.
SPEC_EXAMPLE = """{
  "version": "1.0.0",
  "segments": [
    {
      "speaker": "Darth Vader",
      "startTime": 0.5,
      "endTime": 0.75,
      "body": "I"
    },
    {
      "speaker": "Darth Vader",
      "startTime": 1,
      "endTime": 1.25,
      "body": "am"
    },
    {
      "speaker": "Darth Vader",
      "startTime": 1.5,
      "endTime": 2.0,
      "body": "your"
    },
    {
      "speaker": "Darth Vader",
      "startTime": 2.25,
      "endTime": 2.50,
      "body": "father."
    },
    {
      "speaker": "Luke",
      "startTime": 2.75,
      "endTime": 3.0,
      "body": "Nooooo"
    }
  ]
}"""


def _doc(*segments, version="1.0.0"):
    return json.dumps({"version": version, "segments": list(segments)})


def _sorted(store):
    return sorted(store.all(), key=lambda a: a.interval.start.to_fraction())


def _view(store):
    """Comparable view of a store: everything but ids and provenance."""
    return [
        (a.tier, a.body, a.interval.start, a.interval.end, a.body_schema_uri)
        for a in _sorted(store)
    ]


def _ann(start, end, body, *, tier="cues", uri="annot://schema/srt-cue/v1"):
    return Annotation(
        id=uuid4(),
        tier=tier,
        reference=MediaRef(asset_id="a", interval=TimeInterval(start, end)),
        body=body,
        body_schema_uri=uri,
        provenance=Provenance(
            was_generated_by="user:test",
            was_attributed_to="test",
            generated_at_time=RationalTime.zero(1000),
        ),
    )


# --- registry --------------------------------------------------------------


class TestRegistry:
    def test_registered(self):
        spec = get_adapter("podcast_transcript")
        assert spec.version == "1.0.0"
        assert spec.body_schema_uris == (
            "annot://schema/podcast-transcript-segment/v1",
        )
        assert adapter_module.GENERATED_BY == "adapter:podcast_transcript@1.0.0"

    def test_lookup_by_compound_extension(self):
        assert find_adapter(extension=".transcript.json").name == "podcast_transcript"
        assert find_adapter_for_path("ep1.transcript.json").name == (
            "podcast_transcript"
        )
        assert find_adapter_for_path("EP1.Transcript.JSON").name == (
            "podcast_transcript"
        )

    def test_does_not_claim_application_json(self):
        """The spec's media type is plain JSON: nobody claims it, and a bare
        ``.json`` stays with the W3C Web Annotation adapter."""
        assert "application/json" not in get_adapter("podcast_transcript").media_types
        assert find_adapter(media_type="application/json") is None
        assert find_adapter(extension=".json").name == "web_annotation"
        assert find_adapter_for_path("x.json").name == "web_annotation"

    def test_registry_load_picks_it_from_the_path(self, tmp_path):
        path = tmp_path / "ep.transcript.json"
        path.write_text(SPEC_EXAMPLE, encoding="utf-8")
        assert len(list(registry_load(path, rate=1000).all())) == 5


# --- load ------------------------------------------------------------------


class TestLoad:
    def test_spec_example(self):
        store = adapter_module.load(SPEC_EXAMPLE)
        anns = _sorted(store)
        assert [a.body for a in anns] == [
            {"text": "I", "speaker": "Darth Vader"},
            {"text": "am", "speaker": "Darth Vader"},
            {"text": "your", "speaker": "Darth Vader"},
            {"text": "father.", "speaker": "Darth Vader"},
            {"text": "Nooooo", "speaker": "Luke"},
        ]
        assert [(a.interval.start.value, a.interval.end.value) for a in anns] == [
            (500, 750),
            (1000, 1250),
            (1500, 2000),
            (2250, 2500),
            (2750, 3000),
        ]
        assert {a.tier for a in anns} == {"segments"}
        assert [t.name for t in store.tiers()] == ["segments"]
        assert {a.body_schema_uri for a in anns} == {
            "annot://schema/podcast-transcript-segment/v1"
        }

    def test_exact_times(self):
        store = adapter_module.load(
            _doc({"startTime": 1.001, "endTime": 2.333, "body": "x"})
        )
        (a,) = store.all()
        assert a.interval.start == RationalTime(1001, 1000)
        assert a.interval.start.rate == 1000 and a.interval.start.value == 1001
        assert a.interval.end.value == 2333

    def test_0_333_at_rate_1000_is_exact(self):
        # 0.333 as a float is 0.33300000000000001820...; read as a decimal
        # it is exactly 333/1000.
        (a,) = adapter_module.load(
            _doc({"startTime": 0.333, "endTime": 0.333, "body": "x"}), rate=1000
        ).all()
        assert a.interval.start == RationalTime(333, 1000)

    def test_other_rate(self):
        (a,) = adapter_module.load(
            _doc({"startTime": 1.001, "endTime": 2, "body": "x"}), rate=24000
        ).all()
        assert a.interval.start == RationalTime(24024, 24000)

    def test_lossy_time_raises_naming_the_segment(self):
        doc = _doc(
            {"startTime": 0, "endTime": 1, "body": "ok"},
            {"startTime": 1.0005, "endTime": 2, "body": "too fine"},
        )
        with pytest.raises(LossyTimeConversionError, match=r"segments\[1\]\.startTime"):
            adapter_module.load(doc, rate=1000)

    def test_exponent_notation(self):
        doc = '{"segments": [{"startTime": 1.5e1, "endTime": 2E+1, "body": "x"}]}'
        (a,) = adapter_module.load(doc).all()
        assert (a.interval.start.value, a.interval.end.value) == (15000, 20000)

    def test_missing_speaker_is_none(self):
        (a,) = adapter_module.load(
            _doc({"startTime": 0, "endTime": 1, "body": "x"})
        ).all()
        assert a.body == {"text": "x", "speaker": None}

    def test_missing_end_time_is_inferred(self):
        store = adapter_module.load(
            _doc(
                {"startTime": 0, "body": "a"},
                {"startTime": 2, "endTime": 3, "body": "b"},
                {"startTime": 5, "body": "c"},
            )
        )
        a, b, c = _sorted(store)
        assert (a.interval.start.value, a.interval.end.value) == (0, 2000)
        assert a.body["end_inferred"] is True
        assert "end_inferred" not in b.body
        assert (c.interval.start.value, c.interval.end.value) == (5000, 5000)  # point
        assert c.body["end_inferred"] is True

    def test_extra_segment_fields_are_kept(self):
        (a,) = adapter_module.load(
            _doc({"startTime": 0, "endTime": 1, "body": "x", "confidence": 0.9})
        ).all()
        assert a.body["extra"] == {"confidence": 0.9}

    def test_bytes_and_path(self, tmp_path):
        assert len(list(adapter_module.load(SPEC_EXAMPLE.encode()).all())) == 5
        path = tmp_path / "t.transcript.json"
        path.write_text(SPEC_EXAMPLE, encoding="utf-8")
        assert len(list(adapter_module.load(path).all())) == 5
        assert len(list(adapter_module.load(str(path)).all())) == 5

    def test_custom_tier_and_asset(self):
        store = adapter_module.load(SPEC_EXAMPLE, tier="words", asset_id="ep1.mp3")
        assert {a.tier for a in store.all()} == {"words"}
        assert {a.reference.asset_id for a in store.all()} == {"ep1.mp3"}

    def test_provenance(self):
        store = adapter_module.load(SPEC_EXAMPLE, attribution="user:alice")
        for a in store.all():
            assert a.provenance.was_generated_by == "adapter:podcast_transcript@1.0.0"
            assert a.provenance.was_attributed_to == "user:alice"
            assert a.provenance.activity == "import"
            assert a.provenance.generated_at_is_known


class TestMalformed:
    @pytest.mark.parametrize(
        ("doc", "match"),
        [
            ("[]", "JSON object"),
            ("{not json", "not valid JSON"),
            ('{"version": "1.0.0"}', "segments must be a list"),
            ('{"segments": {}}', "segments must be a list"),
            ('{"version": 1, "segments": []}', "version must be a string"),
            (_doc("x"), r"segments\[0\]: must be an object"),
            (_doc({"endTime": 1, "body": "x"}), r"segments\[0\]: missing startTime"),
            (_doc({"startTime": 0, "endTime": 1}), r"segments\[0\]: body"),
            (
                _doc({"startTime": 0, "endTime": 1, "body": "x", "speaker": 3}),
                r"segments\[0\]: speaker",
            ),
            (
                _doc({"startTime": "1", "endTime": 2, "body": "x"}),
                r"segments\[0\]\.startTime: expected a number",
            ),
            (
                _doc({"startTime": True, "endTime": 2, "body": "x"}),
                r"segments\[0\]\.startTime: expected a number",
            ),
            (
                _doc({"startTime": -1, "endTime": 2, "body": "x"}),
                r"segments\[0\]\.startTime: negative",
            ),
            (
                '{"segments": [{"startTime": NaN, "endTime": 1, "body": "x"}]}',
                r"segments\[0\]\.startTime: not a finite number",
            ),
            (
                '{"segments": [{"startTime": 1e999999999, "body": "x"}]}',
                r"segments\[0\]\.startTime: number out of range",
            ),
            (
                _doc(
                    {"startTime": 0, "endTime": 1, "body": "x"},
                    {"startTime": 3, "endTime": 2, "body": "y"},
                ),
                r"segments\[1\]: endTime 2 is before startTime",
            ),
        ],
    )
    def test_raises_value_error(self, doc, match):
        with pytest.raises(ValueError, match=match):
            adapter_module.load(doc)


# --- dump ------------------------------------------------------------------


class TestDump:
    def test_spec_example_round_trips(self):
        store1 = adapter_module.load(SPEC_EXAMPLE)
        blob = adapter_module.dump(store1)
        store2 = adapter_module.load(blob)
        assert _view(store1) == _view(store2)
        # Same JSON value as the spec's file (2.50 and 2.0 written 2.5 and 2).
        assert json.loads(blob) == json.loads(SPEC_EXAMPLE)

    def test_field_order_follows_the_spec(self):
        blob = adapter_module.dump(adapter_module.load(SPEC_EXAMPLE))
        first = json.loads(blob)["segments"][0]
        assert list(first) == ["speaker", "startTime", "endTime", "body"]

    def test_exact_decimals_are_written(self):
        store = MemoryStore()
        store.add(_ann(RationalTime(1, 8), RationalTime(1001, 1000), {"text": "x"}))
        text = adapter_module.dump(store).decode()
        assert '"startTime": 0.125,' in text
        assert '"endTime": 1.001,' in text

    def test_whole_seconds_are_integers(self):
        store = MemoryStore()
        store.add(_ann(RationalTime(94, 1), RationalTime(188000, 1000), {"text": "x"}))
        text = adapter_module.dump(store).decode()
        assert '"startTime": 94,' in text and '"endTime": 188,' in text

    def test_non_terminating_times_truncate_to_the_millisecond(self):
        store = MemoryStore()
        store.add(_ann(RationalTime(1, 3), RationalTime(2, 3), {"text": "a"}))
        store.add(_ann(RationalTime(2, 3), RationalTime(2001, 3000), {"text": "b"}))
        segs = json.loads(adapter_module.dump(store), parse_float=str)["segments"]
        assert [(s["startTime"], s["endTime"]) for s in segs] == [
            ("0.333", "0.666"),
            ("0.666", "0.667"),
        ]

    def test_no_floats_in_large_times(self):
        # 123456789.001 s is not a double: a float would write ...0010000467.
        t = RationalTime(123456789001, 1000)
        store = MemoryStore()
        store.add(_ann(t, t, {"text": "x"}))
        assert '"startTime": 123456789.001' in adapter_module.dump(store).decode()

    def test_negative_time_raises(self):
        store = MemoryStore()
        store.add(_ann(RationalTime(-1, 1000), RationalTime(0, 1000), {"text": "x"}))
        with pytest.raises(ValueError, match="negative"):
            adapter_module.dump(store)

    def test_missing_end_times_round_trip(self):
        doc = _doc(
            {"startTime": 0, "body": "a"},
            {"startTime": 2, "endTime": 3, "body": "b"},
            {"startTime": 5, "body": "c"},
        )
        blob = adapter_module.dump(adapter_module.load(doc))
        assert json.loads(blob) == json.loads(doc)

    def test_edited_inferred_end_is_written(self):
        store = adapter_module.load(
            _doc({"startTime": 0, "body": "a"}, {"startTime": 2, "body": "b"})
        )
        a = _sorted(store)[0]
        new_iv = TimeInterval(a.interval.start, RationalTime(1500, 1000))
        ref = MediaRef(asset_id=a.reference.asset_id, interval=new_iv)
        store.update(a.model_copy(update={"reference": ref}))
        segs = json.loads(adapter_module.dump(store))["segments"]
        assert segs[0]["endTime"] == 1.5
        assert "endTime" not in segs[1]

    def test_extra_fields_round_trip(self):
        doc = _doc({"startTime": 0, "endTime": 1, "body": "x", "lang": "en"})
        assert json.loads(adapter_module.dump(adapter_module.load(doc))) == json.loads(
            doc
        )

    def test_unicode_is_written_as_is(self):
        doc = _doc({"startTime": 0, "endTime": 1, "body": "café ☕"})
        blob = adapter_module.dump(adapter_module.load(doc))
        assert "café ☕".encode() in blob

    def test_tier_filter_and_non_text_bodies(self):
        store = MemoryStore()
        store.add(_ann(RationalTime(0, 1000), RationalTime(1, 1000), {"text": "a"}))
        store.add(
            _ann(RationalTime(0, 1000), RationalTime(1, 1000), {"text": "b"}, tier="o")
        )
        store.add(_ann(RationalTime(0, 1000), RationalTime(1, 1000), {"title": "c"}))
        segs = json.loads(adapter_module.dump(store))["segments"]
        assert sorted(s["body"] for s in segs) == ["a", "b"]
        segs = json.loads(adapter_module.dump(store, tier="o"))["segments"]
        assert [s["body"] for s in segs] == ["b"]

    def test_empty_store(self):
        assert json.loads(adapter_module.dump(MemoryStore())) == {
            "version": "1.0.0",
            "segments": [],
        }

    def test_write_to_path(self, tmp_path):
        out = tmp_path / "out.transcript.json"
        assert adapter_module.dump(adapter_module.load(SPEC_EXAMPLE), out) is None
        assert len(list(adapter_module.load(out).all())) == 5


# --- cross-format ----------------------------------------------------------


SAMPLE_SRT = """1
00:00:00,000 --> 00:00:01,500
Hello world

2
00:00:01,500 --> 00:00:03,001
Second cue
spans two lines

3
00:00:05,000 --> 00:01:06,250
third cue
"""


class TestCrossFormat:
    def test_srt_to_transcript_to_srt(self):
        transcript = adapter_module.dump(srt.load(SAMPLE_SRT))
        segs = json.loads(transcript, parse_float=str)["segments"]
        assert [(s["startTime"], s["endTime"]) for s in segs] == [
            (0, "1.5"),
            ("1.5", "3.001"),
            (5, "66.25"),
        ]
        assert segs[1]["body"] == "Second cue\nspans two lines"
        assert "speaker" not in segs[0]
        back = srt.dump(adapter_module.load(transcript))
        assert back.decode() == SAMPLE_SRT

    def test_speaker_survives_a_store_from_another_format(self):
        store = MemoryStore()
        store.add(
            _ann(
                RationalTime(0, 1000),
                RationalTime(1, 1000),
                {"text": "hi", "speaker": "Ann"},
                tier="turns",
            )
        )
        (seg,) = json.loads(adapter_module.dump(store))["segments"]
        assert seg["speaker"] == "Ann"


# --- review fixes (lacing#107) ---------------------------------------------


class TestNonFiniteAndInexactNumbers:
    """A number a float cannot hold is refused on load, naming the field,
    rather than accepted and then failing the dump."""

    @pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity", "1e400"])
    def test_non_finite_extra_field_refused_on_load(self, literal):
        doc = (
            '{"segments": [{"startTime": 0, "body": "a"}, '
            f'{{"startTime": 1, "body": "b", "confidence": {literal}}}]}}'
        )
        with pytest.raises(
            ValueError, match=r"segments\[1\]\.confidence: not a finite number"
        ):
            adapter_module.load(doc)

    def test_more_digits_than_a_float_refused(self):
        doc = '{"segments": [{"startTime": 0, "body": "a", "n": 12345678901234567.5}]}'
        with pytest.raises(ValueError, match=r"segments\[0\]\.n: .*exactly"):
            adapter_module.load(doc)

    def test_float_noise_in_extra_field_round_trips(self):
        doc = '{"segments": [{"startTime": 0, "body": "a", "n": 0.30000000000000004}]}'
        blob = adapter_module.dump(adapter_module.load(doc))
        assert b'"n": 0.30000000000000004' in blob


class TestInferredRate:
    def test_default_rate_holds_a_16khz_sample(self):
        doc = _doc({"startTime": 0.0000625, "endTime": 1, "body": "x"})
        (a,) = adapter_module.load(doc).all()
        assert a.interval.start == RationalTime(625, 10**7)
        assert a.interval.start.rate == 10**7
        assert json.loads(adapter_module.dump(adapter_module.load(doc))) == (
            json.loads(doc)
        )

    def test_default_rate_holds_js_float_noise(self):
        doc = _doc({"startTime": 0.30000000000000004, "endTime": 1, "body": "x"})
        blob = adapter_module.dump(adapter_module.load(doc))
        assert b'"startTime": 0.30000000000000004' in blob

    def test_default_rate_is_at_least_milliseconds(self):
        (a,) = adapter_module.load(
            _doc({"startTime": 1, "endTime": 2, "body": "x"})
        ).all()
        assert a.interval.start.rate == 1000

    def test_explicit_rate_still_raises_naming_the_rate_that_works(self):
        doc = _doc({"startTime": 0.0000625, "endTime": 1, "body": "x"})
        with pytest.raises(LossyTimeConversionError, match=r"rate=10000000 holds"):
            adapter_module.load(doc, rate=1000)


class TestNullIsAbsent:
    def test_null_end_time_is_inferred_and_left_out_on_dump(self):
        doc = _doc(
            {"startTime": 0, "endTime": None, "body": "a"},
            {"startTime": 2, "endTime": 3, "body": "b"},
        )
        a, _ = _sorted(adapter_module.load(doc))
        assert (a.interval.end.value, a.body["end_inferred"]) == (2000, True)
        out = json.loads(adapter_module.dump(adapter_module.load(doc)))
        assert "endTime" not in out["segments"][0]

    def test_null_speaker_is_left_out_on_dump(self):
        doc = _doc({"startTime": 0, "endTime": 1, "body": "a", "speaker": None})
        (a,) = adapter_module.load(doc).all()
        assert a.body["speaker"] is None
        out = json.loads(adapter_module.dump(adapter_module.load(doc)))
        assert "speaker" not in out["segments"][0]
