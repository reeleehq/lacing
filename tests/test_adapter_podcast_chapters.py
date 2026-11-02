"""Tests for the Podcasting 2.0 podcast:chapters JSON adapter."""

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
from lacing.adapters import podcast_chapters as adapter_module  # registers
from lacing.adapters import webvtt, web_annotation  # noqa: F401  registers
from lacing.model import Annotation, MediaRef, Provenance
from lacing.store import MemoryStore
from lacing.time import LossyTimeConversionError, RationalTime, TimeInterval


# The spec's example files, docs/examples/chapters/example.json and
# exampleComplex.json (the latter's long image URL and value tag shortened).
BASIC_EXAMPLE = """{
  "version": "1.2.0",
  "chapters":
  [
    {"startTime": 0, "title": "Intro"},
    {"startTime": 168, "title": "Hearing Aids",
     "img": "https://example.com/images/hearing_aids.jpg"},
    {"startTime": 260, "title": "Progress Report"},
    {"startTime": 410, "title": "Namespace",
     "img": "https://example.com/images/namepsace_example.jpg",
     "url": "https://github.com/Podcastindex-org/podcast-namespace"},
    {"startTime": 3990, "title": "Just Break Up",
     "img": "https://example.com/images/justbreakuppod.png"},
    {"startTime": 4600, "title": "Donations", "url": "https://example.com/paypal_link"},
    {"startTime": 5510, "title": "The Big Players"},
    {"startTime": 5854, "title": "Spread the Word"},
    {"startTime": 6089, "title": "Outro"}
  ]
}"""

COMPLEX_EXAMPLE = """{
  "version": "1.2.0",
  "author": "John Doe",
  "title": "Episode 7 - Making Progress",
  "podcastName": "John's Awesome Podcast",
  "chapters":
  [
    {"startTime": 0, "title": "Intro"},
    {"startTime": 168, "title": "Hearing Aids"},
    {"startTime": 260, "title": "Progress Report"},
    {"startTime": 410, "title": "Namespace",
     "img": "https://example.com/images/namepsace_example.jpg",
     "url": "https://github.com/Podcastindex-org/podcast-namespace"},
    {"startTime": 3990, "title": "Just Break Up",
     "img": "https://example.com/images/justbreakuppod.png",
     "url": "https://twitter.com/justbreakuppod"},
    {"startTime": 4200, "title": "Played song by artist",
     "img": "https://i.discogs.com/x.jpeg",
     "url": "https://www.discogs.com/master/96559-Rick-Astley-Never-Gonna-Give-You-Up",
     "value": "<podcast:value type=\\"lightning\\" method=\\"keysend\\"/>"},
    {"startTime": 4600, "title": "Donations", "url": "https://example.com/paypal_link"},
    {"startTime": 4826, "img": "https://example.com/images/parisfrance.jpg",
     "toc": false,
     "location": {"name": "Eiffel Tower, Paris", "geo": "geo:42.3417649,-70.9661596"}},
    {"startTime": 5510, "title": "The Big Players"},
    {"startTime": 5854, "title": "Spread the Word"},
    {"startTime": 6089, "title": "Outro"}
  ]
}"""

CHAPTER_URI = "annot://schema/podcast-chapter/v1"
EPISODE_URI = "annot://schema/podcast-chapters-episode/v1"


def _doc(*chapters, **top):
    return json.dumps({"version": "1.2.0", **top, "chapters": list(chapters)})


def _chapters(store):
    return sorted(
        (a for a in store.all() if a.body_schema_uri == CHAPTER_URI),
        key=lambda a: a.interval.start.to_fraction(),
    )


def _episode(store):
    (a,) = [a for a in store.all() if a.body_schema_uri == EPISODE_URI]
    return a


def _view(store):
    """Comparable view of a store: everything but ids and provenance."""
    return sorted(
        (
            (
                a.tier,
                json.dumps(a.body, sort_keys=True),
                a.interval.start.to_fraction(),
                a.interval.end.to_fraction(),
                a.body_schema_uri,
            )
            for a in store.all()
        ),
    )


