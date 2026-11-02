"""Tests for the WebVTT adapter."""

from __future__ import annotations

from uuid import uuid4

import pytest

from lacing.adapters import find_adapter, get_adapter
from lacing.adapters import webvtt as adapter_module  # noqa: F401  registers
from lacing.model import Annotation, MediaRef, Provenance
from lacing.store import MemoryStore
from lacing.tier import Tier
from lacing.time import RationalTime, TimeInterval


SAMPLE_VTT = """WEBVTT

1
00:00:00.000 --> 00:00:01.500 align:start
Hello world

2
00:00:01.500 --> 00:00:03.000
Second cue
spans two lines

00:00:05.000 --> 00:00:06.250
A cue with no id
"""


def _ann(
    tier: str,
    start_ms: int,
    end_ms: int,
    text: str,
    *,
    cue_id: str | None = None,
    settings: dict | None = None,
) -> Annotation:
    return Annotation(
        id=uuid4(),
        tier=tier,
        reference=MediaRef(
            asset_id="webvtt:sample",
            interval=TimeInterval(
                RationalTime(start_ms, 1000),
                RationalTime(end_ms, 1000),
            ),
        ),
        body={"text": text, "id": cue_id, "settings": settings or {}},
        body_schema_uri="annot://schema/webvtt-cue/v1",
        provenance=Provenance(
            was_generated_by="user:test",
            was_attributed_to="test",
            generated_at_time=RationalTime.zero(1000),
        ),
    )


# --- registry --------------------------------------------------------------


class TestRegistry:
    def test_webvtt_registered(self):
        spec = get_adapter("webvtt")
        assert spec.name == "webvtt"
        assert ".vtt" in spec.extensions

    def test_lookup_by_extension(self):
        assert find_adapter(extension=".vtt") is not None

    def test_lookup_by_media_type(self):
        assert find_adapter(media_type="text/vtt") is not None


# --- timestamp parsing ----------------------------------------------------


class TestTimestamp:
    def test_parse_with_hours(self):
        t = adapter_module._parse_timestamp("01:02:03.456", rate=1000)
        # 1h 2m 3s 456ms = 3723456 ms
        assert t.value == 3723456

    def test_parse_without_hours(self):
        t = adapter_module._parse_timestamp("00:01.250", rate=1000)
        assert t.value == 1250

    def test_format_round_trip(self):
        t = RationalTime(3723456, 1000)
        s = adapter_module._format_timestamp(t)
        assert s == "01:02:03.456"
        assert adapter_module._parse_timestamp(s, rate=1000) == t

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            adapter_module._parse_timestamp("nope", rate=1000)


# --- load ------------------------------------------------------------------


