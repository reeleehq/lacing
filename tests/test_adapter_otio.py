"""Tests for the OpenTimelineIO (OTIO) adapter."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fractions import Fraction

import pytest

otio = pytest.importorskip("opentimelineio")

from lacing.adapters import find_adapter, get_adapter  # noqa: E402
from lacing.adapters import otio as adapter_module  # noqa: E402, F401  registers
from lacing.model import Annotation, MediaRef, Provenance  # noqa: E402
from lacing.store import MemoryStore  # noqa: E402
from lacing.tier import Tier  # noqa: E402
from lacing.time import RationalTime, TimeInterval  # noqa: E402


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def build_sample_otio(tmp_path) -> Path:
    """Build a small OTIO file: timeline with two tracks of clips and a marker."""
    tl = otio.schema.Timeline(name="demo")

    video = otio.schema.Track(name="V1", kind=otio.schema.TrackKind.Video)
    tl.tracks.append(video)
    clip1 = otio.schema.Clip(
        name="Intro",
        media_reference=otio.schema.ExternalReference(target_url="file://intro.mov"),
        source_range=otio.opentime.TimeRange(
            start_time=otio.opentime.RationalTime(0, 24),
            duration=otio.opentime.RationalTime(24, 24),  # 1s
        ),
    )
    video.append(clip1)
    clip2 = otio.schema.Clip(
        name="Body",
        media_reference=otio.schema.ExternalReference(target_url="file://body.mov"),
        source_range=otio.opentime.TimeRange(
            start_time=otio.opentime.RationalTime(0, 24),
            duration=otio.opentime.RationalTime(48, 24),  # 2s
        ),
    )
    video.append(clip2)

    audio = otio.schema.Track(name="A1", kind=otio.schema.TrackKind.Audio)
    tl.tracks.append(audio)
    audio_clip = otio.schema.Clip(
        name="Music",
        media_reference=otio.schema.ExternalReference(target_url="file://music.wav"),
        source_range=otio.opentime.TimeRange(
            start_time=otio.opentime.RationalTime(0, 1000),
            duration=otio.opentime.RationalTime(3000, 1000),  # 3s
        ),
    )
    audio.append(audio_clip)

    # Marker on the second video clip at clip-time t=12 (= track-time 1.5s)
    clip2.markers.append(
        otio.schema.Marker(
            name="cue",
            marked_range=otio.opentime.TimeRange(
                start_time=otio.opentime.RationalTime(12, 24),
                duration=otio.opentime.RationalTime(0, 24),
            ),
            color=otio.schema.MarkerColor.RED,
        )
    )

    out = tmp_path / "demo.otio"
    otio.adapters.write_to_file(tl, str(out))
    return out


@pytest.fixture
def sample_otio_path(tmp_path) -> Path:
    return build_sample_otio(tmp_path)


def _make_store_for_dump() -> MemoryStore:
    s = MemoryStore()
    s.add_tier(Tier("V1"))
    s.add_tier(Tier("markers"))
    rate = 1000

    def _clip(
        start_ms: int, end_ms: int, name: str, asset: str = "file://demo.mov"
    ) -> Annotation:
        return Annotation(
            id=uuid4(),
            tier="V1",
            reference=MediaRef(
                asset_id=asset,
                interval=TimeInterval(
                    RationalTime(start_ms, rate), RationalTime(end_ms, rate)
                ),
            ),
            body={"name": name, "kind": "clip"},
            body_schema_uri="annot://schema/otio-clip/v1",
            provenance=Provenance(
                was_generated_by="user:test",
                was_attributed_to="thor",
                generated_at_time=RationalTime.zero(rate),
            ),
        )

    s.add(_clip(0, 1000, "Intro"))
    s.add(_clip(1000, 3000, "Body"))
    return s


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_registered(self):
        spec = get_adapter("otio")
        assert spec.name == "otio"
        assert ".otio" in spec.extensions

    def test_lookup_by_extension(self):
        assert find_adapter(extension=".otio") is not None

    def test_two_body_schema_uris(self):
        spec = get_adapter("otio")
        assert "annot://schema/otio-clip/v1" in spec.body_schema_uris
        assert "annot://schema/otio-marker/v1" in spec.body_schema_uris


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------


class TestLoad:
    def test_load_from_path(self, sample_otio_path):
        store = adapter_module.load(sample_otio_path, rate=1000)
        # 2 video clips + 1 audio clip + 1 marker = 4
        anns = list(store.all())
        assert len(anns) == 4

    def test_creates_track_tiers(self, sample_otio_path):
        store = adapter_module.load(sample_otio_path, rate=1000)
        names = {t.name for t in store.tiers()}
        assert "V1" in names
        assert "A1" in names
        assert "markers" in names

    def test_clip_intervals(self, sample_otio_path):
        store = adapter_module.load(sample_otio_path, rate=1000)
        v1 = sorted(
            store.by_tier("V1"),
            key=lambda a: a.interval.start.to_fraction(),
        )
        # Intro 0-1s, Body 1-3s
        assert v1[0].interval.start.value == 0
        assert v1[0].interval.end.value == 1000
        assert v1[1].interval.start.value == 1000
        assert v1[1].interval.end.value == 3000

    def test_clip_asset_id_from_media_ref(self, sample_otio_path):
        store = adapter_module.load(sample_otio_path, rate=1000)
        intro = next(a for a in store.by_tier("V1") if a.body.get("name") == "Intro")
        assert intro.reference.asset_id == "file://intro.mov"

    def test_marker_is_point_annotation(self, sample_otio_path):
        store = adapter_module.load(sample_otio_path, rate=1000)
        markers = list(store.by_tier("markers"))
        assert len(markers) == 1
        m = markers[0]
        assert m.interval.is_point
        # Marker is at clip-relative t=12/24 = 0.5s; clip starts at track-time 1s.
        # So track-time = 1.0 + 0.5 = 1.5s = 1500 ticks at rate 1000.
        assert m.interval.start.value == 1500

    def test_marker_color(self, sample_otio_path):
        store = adapter_module.load(sample_otio_path, rate=1000)
        m = next(store.by_tier("markers"))
        assert m.body["color"] == "RED"

    def test_provenance(self, sample_otio_path):
        store = adapter_module.load(sample_otio_path, rate=1000, attribution="thor")
        a = next(store.all())
        assert a.provenance.was_generated_by == "adapter:otio@1.1.0"
        assert a.provenance.was_attributed_to == "thor"
        assert a.provenance.activity == "import"

    def test_load_from_bytes(self, sample_otio_path):
        blob = sample_otio_path.read_bytes()
        store = adapter_module.load(blob, rate=1000)
        assert len(list(store.all())) == 4

    def test_asset_id_override(self, sample_otio_path):
        store = adapter_module.load(sample_otio_path, rate=1000, asset_id="blake3:hash")
        v1 = next(a for a in store.by_tier("V1"))
        assert v1.reference.asset_id == "blake3:hash"


# ---------------------------------------------------------------------------
# dump
# ---------------------------------------------------------------------------


class TestDump:
    def test_dump_returns_bytes(self):
        store = _make_store_for_dump()
        blob = adapter_module.dump(store)
        assert isinstance(blob, bytes)
        assert b"OTIO_SCHEMA" in blob
        assert b"Intro" in blob
        assert b"Body" in blob

    def test_dump_to_path(self, tmp_path):
        store = _make_store_for_dump()
        out = tmp_path / "out.otio"
        result = adapter_module.dump(store, out)
        assert result is None
        assert out.exists()

    def test_dump_emits_valid_otio(self, tmp_path):
        store = _make_store_for_dump()
        out = tmp_path / "out.otio"
        adapter_module.dump(store, out)
        # Re-parse with native otio
        tl = otio.adapters.read_from_file(str(out))
        assert tl.name == "lacing"
        v1 = next(t for t in tl.tracks if t.name == "V1")
        clip_names = [c.name for c in v1.find_clips()]
        assert "Intro" in clip_names
        assert "Body" in clip_names


# ---------------------------------------------------------------------------
# round trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_roundtrip_clip_intervals(self, tmp_path):
        original = _make_store_for_dump()
        path = tmp_path / "rt.otio"
        adapter_module.dump(original, path)

        loaded = adapter_module.load(path, rate=1000)
        # Clips on V1 round-trip; markers tier is empty in our dump (no markers in source).
        v1_loaded = sorted(
            (a.body["name"], a.interval.start.value, a.interval.end.value)
            for a in loaded.by_tier("V1")
        )
        v1_orig = sorted(
            (a.body["name"], a.interval.start.value, a.interval.end.value)
            for a in original.by_tier("V1")
        )
        assert v1_loaded == v1_orig


# ---------------------------------------------------------------------------
# top-level dispatch
# ---------------------------------------------------------------------------


class TestDispatch:
    def test_load_via_top_level(self, sample_otio_path):
        from lacing.adapters import load as top_load

        store = top_load(sample_otio_path, rate=1000)
        assert len(list(store.all())) == 4

    def test_dump_via_top_level(self, tmp_path):
        from lacing.adapters import dump as top_dump

        out = tmp_path / "out.otio"
        top_dump(_make_store_for_dump(), out, format="otio")
        assert out.exists()


@pytest.mark.parametrize("end", [0, 1000])  # a marker (point) and a clip
def test_a_body_without_a_name_dumps(end):
    """lacing#132: name=None made OTIO's constructors raise TypeError."""
    from uuid import uuid4

    from lacing import Annotation, MediaRef, Provenance, RationalTime, TimeInterval
    from lacing.store import MemoryStore
    from lacing.tier import Tier

    store = MemoryStore()
    store.add_tier(Tier("t"))
    store.add(
        Annotation(
            id=uuid4(),
            tier="t",
            reference=MediaRef(
                asset_id="a",
                interval=TimeInterval(RationalTime(0, 1000), RationalTime(end, 1000)),
            ),
            body={"text": "x"},
            body_schema_uri="annot://schema/x/v1",
            provenance=Provenance(
                was_generated_by="user:t",
                was_attributed_to="t",
                generated_at_time=RationalTime.now(),
            ),
        )
    )
    [back] = list(adapter_module.load(adapter_module.dump(store)).all())
    assert back.tier == "t"
    assert (back.interval.start, back.interval.end) == (
        RationalTime(0, 1000),
        RationalTime(end, 1000),
    )