def _ann(start, end, body, *, tier="chapters", uri=CHAPTER_URI):
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


def _s(value):
    return RationalTime(value, 1)


# --- registry --------------------------------------------------------------


class TestRegistry:
    def test_registered(self):
        spec = get_adapter("podcast_chapters")
        assert spec.version == "1.0.0"
        assert spec.body_schema_uris == (CHAPTER_URI, EPISODE_URI)
        assert adapter_module.GENERATED_BY == "adapter:podcast_chapters@1.0.0"

    def test_lookup_by_spec_media_type(self):
        spec = find_adapter(media_type="application/json+chapters")
        assert spec.name == "podcast_chapters"

    def test_lookup_by_compound_extension(self):
        assert find_adapter(extension=".chapters.json").name == "podcast_chapters"
        assert find_adapter_for_path("a/b.c/ep.chapters.json").name == (
            "podcast_chapters"
        )

    def test_does_not_claim_application_json(self):
        assert "application/json" not in get_adapter("podcast_chapters").media_types
        assert find_adapter(media_type="application/json") is None
        assert find_adapter_for_path("x.json").name == "web_annotation"

    def test_registry_load_picks_it_from_the_path(self, tmp_path):
        path = tmp_path / "ep.chapters.json"
        path.write_text(BASIC_EXAMPLE, encoding="utf-8")
        assert len(_chapters(registry_load(path, rate=1000))) == 9


# --- load ------------------------------------------------------------------


class TestLoad:
    def test_basic_example(self):
        store = adapter_module.load(BASIC_EXAMPLE)
        chapters = _chapters(store)
        assert [c.body.get("title") for c in chapters] == [
            "Intro",
            "Hearing Aids",
            "Progress Report",
            "Namespace",
            "Just Break Up",
            "Donations",
            "The Big Players",
            "Spread the Word",
            "Outro",
        ]
        assert {c.tier for c in chapters} == {"chapters"}
        assert chapters[1].body["img"] == "https://example.com/images/hearing_aids.jpg"
        assert {t.name for t in store.tiers()} == {"chapters", "episode"}

    def test_missing_end_is_the_next_start_and_last_is_a_point(self):
        chapters = _chapters(adapter_module.load(BASIC_EXAMPLE))
        spans = [(c.interval.start.value, c.interval.end.value) for c in chapters]
        assert spans[0] == (0, 168000)
        assert spans[1] == (168000, 260000)
        assert spans[-1] == (6089000, 6089000)  # point
        assert all(c.body["end_inferred"] is True for c in chapters)

    def test_explicit_end_time_is_kept(self):
        chapters = _chapters(
            adapter_module.load(
                _doc(
                    {"startTime": 0, "endTime": 100.5, "title": "a"},
                    {"startTime": 168, "title": "b"},
                )
            )
        )
        assert chapters[0].interval.end == RationalTime(100500, 1000)
        assert "end_inferred" not in chapters[0].body

    def test_unsorted_and_shared_starts(self):
        chapters = _chapters(
            adapter_module.load(
                _doc(
                    {"startTime": 10, "title": "late"},
                    {"startTime": 0, "title": "a"},
                    {"startTime": 0, "title": "b"},
                )
            )
        )
        ends = {c.body["title"]: c.interval.end.value for c in chapters}
        assert ends == {"a": 10000, "b": 10000, "late": 10000}

    def test_optional_fields_kept_verbatim(self):
        chapters = _chapters(adapter_module.load(COMPLEX_EXAMPLE))
        paris = next(c for c in chapters if c.interval.start.value == 4826000)
        assert paris.body == {
            "img": "https://example.com/images/parisfrance.jpg",
            "toc": False,
            "location": {
                "name": "Eiffel Tower, Paris",
                "geo": "geo:42.3417649,-70.9661596",
            },
            "end_inferred": True,
        }
        song = next(c for c in chapters if c.interval.start.value == 4200000)
        assert song.body["value"].startswith("<podcast:value")  # unnamed field

    def test_top_level_fields_on_one_episode_annotation(self):
        store = adapter_module.load(COMPLEX_EXAMPLE)
        ep = _episode(store)
        assert ep.tier == "episode"
        assert ep.interval.start == ep.interval.end == RationalTime(0, 1000)
        assert ep.body == {
            "version": "1.2.0",
            "fields": {
                "author": "John Doe",
                "title": "Episode 7 - Making Progress",
                "podcastName": "John's Awesome Podcast",
            },
        }

    def test_exact_times(self):
        (c,) = _chapters(
            adapter_module.load(_doc({"startTime": 1.001, "endTime": 2.333}))
        )
        assert c.interval.start == RationalTime(1001, 1000)
        assert c.interval.end.value == 2333
        (c,) = _chapters(adapter_module.load(_doc({"startTime": 0.333}), rate=1000))
        assert c.interval.start == RationalTime(333, 1000)

    def test_lossy_time_raises_naming_the_chapter(self):
        with pytest.raises(LossyTimeConversionError, match=r"chapters\[1\]\.endTime"):
            adapter_module.load(
                _doc({"startTime": 0}, {"startTime": 1, "endTime": 1.0001})
            )

    def test_non_time_numbers_are_plain_json(self):
        (c,) = _chapters(adapter_module.load(_doc({"startTime": 0, "weight": 0.5})))
        assert c.body["weight"] == 0.5 and isinstance(c.body["weight"], float)

    def test_provenance(self):
        store = adapter_module.load(COMPLEX_EXAMPLE, attribution="user:bob")
        for a in store.all():
            assert a.provenance.was_generated_by == "adapter:podcast_chapters@1.0.0"
            assert a.provenance.was_attributed_to == "user:bob"
            assert a.provenance.activity == "import"
            assert a.provenance.generated_at_is_known

    def test_custom_tiers(self):
        store = adapter_module.load(BASIC_EXAMPLE, tier="toc", episode_tier="meta")
        assert {a.tier for a in store.all()} == {"toc", "meta"}


