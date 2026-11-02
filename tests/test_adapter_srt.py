"""Tests for the SubRip (SRT) adapter."""

from __future__ import annotations

from uuid import uuid4

import pytest

from lacing.adapters import find_adapter, get_adapter
from lacing.adapters import srt as adapter_module  # noqa: F401  registers
from lacing.adapters import webvtt
from lacing.model import Annotation, MediaRef, Provenance
from lacing.store import MemoryStore
from lacing.time import LossyTimeConversionError, RationalTime, TimeInterval


SAMPLE_SRT = """1
00:00:00,000 --> 00:00:01,500
Hello world

2
00:00:01,500 --> 00:00:03,000
Second cue
spans two lines

3
00:00:05,000 --> 00:01:06,250
<i>Italic</i> third cue
"""

# What real files do: BOM, CRLF, leading/extra/whitespace-only blank lines,
# '.' separator, position coordinates, no blank line between two cues, no
# final newline, non-sequential indices.
MESSY_SRT = (
    "﻿\r\n"
    "7\r\n"
    "00:00:01,001 --> 00:00:02.002 X1:100 X2:500 Y1:40 Y2:80\r\n"
    "first line\r\n"
    "second line\r\n"
    "\r\n"
    "   \r\n"
    "\r\n"
    "9\r\n"
    "01:02:03.456 --> 01:02:04,000\r\n"
    "middle\r\n"
    "12\r\n"
    "01:02:05,000 --> 01:02:06,000\r\n"
    "last, unterminated"
)


def _sorted(store):
    return sorted(store.all(), key=lambda a: a.interval.start.to_fraction())


def _cues(store):
    """Comparable view of a store: everything but ids and provenance."""
    return [
        (a.tier, a.body["text"], a.interval.start, a.interval.end)
        for a in _sorted(store)
    ]


def _ann(start: RationalTime, end: RationalTime, body: dict, *, tier="cues"):
    return Annotation(
        id=uuid4(),
        tier=tier,
        reference=MediaRef(asset_id="srt:sample", interval=TimeInterval(start, end)),
        body=body,
        body_schema_uri="annot://schema/srt-cue/v1",
        provenance=Provenance(
            was_generated_by="user:test",
            was_attributed_to="test",
            generated_at_time=RationalTime.zero(1000),
        ),
    )


def _ms(start_ms: int, end_ms: int, text: str, **kw):
    return _ann(
        RationalTime(start_ms, 1000), RationalTime(end_ms, 1000), {"text": text}, **kw
    )


# --- registry --------------------------------------------------------------


class TestRegistry:
    def test_registered(self):
        spec = get_adapter("srt")
        assert spec.version == "1.0.0"
        assert spec.body_schema_uris == ("annot://schema/srt-cue/v1",)

    def test_lookup_by_extension(self):
        assert find_adapter(extension=".srt").name == "srt"
        assert find_adapter(extension="SRT").name == "srt"

    def test_lookup_by_media_type(self):
        assert find_adapter(media_type="application/x-subrip").name == "srt"

    def test_generated_by(self):
        assert adapter_module.GENERATED_BY == "adapter:srt@1.0.0"


# --- load ------------------------------------------------------------------