class TestLoad:
    def test_load_from_string(self):
        store = adapter_module.load(SAMPLE_VTT, rate=1000)
        assert len(list(store.all())) == 3

    def test_load_from_bytes(self):
        store = adapter_module.load(SAMPLE_VTT.encode("utf-8"), rate=1000)
        assert len(list(store.all())) == 3

    def test_load_from_path(self, tmp_path):
        path = tmp_path / "x.vtt"
        path.write_text(SAMPLE_VTT, encoding="utf-8")
        store = adapter_module.load(path, rate=1000)
        assert len(list(store.all())) == 3

    def test_load_default_tier(self):
        store = adapter_module.load(SAMPLE_VTT, rate=1000)
        names = {t.name for t in store.tiers()}
        assert names == {"cues"}

    def test_load_custom_tier(self):
        store = adapter_module.load(SAMPLE_VTT, rate=1000, tier="captions")
        anns = list(store.all())
        assert all(a.tier == "captions" for a in anns)

    def test_cue_intervals(self):
        store = adapter_module.load(SAMPLE_VTT, rate=1000)
        anns = sorted(store.all(), key=lambda a: a.interval.start.to_fraction())
        assert anns[0].interval.start.value == 0
        assert anns[0].interval.end.value == 1500
        assert anns[1].interval.start.value == 1500
        assert anns[1].interval.end.value == 3000

    def test_cue_id_captured(self):
        store = adapter_module.load(SAMPLE_VTT, rate=1000)
        anns = sorted(store.all(), key=lambda a: a.interval.start.to_fraction())
        assert anns[0].body["id"] == "1"
        assert anns[1].body["id"] == "2"
        assert anns[2].body["id"] is None

    def test_settings_captured(self):
        store = adapter_module.load(SAMPLE_VTT, rate=1000)
        anns = sorted(store.all(), key=lambda a: a.interval.start.to_fraction())
        assert anns[0].body["settings"] == {"align": "start"}
        assert anns[1].body["settings"] == {}

    def test_multiline_text(self):
        store = adapter_module.load(SAMPLE_VTT, rate=1000)
        anns = sorted(store.all(), key=lambda a: a.interval.start.to_fraction())
        assert anns[1].body["text"] == "Second cue\nspans two lines"

    def test_provenance(self):
        store = adapter_module.load(SAMPLE_VTT, rate=1000, attribution="thor")
        ann = next(store.all())
        assert ann.provenance.was_generated_by == "adapter:webvtt@1.0.0"
        assert ann.provenance.was_attributed_to == "thor"
        assert ann.provenance.activity == "import"

    def test_missing_header_raises(self):
        with pytest.raises(ValueError):
            adapter_module.load("not a webvtt file", rate=1000)

    def test_skips_note_blocks(self):
        vtt = """WEBVTT

NOTE
This is a comment block

00:00:00.000 --> 00:00:01.000
hello
"""
        store = adapter_module.load(vtt, rate=1000)
        assert len(list(store.all())) == 1


# --- dump ------------------------------------------------------------------


class TestDump:
    def test_dump_returns_bytes(self):
        s = MemoryStore()
        s.add(_ann("cues", 0, 1500, "Hello"))
        blob = adapter_module.dump(s)
        assert isinstance(blob, bytes)
        assert blob.startswith(b"WEBVTT")
        assert b"00:00:00.000 --> 00:00:01.500" in blob
        assert b"Hello" in blob

    def test_dump_to_path(self, tmp_path):
        s = MemoryStore()
        s.add(_ann("cues", 0, 1500, "Hi"))
        out = tmp_path / "x.vtt"
        result = adapter_module.dump(s, out)
        assert result is None
        assert out.read_text(encoding="utf-8").startswith("WEBVTT")

    def test_dump_includes_id_when_present(self):
        s = MemoryStore()
        s.add(_ann("cues", 0, 1500, "Hi", cue_id="cue-a"))
        blob = adapter_module.dump(s)
        assert b"cue-a" in blob

    def test_dump_includes_settings(self):
        s = MemoryStore()
        s.add(_ann("cues", 0, 1500, "Hi", settings={"align": "start"}))
        blob = adapter_module.dump(s)
        assert b"align:start" in blob

    def test_dump_filters_by_tier(self):
        s = MemoryStore()
        s.add(_ann("cues", 0, 1000, "alpha"))
        s.add(_ann("other", 1000, 2000, "omega"))
        blob = adapter_module.dump(s, tier="cues")
        assert b"alpha" in blob
        assert b"omega" not in blob

    def test_dump_sorts_by_start(self):
        s = MemoryStore()
        s.add(_ann("cues", 2000, 3000, "second"))
        s.add(_ann("cues", 0, 1000, "first"))
        blob = adapter_module.dump(s).decode("utf-8")
        assert blob.index("first") < blob.index("second")


# --- round trip ------------------------------------------------------------


class TestRoundTrip:
    def test_roundtrip(self):
        original = adapter_module.load(SAMPLE_VTT, rate=1000)
        blob = adapter_module.dump(original)
        loaded = adapter_module.load(blob, rate=1000)
        assert len(list(loaded.all())) == len(list(original.all()))

        original_cues = sorted(
            (
                a.body["text"],
                a.body.get("id"),
                a.interval.start.value,
                a.interval.end.value,
            )
            for a in original.all()
        )
        loaded_cues = sorted(
            (
                a.body["text"],
                a.body.get("id"),
                a.interval.start.value,
                a.interval.end.value,
            )
            for a in loaded.all()
        )
        assert loaded_cues == original_cues