class TestMalformed:
    @pytest.mark.parametrize(
        ("doc", "match"),
        [
            ("[]", "JSON object"),
            ("{", "not valid JSON"),
            ('{"version": "1.2.0"}', "chapters must be a list"),
            ('{"version": 1.2, "chapters": []}', "version must be a string"),
            (_doc(3), r"chapters\[0\]: a chapter must be an object"),
            (_doc({"title": "x"}), r"chapters\[0\]: missing startTime"),
            (_doc({"startTime": 0}, {"startTime": "1"}), r"chapters\[1\]\.startTime"),
            (_doc({"startTime": -0.5}), r"chapters\[0\]\.startTime: negative"),
            (
                _doc({"startTime": 0}, {"startTime": 5, "endTime": 4}),
                r"chapters\[1\]: endTime 4 is before startTime",
            ),
            (_doc({"startTime": 0, "title": 7}), r"chapters\[0\]: title"),
            (_doc({"startTime": 0, "img": None}), r"chapters\[0\]: img"),
            (_doc({"startTime": 0, "url": []}), r"chapters\[0\]: url"),
            (_doc({"startTime": 0, "toc": "false"}), r"chapters\[0\]: toc"),
            (_doc({"startTime": 0, "location": "Paris"}), r"chapters\[0\]: location"),
            (_doc({"startTime": 0, "end_inferred": 1}), r"chapters\[0\]: the field"),
        ],
    )
    def test_raises_value_error(self, doc, match):
        with pytest.raises(ValueError, match=match):
            adapter_module.load(doc)


# --- dump ------------------------------------------------------------------