# ---------------------------------------------------------------------------
# exact time: no float seconds, no millisecond quantisation (lacing#134)
# ---------------------------------------------------------------------------


def _ann(tier: str, start: RationalTime, end: RationalTime, name: str) -> Annotation:
    return Annotation(
        id=uuid4(),
        tier=tier,
        reference=MediaRef(
            asset_id="file://demo.mov", interval=TimeInterval(start, end)
        ),
        body={"name": name, "kind": "marker" if start == end else "clip"},
        body_schema_uri=(
            "annot://schema/otio-marker/v1"
            if start == end
            else "annot://schema/otio-clip/v1"
        ),
        provenance=Provenance(
            was_generated_by="user:test",
            was_attributed_to="thor",
            generated_at_time=RationalTime.now(),
        ),
    )


def _store(tier: str, *spans: tuple[RationalTime, RationalTime]) -> MemoryStore:
    s = MemoryStore()
    s.add_tier(Tier(tier))
    for i, (start, end) in enumerate(spans):
        s.add(_ann(tier, start, end, f"a{i}"))
    return s


def _spans(store: MemoryStore, tier: str) -> list[tuple[RationalTime, RationalTime]]:
    return sorted(
        ((a.interval.start, a.interval.end) for a in store.by_tier(tier)),
        key=lambda se: (se[0].to_fraction(), se[1].to_fraction()),
    )