class TestLoad:
    def test_typical_file(self):
        anns = _sorted(adapter_module.load(SAMPLE_SRT))
        assert [a.body for a in anns] == [
            {"text": "Hello world", "index": 1},
            {"text": "Second cue\nspans two lines", "index": 2},
            {"text": "<i>Italic</i> third cue", "index": 3},
        ]
        assert [(a.interval.start.value, a.interval.end.value) for a in anns] == [
            (0, 1500),
            (1500, 3000),
            (5000, 66250),
        ]
        assert {a.tier for a in anns} == {"cues"}

    def test_messy_file(self):
        anns = _sorted(adapter_module.load(MESSY_SRT))
        assert [a.body for a in anns] == [
            {"text": "first line\nsecond line", "index": 7},
            {"text": "middle", "index": 9},
            {"text": "last, unterminated", "index": 12},
        ]
        assert anns[0].interval == TimeInterval(
            RationalTime(1001, 1000), RationalTime(2002, 1000)
        )
        assert anns[1].interval.start == RationalTime(3723456, 1000)

    def test_exact_times(self):
        store = adapter_module.load("1\n00:00:01,001 --> 00:00:01,002\nx\n")
        (ann,) = store.all()
        assert ann.interval.start == RationalTime(1001, 1000)
        assert ann.interval.start.value == 1001
        assert ann.interval.end == RationalTime(1002, 1000)

    def test_exact_times_at_another_rate(self):
        store = adapter_module.load("1\n00:00:01,001 --> 00:00:02,000\nx\n", rate=48000)
        (ann,) = store.all()
        assert ann.interval.start == RationalTime(48048, 48000)

    def test_rate_that_cannot_hold_a_millisecond_raises(self):
        with pytest.raises(LossyTimeConversionError):
            adapter_module.load("1\n00:00:01,001 --> 00:00:02,000\nx\n", rate=24)

    def test_missing_index_line(self):
        (ann,) = adapter_module.load("00:00:01,000 --> 00:00:02,000\nno index\n").all()
        assert ann.body == {"text": "no index", "index": None}

    def test_empty_text_cue(self):
        anns = _sorted(
            adapter_module.load(
                "1\n00:00:01,000 --> 00:00:02,000\n\n2\n00:00:03,000 --> 00:00:04,000\nb\n"
            )
        )
        assert [a.body["text"] for a in anns] == ["", "b"]

    def test_empty_input(self):
        assert list(adapter_module.load(b"").all()) == []
        assert list(adapter_module.load("\n\n").all()) == []

    def test_from_bytes_with_bom(self):
        blob = SAMPLE_SRT.encode("utf-8-sig")
        assert _cues(adapter_module.load(blob)) == _cues(
            adapter_module.load(SAMPLE_SRT)
        )

    def test_from_path(self, tmp_path):
        path = tmp_path / "x.srt"
        path.write_bytes(MESSY_SRT.encode("utf-8"))
        expected = _cues(adapter_module.load(MESSY_SRT))
        assert _cues(adapter_module.load(path)) == expected
        assert _cues(adapter_module.load(str(path))) == expected

    def test_generic_loader_dispatches_on_extension(self, tmp_path):
        from lacing.adapters import load

        path = tmp_path / "x.srt"
        path.write_text(SAMPLE_SRT, encoding="utf-8")
        assert len(list(load(str(path)).all())) == 3

    def test_custom_tier_and_asset(self):
        store = adapter_module.load(SAMPLE_SRT, tier="subs", asset_id="movie")
        anns = list(store.all())
        assert {a.tier for a in anns} == {"subs"}
        assert {a.reference.asset_id for a in anns} == {"movie"}
        assert {t.name for t in store.tiers()} == {"subs"}

    def test_provenance(self):
        store = adapter_module.load(SAMPLE_SRT, attribution="thor")
        for ann in store.all():
            assert ann.provenance.was_generated_by == "adapter:srt@1.0.0"
            assert ann.provenance.was_attributed_to == "thor"
            assert ann.provenance.activity == "import"
            assert ann.provenance.generated_at_is_known
            assert ann.body_schema_uri == "annot://schema/srt-cue/v1"


# --- malformed input -------------------------------------------------------


class TestMalformed:
    @pytest.mark.parametrize(
        "timing",
        [
            "00:00:01 --> 00:00:02,000",  # no milliseconds
            "00:00:01,00 --> 00:00:02,000",  # two-digit milliseconds
            "00:00:01,000 -> 00:00:02,000",  # wrong arrow
            "00:00:01,000 --> 00:00:02,000 garbage",  # unknown trailer
            "00:61:01,000 --> 00:00:02,000",  # minutes out of range
        ],
    )
    def test_malformed_timing_line_names_its_line(self, timing):
        src = f"1\n00:00:00,000 --> 00:00:00,500\nok\n\n2\n{timing}\nbad\n"
        with pytest.raises(ValueError, match=r"^line 6: malformed SubRip timing"):
            adapter_module.load(src)

    def test_timing_line_without_arrow_after_index(self):
        with pytest.raises(ValueError, match=r"^line 2: malformed SubRip timing"):
            adapter_module.load("1\n00:00:01,000 00:00:02,000\nx\n")

    def test_index_without_timing_line(self):
        with pytest.raises(ValueError, match=r"^line 1: cue 1 has no timing line"):
            adapter_module.load("1\n\n")

    def test_stray_text(self):
        with pytest.raises(ValueError, match=r"^line 1: expected a cue index"):
            adapter_module.load("not a subtitle file\n")

    def test_end_before_start(self):
        with pytest.raises(ValueError, match=r"^line 2: cue ends before it starts"):
            adapter_module.load("1\n00:00:02,000 --> 00:00:01,000\nx\n")


# --- dump ------------------------------------------------------------------