# --- edge cases (lacing#126) ---------------------------------------------------


def _one_cue_store(start, end, text):
    store = MemoryStore()
    store.add(
        Annotation(
            id=uuid4(),
            tier="cues",
            reference=MediaRef(asset_id="x", interval=TimeInterval(start, end)),
            body={"text": text},
            body_schema_uri="annot://schema/webvtt-cue/v1",
            provenance=Provenance(
                was_generated_by="user:t",
                was_attributed_to="t",
                generated_at_time=RationalTime.now(),
            ),
        )
    )
    return store


def test_a_negative_time_is_refused_not_written_as_a_bad_timestamp():
    store = _one_cue_store(RationalTime(-1, 3000), RationalTime(1, 1), "x")
    with pytest.raises(ValueError, match="negative"):
        adapter_module.dump(store)


def test_blank_lines_inside_cue_text_are_dropped_so_the_file_round_trips():
    store = _one_cue_store(RationalTime(0, 1), RationalTime(1, 1), "one\n\ntwo")
    back = adapter_module.load(adapter_module.dump(store))
    assert [a.body["text"] for a in back.all()] == ["one\ntwo"]


@pytest.mark.parametrize(
    "text, reloaded",
    [
        ("one\u2028\u2028two", "one\u2028\u2028two"),  # not a WebVTT line break
        ("one\x0c\x0ctwo", "one\x0c\x0ctwo"),
        ("  \nx", "x"),  # a whitespace-only line used to swallow the rest
    ],
)
def test_text_survives_a_round_trip(text, reloaded):
    store = _one_cue_store(RationalTime(0, 1), RationalTime(1, 1), text)
    back = adapter_module.load(adapter_module.dump(store))
    assert [a.body["text"] for a in back.all()] == [reloaded]


def test_an_arrow_inside_cue_text_is_escaped_so_a_player_sees_one_cue():
    """lacing#129: a spec-following parser starts a cue at any '-->' line."""
    text = "x\n00:00:05.000 --> 00:00:06.000\ny"
    store = _one_cue_store(RationalTime(0, 1), RationalTime(1, 1), text)
    blob = adapter_module.dump(store).decode()
    assert "-->" not in blob.split("\n", 3)[3]  # only the timing line has one
    assert [a.body["text"] for a in adapter_module.load(blob).all()] == [
        "x\n00:00:05.000 --&gt; 00:00:06.000\ny"
    ]


@pytest.mark.parametrize("cue_id", ["a-->b", "x\ny", "x\ry"])
def test_a_cue_id_webvtt_cannot_write_is_refused(cue_id):
    store = _one_cue_store(RationalTime(0, 1), RationalTime(1, 1), "t")
    [ann] = store.all()
    store2 = MemoryStore()
    store2.add(ann.model_copy(update={"body": {"text": "t", "id": cue_id}}))
    with pytest.raises(ValueError, match="cue id"):
        adapter_module.dump(store2)


@pytest.mark.parametrize("cue_id", ["NOTE 1", "STYLE", "REGION x"])
def test_a_cue_whose_id_starts_like_a_block_keyword_loads(cue_id):
    blob = f"WEBVTT\n\n{cue_id}\n00:00:01.000 --> 00:00:02.000\nhi\n"
    [ann] = adapter_module.load(blob).all()
    assert (ann.body["id"], ann.body["text"]) == (cue_id, "hi")


def test_a_note_block_is_still_skipped():
    blob = "WEBVTT\n\nNOTE a comment\nmore\n\n00:00:01.000 --> 00:00:02.000\nhi\n"
    assert [a.body["text"] for a in adapter_module.load(blob).all()] == ["hi"]