class TestDump:
    @pytest.mark.parametrize("example", [BASIC_EXAMPLE, COMPLEX_EXAMPLE])
    def test_spec_examples_round_trip(self, example):
        store1 = adapter_module.load(example)
        blob = adapter_module.dump(store1)
        assert json.loads(blob) == json.loads(example)
        assert _view(adapter_module.load(blob)) == _view(store1)

    def test_key_order(self):
        doc = json.loads(adapter_module.dump(adapter_module.load(COMPLEX_EXAMPLE)))
        assert list(doc) == ["version", "author", "title", "podcastName", "chapters"]
        assert list(doc["chapters"][3]) == ["startTime", "title", "img", "url"]

    def test_explicit_and_missing_end_times_round_trip(self):
        doc = _doc(
            {"startTime": 0, "endTime": 100.25, "title": "a"},
            {"startTime": 168, "title": "b"},
            {"startTime": 200, "endTime": 260, "title": "c"},
            {"startTime": 260, "title": "d"},
        )
        assert json.loads(adapter_module.dump(adapter_module.load(doc))) == json.loads(
            doc
        )

    def test_edited_inferred_end_is_written(self):
        store = adapter_module.load(_doc({"startTime": 0}, {"startTime": 10}))
        first = _chapters(store)[0]
        ref = MediaRef(asset_id="a", interval=TimeInterval(first.interval.start, _s(4)))
        store.update(first.model_copy(update={"reference": ref}))
        chapters = json.loads(adapter_module.dump(store))["chapters"]
        assert chapters == [{"startTime": 0, "endTime": 4}, {"startTime": 10}]

    def test_exact_decimal_and_ms_rounding(self):
        store = MemoryStore()
        store.add(_ann(RationalTime(1001, 1000), RationalTime(1001, 1000), {}))
        store.add(_ann(RationalTime(4, 3), RationalTime(5, 3), {"title": "third"}))
        chapters = json.loads(adapter_module.dump(store), parse_float=str)["chapters"]
        assert chapters == [
            {"startTime": "1.001", "endTime": "1.001"},
            {"startTime": "1.333", "endTime": "1.666", "title": "third"},
        ]

    def test_a_store_without_episode_writes_the_default_version(self):
        store = MemoryStore()
        store.add(_ann(_s(0), _s(5), {"title": "only"}))
        doc = json.loads(adapter_module.dump(store))
        assert doc == {
            "version": "1.2.0",
            "chapters": [{"startTime": 0, "endTime": 5, "title": "only"}],
        }

    def test_two_episode_annotations_raise(self):
        store = MemoryStore()
        for _ in range(2):
            store.add(
                _ann(_s(0), _s(0), {"version": "1.2.0", "fields": {}}, uri=EPISODE_URI)
            )
        with pytest.raises(ValueError, match="2 episode annotations"):
            adapter_module.dump(store)

    def test_negative_time_raises(self):
        store = MemoryStore()
        store.add(_ann(RationalTime(-1, 1000), _s(1), {}))
        with pytest.raises(ValueError, match="negative"):
            adapter_module.dump(store)

    def test_without_tier_only_chapter_bodies_are_written(self):
        store = adapter_module.load(BASIC_EXAMPLE)
        store.add(
            _ann(
                _s(1),
                _s(2),
                {"text": "a cue"},
                tier="cues",
                uri="annot://schema/srt-cue/v1",
            )
        )
        assert len(json.loads(adapter_module.dump(store))["chapters"]) == 9

    def test_tier_takes_titles_from_another_format(self):
        vtt = "WEBVTT\n\n00:00.000 --> 01:00.000\nOpening\n\n01:00.000 --> 02:30.500\nMain\n"
        store = webvtt.load(vtt, rate=1000)
        chapters = json.loads(adapter_module.dump(store, tier="cues"))["chapters"]
        assert chapters == [
            {"startTime": 0, "endTime": 60, "title": "Opening"},
            {"startTime": 60, "endTime": 150.5, "title": "Main"},
        ]

    def test_write_to_path(self, tmp_path):
        out = tmp_path / "out.chapters.json"
        assert adapter_module.dump(adapter_module.load(COMPLEX_EXAMPLE), out) is None
        assert json.loads(out.read_text()) == json.loads(COMPLEX_EXAMPLE)