class TestDump:
    def test_dump_bytes(self):
        s = MemoryStore()
        s.add(_ms(1001, 2500, "Hello\nworld"))
        assert (
            adapter_module.dump(s)
            == b"1\n00:00:01,001 --> 00:00:02,500\nHello\nworld\n"
        )

    def test_dump_to_path(self, tmp_path):
        s = MemoryStore()
        s.add(_ms(0, 1000, "Hi"))
        out = tmp_path / "x.srt"
        assert adapter_module.dump(s, out) is None
        assert out.read_bytes() == adapter_module.dump(s)

    def test_dump_renumbers_in_start_then_end_order(self):
        s = MemoryStore()
        for start, end, text, index in [
            (2000, 3000, "third", 40),
            (0, 1000, "second", 2),
            (0, 500, "first", 99),
        ]:
            s.add(
                _ann(
                    RationalTime(start, 1000),
                    RationalTime(end, 1000),
                    {"text": text, "index": index},
                )
            )
        assert adapter_module.dump(s).decode("utf-8") == (
            "1\n00:00:00,000 --> 00:00:00,500\nfirst\n\n"
            "2\n00:00:00,000 --> 00:00:01,000\nsecond\n\n"
            "3\n00:00:02,000 --> 00:00:03,000\nthird\n"
        )

    def test_dump_filters_by_tier(self):
        s = MemoryStore()
        s.add(_ms(0, 1000, "alpha"))
        s.add(_ms(1000, 2000, "omega", tier="other"))
        blob = adapter_module.dump(s, tier="cues")
        assert b"alpha" in blob and b"omega" not in blob

    def test_dump_skips_bodies_without_text(self):
        s = MemoryStore()
        s.add(_ms(0, 1000, "kept"))
        s.add(_ann(RationalTime(1, 1000), RationalTime(2, 1000), {"label": "x"}))
        s.add(_ann(RationalTime(3, 1000), RationalTime(4, 1000), {"text": None}))
        assert adapter_module.dump(s) == b"1\n00:00:00,000 --> 00:00:01,000\nkept\n"

    def test_dump_empty_store(self):
        assert adapter_module.dump(MemoryStore()) == b""

    def test_blank_lines_inside_text_are_dropped(self):
        s = MemoryStore()
        s.add(_ms(0, 1000, "a\n\n  \nb"))
        (ann,) = adapter_module.load(adapter_module.dump(s)).all()
        assert ann.body["text"] == "a\nb"

    def test_sub_millisecond_times_truncate_and_keep_start_le_end(self):
        s = MemoryStore()
        # 1/3 s and 2/3 s -> 333 ms and 666 ms (truncated, not rounded to 667)
        s.add(_ann(RationalTime(1, 3), RationalTime(2, 3), {"text": "thirds"}))
        # A sub-ms cue inside one millisecond: [1.0, ~1.396) ms -> [1, 1] ms
        s.add(_ann(RationalTime(48, 48000), RationalTime(67, 48000), {"text": "tiny"}))
        # 999.9 ms -> 999 ms (truncated, never rounded across a second)
        s.add(
            _ann(
                RationalTime(9999, 10000), RationalTime(10001, 10000), {"text": "edge"}
            )
        )
        blob = adapter_module.dump(s).decode("utf-8")
        assert "00:00:00,333 --> 00:00:00,666\nthirds" in blob
        assert "00:00:00,001 --> 00:00:00,001\ntiny" in blob
        assert "00:00:00,999 --> 00:00:01,000\nedge" in blob
        for ann in adapter_module.load(blob).all():
            assert ann.interval.start <= ann.interval.end

    def test_negative_time_raises(self):
        s = MemoryStore()
        s.add(_ann(RationalTime(-1, 1000), RationalTime(5, 1000), {"text": "x"}))
        with pytest.raises(ValueError, match="negative"):
            adapter_module.dump(s)


# --- round trips -----------------------------------------------------------


class TestRoundTrip:
    @pytest.mark.parametrize("sample", [SAMPLE_SRT, MESSY_SRT])
    def test_load_dump_load(self, sample):
        original = adapter_module.load(sample)
        loaded = adapter_module.load(adapter_module.dump(original))
        assert _cues(loaded) == _cues(original)

    def test_dump_is_a_fixed_point(self):
        once = adapter_module.dump(adapter_module.load(MESSY_SRT))
        assert adapter_module.dump(adapter_module.load(once)) == once

    def test_typical_file_is_reproduced(self):
        assert adapter_module.dump(adapter_module.load(SAMPLE_SRT)).decode() == (
            SAMPLE_SRT
        )

    def test_webvtt_to_srt_to_webvtt(self):
        from tests.test_adapter_webvtt import SAMPLE_VTT

        vtt = webvtt.load(SAMPLE_VTT)
        via_srt = adapter_module.load(adapter_module.dump(vtt))
        back = webvtt.load(webvtt.dump(via_srt))
        assert _cues(via_srt) == _cues(vtt)
        assert _cues(back) == _cues(vtt)