def _roundtrip(store: MemoryStore, *, rate: int) -> MemoryStore:
    return adapter_module.load(adapter_module.dump(store), rate=rate)


def _timeline_with(*items, name: str = "T") -> bytes:
    tl = otio.schema.Timeline(name="t")
    track = otio.schema.Track(name=name)
    for item in items:
        track.append(item)
    tl.tracks.append(track)
    return otio.adapters.write_to_string(tl, adapter_name="otio_json").encode()


def _otio_clip(start, duration, name: str = "c"):
    return otio.schema.Clip(
        name=name,
        media_reference=otio.schema.ExternalReference(target_url="file://x"),
        source_range=otio.opentime.TimeRange(start_time=start, duration=duration),
    )


class TestExactTime:
    def test_roundtrip_at_48k(self):
        rt = lambda v: RationalTime(v, 48000)  # noqa: E731
        # Sample-exact bounds: 1 sample and 47_999 samples are not whole ms.
        spans = [(rt(1), rt(47_999)), (rt(47_999), rt(96_001))]
        back = _roundtrip(_store("A", *spans), rate=48000)
        assert _spans(back, "A") == spans
        assert all(s.rate == 48000 and e.rate == 48000 for s, e in _spans(back, "A"))

    def test_dump_keeps_lacing_integers_not_milliseconds(self):
        store = _store("A", (RationalTime(1, 48000), RationalTime(48_000, 48000)))
        tl = otio.adapters.read_from_string(
            adapter_module.dump(store).decode(), adapter_name="otio_json"
        )
        [gap, clip] = list(tl.tracks[0])
        assert (gap.source_range.duration.value, gap.source_range.duration.rate) == (
            1,
            48000,
        )
        dur = clip.source_range.duration
        assert (dur.value, dur.rate) == (47_999, 48000)

    def test_roundtrip_ntsc(self):
        # 29.97 fps as lacing writes it: rate 30000, one frame = 1001 ticks.
        frame = 1001
        rt = lambda f: RationalTime(f * frame, 30000)  # noqa: E731
        spans = [(rt(0), rt(1)), (rt(1), rt(30)), (rt(30), rt(10_789))]
        back = _roundtrip(_store("V", *spans), rate=30000)
        assert _spans(back, "V") == spans
        assert [s.value for s, _ in _spans(back, "V")] == [0, 1001, 30_030]

    def test_gaps_at_a_non_ms_rate(self):
        rt = lambda v: RationalTime(v, 48000)  # noqa: E731
        spans = [(rt(7), rt(11)), (rt(13), rt(17)), (rt(48_001), rt(48_003))]
        store = _store("A", *spans)
        tl = otio.adapters.read_from_string(
            adapter_module.dump(store).decode(), adapter_name="otio_json"
        )
        kinds = [
            (item.schema_name(), item.source_range.duration.value)
            for item in tl.tracks[0]
        ]
        assert kinds == [
            ("Gap", 7),
            ("Clip", 4),
            ("Gap", 2),
            ("Clip", 4),
            ("Gap", 47_984),
            ("Clip", 2),
        ]
        assert _spans(_roundtrip(store, rate=48000), "A") == spans

    def test_gap_between_clips_at_different_rates(self):
        # Gap from 1/30000 * 1001 s to 1/48000 * 48_049 s: exact only at their LCM.
        spans = [
            (RationalTime(0, 30000), RationalTime(1001, 30000)),
            (RationalTime(48_049, 48000), RationalTime(96_000, 48000)),
        ]
        back = _roundtrip(_store("A", *spans), rate=240_000)
        assert _spans(back, "A") == spans

    def test_markers_at_a_non_ms_rate(self):
        points = [RationalTime(1, 48000), RationalTime(10_011, 30000)]
        store = _store("M", *((t, t) for t in points))
        tl = otio.adapters.read_from_string(
            adapter_module.dump(store).decode(), adapter_name="otio_json"
        )
        assert sorted(
            (m.marked_range.start_time.value, m.marked_range.start_time.rate)
            for m in tl.tracks[0].markers
        ) == [(1, 48000), (10_011, 30000)]
        back = _roundtrip(store, rate=240_000)
        assert [s for s, _ in _spans(back, "M")] == points

    def test_load_keeps_exact_values_at_24_and_1000(self):
        blob = _timeline_with(
            _otio_clip(
                otio.opentime.RationalTime(0, 24), otio.opentime.RationalTime(25, 24)
            ),
            _otio_clip(
                otio.opentime.RationalTime(0, 1000),
                otio.opentime.RationalTime(1001, 1000),
            ),
        )
        # 25/24 s then 1001/1000 s: exact at rate 24000, not on a ms grid.
        spans = _spans(adapter_module.load(blob, rate=24000), "T")
        assert spans == [
            (RationalTime(0, 24000), RationalTime(25_000, 24000)),
            (RationalTime(25_000, 24000), RationalTime(49_024, 24000)),
        ]

    def test_one_third_second_survives_exactly(self):
        """A float-seconds path cannot hold 1/3 s; this one must, both ways."""
        third = RationalTime(1, 3)
        spans = [(third, RationalTime(2, 3)), (RationalTime(2, 3), RationalTime(4, 3))]
        store = _store("A", *spans, (third, third))
        back = _roundtrip(store, rate=3)
        assert _spans(back, "A") == [(third, third), *spans]

    def test_load_recovers_rationals_written_as_doubles(self):
        # Third-party OTIO: rate 24000/1001 stored as the double 23.976...,
        # and a value of 1/3 stored as 0.333...
        ntsc = 24000 / 1001
        blob = _timeline_with(
            _otio_clip(
                otio.opentime.RationalTime(0, ntsc),
                otio.opentime.RationalTime(24, ntsc),  # 24 frames = 1.001 s
            ),
            _otio_clip(
                otio.opentime.RationalTime(0, 1), otio.opentime.RationalTime(1 / 3, 1)
            ),
        )
        spans = _spans(adapter_module.load(blob, rate=72000), "T")
        assert spans == [
            (RationalTime(0, 72000), RationalTime(72_072, 72000)),
            (RationalTime(72_072, 72000), RationalTime(96_072, 72000)),
        ]

    def test_load_raises_rather_than_rounds(self):
        from lacing.time import LossyTimeConversionError

        blob = _timeline_with(
            _otio_clip(
                otio.opentime.RationalTime(0, 48000),
                otio.opentime.RationalTime(1, 48000),
            )
        )
        with pytest.raises(LossyTimeConversionError, match="multiple of 48000"):
            adapter_module.load(blob, rate=1000)

    @pytest.mark.parametrize(
        "seconds, rate",
        [
            (Fraction(12345, 48000), 48000),  # odd samples, written as seconds
            (Fraction(1, 10000), 240000),
            (Fraction(1001, 30000), 240000),  # one NTSC frame, as seconds
        ],
    )
    def test_times_written_as_seconds_at_rate_1_load_exactly(self, seconds, rate):
        """OTIO's own from_seconds writes rate 1.0: the load rate is the hint
        that recovers the time the writer meant (review of lacing#134)."""
        blob = _timeline_with(
            _otio_clip(
                otio.opentime.RationalTime(0, 1),
                otio.opentime.RationalTime(float(seconds), 1),
            )
        )
        [clip] = adapter_module.load(blob, rate=rate).all()
        assert clip.interval.end.to_fraction() == seconds

    def test_dump_refuses_integers_doubles_cannot_hold(self):
        from lacing.time import LossyTimeConversionError

        big = 2**53 + 1
        store = _store("A", (RationalTime(0, 1), RationalTime(big, 1)))
        with pytest.raises(LossyTimeConversionError):
            adapter_module.dump(store)
