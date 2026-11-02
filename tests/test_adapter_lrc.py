"""Tests for the LRC lyrics adapter (plain and enhanced LRC)."""

from __future__ import annotations

import time
from uuid import uuid4

import pytest

from lacing.adapters import find_adapter, get_adapter
from lacing.adapters import lrc as adapter_module  # noqa: F401  registers
from lacing.adapters import srt
from lacing.model import Annotation, MediaRef, Provenance
from lacing.store import MemoryStore
from lacing.tier import TierStereotype, validate_tier_constraint
from lacing.time import LossyTimeConversionError, RationalTime, TimeInterval


PLAIN_LRC = """[ar:Some Artist]
[ti:Some Title]
[al:Some Album]
[by:someone]
[00:12.00]I came down to the river
[00:15.30]to watch the water flow
[00:18.75]
[00:20.00]and the night came on
"""

ENHANCED_LRC = """[ti:Word by word]
[length: 0:30]
[00:01.00]<00:01.00>Word <00:01.40>by <00:01.80>word<00:02.50>
[00:03.00]Oh <00:03.50>yeah
[00:05.00]plain line
"""

LINE = "annot://schema/lyric-line/v1"
WORD = "annot://schema/word/v1"
TAGS = "annot://schema/lrc-tags/v1"


def _tier(store, name):
    return sorted(
        (a for a in store.all() if a.tier == name),
        key=lambda a: (a.interval.start.to_fraction(), a.interval.end.to_fraction()),
    )


def _spans(store, tier="lines"):
    """``(text, start_ms, end_ms)`` per annotation of ``tier`` (rate 1000)."""
    return [
        (a.body["text"], a.interval.start.value, a.interval.end.value)
        for a in _tier(store, tier)
    ]


def _view(store):
    """Comparable view of a store: everything but ids and provenance."""
    return sorted(
        (a.tier, a.interval.start, a.interval.end, a.body_schema_uri, repr(a.body))
        for a in store.all()
    )


def _included_in_violations(store):
    """Violations of the words tier's INCLUDED_IN constraint on the lines tier."""
    lines, words = store.get_tier("lines"), store.get_tier("words")
    return validate_tier_constraint(
        lines,
        words,
        [a.interval for a in _tier(store, "lines")],
        [a.interval for a in _tier(store, "words")],
    )


def _tags(store):
    (ann,) = _tier(store, "tags")
    return [(t["key"], t["value"]) for t in ann.body["tags"]]


def _ann(start_ms: int, end_ms: int, text: str, *, tier="lines", rate=1000):
    return Annotation(
        id=uuid4(),
        tier=tier,
        reference=MediaRef(
            asset_id="lrc:sample",
            interval=TimeInterval(
                RationalTime(start_ms, rate), RationalTime(end_ms, rate)
            ),
        ),
        body={"text": text},
        body_schema_uri=LINE,
        provenance=Provenance(
            was_generated_by="user:test",
            was_attributed_to="test",
            generated_at_time=RationalTime.zero(1000),
        ),
    )


# --- registry --------------------------------------------------------------


class TestRegistry:
    def test_registered(self):
        spec = get_adapter("lrc")
        assert spec.version == "1.0.0"
        assert spec.body_schema_uris == (LINE, WORD, TAGS)

    def test_lookup_by_extension(self):
        assert find_adapter(extension=".lrc").name == "lrc"
        assert find_adapter(extension="LRC").name == "lrc"

    def test_lookup_by_media_type(self):
        assert find_adapter(media_type="application/x-lrc").name == "lrc"

    def test_generated_by(self):
        assert adapter_module.GENERATED_BY == "adapter:lrc@1.0.0"

    def test_generic_loader_dispatches_on_extension(self, tmp_path):
        from lacing.adapters import load

        path = tmp_path / "song.lrc"
        path.write_text(PLAIN_LRC, encoding="utf-8")
        assert len(_tier(load(str(path)), "lines")) == 4


# --- load: plain -----------------------------------------------------------


class TestLoadPlain:
    def test_lines_end_at_the_next_start_and_the_last_is_a_point(self):
        assert _spans(adapter_module.load(PLAIN_LRC)) == [
            ("I came down to the river", 12000, 15300),
            ("to watch the water flow", 15300, 18750),
            ("", 18750, 20000),  # an empty tag clears the display
            ("and the night came on", 20000, 20000),
        ]

    def test_tiers_and_schemas(self):
        store = adapter_module.load(PLAIN_LRC)
        assert {t.name for t in store.tiers()} == {"lines", "tags"}
        assert store.get_tier("lines").stereotype == TierStereotype.NONE
        assert {a.body_schema_uri for a in _tier(store, "lines")} == {LINE}
        assert all(set(a.body) == {"text"} for a in _tier(store, "lines"))

    def test_id_tags_are_kept_verbatim_in_file_order(self):
        store = adapter_module.load(
            PLAIN_LRC + "[length: 3:20]\n[x-custom:Some: value]\n"
        )
        assert _tags(store) == [
            ("ar", "Some Artist"),
            ("ti", "Some Title"),
            ("al", "Some Album"),
            ("by", "someone"),
            ("length", " 3:20"),
            ("x-custom", "Some: value"),
        ]
        (ann,) = _tier(store, "tags")
        assert ann.interval.is_point and ann.interval.start.value == 0
        assert ann.body_schema_uri == TAGS

    def test_no_tags_no_tags_tier(self):
        store = adapter_module.load("[00:01.00]hi\n")
        assert {t.name for t in store.tiers()} == {"lines"}

    def test_repeated_time_tags(self):
        store = adapter_module.load(
            "[00:12.00][00:45.00]chorus\n[00:20.00]verse\n[00:50.00]outro\n"
        )
        assert _spans(store) == [
            ("chorus", 12000, 20000),
            ("verse", 20000, 45000),
            ("chorus", 45000, 50000),
            ("outro", 50000, 50000),
        ]

    def test_lines_sharing_a_start_all_end_at_the_next_later_start(self):
        store = adapter_module.load("[00:01.00]Hello\n[00:01.00]Bonjour\n[00:03.00]x\n")
        assert _spans(store) == [
            ("Hello", 1000, 3000),
            ("Bonjour", 1000, 3000),
            ("x", 3000, 3000),
        ]

    def test_text_after_the_time_tags_keeps_brackets(self):
        (ann, _) = _tier(
            adapter_module.load("[00:01.00][Chorus] la\n[00:02.00]b\n"), "lines"
        )
        assert ann.body["text"] == "[Chorus] la"

    def test_length_ends_the_last_line(self):
        store = adapter_module.load("[length: 1:05.5]\n[00:01.00]a\n[00:59.00]b\n")
        assert _spans(store)[-1] == ("b", 59000, 65500)

    def test_length_with_no_fraction(self):
        store = adapter_module.load("[length:03:20]\n[00:01.00]a\n")
        assert _spans(store) == [("a", 1000, 200000)]

    def test_empty_input(self):
        assert list(adapter_module.load(b"").all()) == []
        assert list(adapter_module.load("\n\n").all()) == []

    def test_from_bytes_with_bom_crlf_and_path(self, tmp_path):
        expected = _view(adapter_module.load(PLAIN_LRC))
        blob = PLAIN_LRC.replace("\n", "\r\n").encode("utf-8-sig")
        assert _view(adapter_module.load(blob)) == expected
        path = tmp_path / "x.lrc"
        path.write_bytes(blob)
        assert _view(adapter_module.load(path)) == expected
        assert _view(adapter_module.load(str(path))) == expected

    def test_custom_tiers_and_asset(self):
        store = adapter_module.load(
            ENHANCED_LRC, tier="L", words_tier="W", tags_tier="T", asset_id="song"
        )
        assert {t.name for t in store.tiers()} == {"L", "W", "T"}
        assert store.get_tier("W").parent == "L"
        assert {a.reference.asset_id for a in store.all()} == {"song"}


# --- load: times -----------------------------------------------------------


class TestTimes:
    @pytest.mark.parametrize(
        "tag, ms",
        [
            ("00:12.34", 12340),  # centiseconds
            ("00:12.345", 12345),  # milliseconds
            ("00:12:34", 12340),  # ':' before the fraction
            ("00:12:345", 12345),
            ("00:12.5", 12500),  # one digit: tenths
            ("00:12", 12000),  # whole seconds
            ("123:04.00", 7384000),  # minutes past 99
            ("1:02.03", 62030),
        ],
    )
    def test_centiseconds_and_milliseconds(self, tag, ms):
        (ann,) = adapter_module.load(f"[{tag}]x\n").all()
        assert ann.interval.start == RationalTime(ms, 1000)
        assert ann.interval.start.value == ms

    def test_exact_times_at_another_rate(self):
        (ann,) = adapter_module.load("[00:01.001]x\n", rate=48000).all()
        assert ann.interval.start == RationalTime(48048, 48000)
        assert ann.interval.start.rate == 48000

    def test_rate_that_cannot_hold_a_millisecond_raises(self):
        with pytest.raises(LossyTimeConversionError):
            adapter_module.load("[00:01.001]x\n", rate=24)

    def test_positive_offset_makes_lyrics_sooner(self):
        store = adapter_module.load("[offset:+250]\n[00:12.00]a\n[00:13.00]b\n")
        assert _spans(store) == [("a", 11750, 12750), ("b", 12750, 12750)]

    def test_negative_offset_makes_lyrics_later(self):
        store = adapter_module.load("[00:12.00]a\n[offset:-250]\n[00:13.00]b\n")
        assert _spans(store) == [("a", 12250, 13250), ("b", 13250, 13250)]

    def test_offset_without_sign_is_positive(self):
        store = adapter_module.load("[offset:5]\n[00:12.00]a\n")
        assert _spans(store) == [("a", 11995, 11995)]

    def test_offset_shifts_word_stamps_but_not_length(self):
        store = adapter_module.load(
            "[offset:-1000]\n[length:0:10]\n[00:01.00]<00:01.00>a <00:01.50>b\n"
        )
        assert _spans(store) == [("a b", 2000, 10000)]
        assert _spans(store, "words") == [("a", 2000, 2500), ("b", 2500, 10000)]

    def test_offset_that_makes_a_time_negative_clamps_to_zero(self):
        # a common file: "+" offset and an "Artist - Title" line at 0 (ffmpeg's
        # lrcdec lets the negative time through; lacing clamps it, inexactly)
        src = "[offset:+500]\n[00:00.00]Artist - Title\n[00:05.00]a\n"
        store = adapter_module.load(src)
        assert _spans(store) == [("Artist - Title", 0, 4500), ("a", 4500, 4500)]
        assert adapter_module.dump(store).decode() == (
            "[offset:+500]\n[00:00.50]Artist - Title\n[00:05.00]a\n"
        )

    def test_clamped_word_stamps_keep_their_order(self):
        store = adapter_module.load(
            "[offset:+2000]\n[00:01.00]<00:01.00>a <00:03.00>b\n"
        )
        assert _spans(store, "words") == [("a", 0, 1000), ("b", 1000, 1000)]

    def test_an_empty_offset_is_zero(self):
        store = adapter_module.load("[ar:]\n[ti:]\n[offset:]\n[00:01.00]a\n")
        assert _spans(store) == [("a", 1000, 1000)]
        assert _tags(store) == [("ar", ""), ("ti", ""), ("offset", "")]

    def test_comma_before_the_fraction(self):
        store = adapter_module.load("[00:01,50]<00:01,50>a <00:02,25>b\n")
        assert _spans(store) == [("a b", 1500, 2250)]
        assert _spans(store, "words") == [("a", 1500, 2250), ("b", 2250, 2250)]


# --- load: enhanced --------------------------------------------------------


class TestLoadEnhanced:
    def test_words(self):
        store = adapter_module.load(ENHANCED_LRC)
        assert _spans(store) == [
            ("Word by word", 1000, 3000),
            ("Oh yeah", 3000, 5000),
            ("plain line", 5000, 30000),
        ]
        assert _spans(store, "words") == [
            ("Word", 1000, 1400),
            ("by", 1400, 1800),
            ("word", 1800, 2500),  # the trailing stamp ends it
            ("Oh", 3000, 3500),  # text before the first stamp: at the line time
            ("yeah", 3500, 5000),  # the last word ends with its line
        ]

    def test_words_tier(self):
        store = adapter_module.load(ENHANCED_LRC)
        tier = store.get_tier("words")
        assert tier.stereotype == TierStereotype.INCLUDED_IN
        assert tier.parent == "lines"
        assert {a.body_schema_uri for a in _tier(store, "words")} == {WORD}
        assert all(set(a.body) == {"text"} for a in _tier(store, "words"))

    def test_plain_file_has_no_words_tier(self):
        assert adapter_module.load(PLAIN_LRC).get_tier("words") is None

    def test_a_blank_segment_between_stamps_is_a_gap(self):
        store = adapter_module.load("[00:01.00]<00:01.00>a<00:01.20> <00:01.50>b\n")
        assert _spans(store, "words") == [("a", 1000, 1200), ("b", 1500, 1500)]

    def test_words_of_a_last_point_line_end_at_their_start(self):
        store = adapter_module.load("[00:01.00]<00:01.00>a <00:01.50>b\n")
        assert _spans(store, "words") == [("a", 1000, 1500), ("b", 1500, 1500)]

    def test_repeated_tags_read_words_once_against_the_matching_tag(self):
        store = adapter_module.load(
            "[00:01.00][00:10.00]<00:10.00>la <00:10.50>la\n[00:05.00]x\n[00:12.00]y\n"
        )
        assert _spans(store, "words") == [("la", 10000, 10500), ("la", 10500, 12000)]

    def test_angle_brackets_that_are_not_stamps_are_text(self):
        (ann,) = adapter_module.load("[00:01.00]I <3 you <b>\n").all()
        assert ann.body["text"] == "I <3 you <b>"


# --- load: lenient input and karaoke ------------------------------------


class TestLenient:
    def test_a_bracket_that_is_not_a_clock_starts_the_text(self):
        store = adapter_module.load("[00:01.00][2x] la\n[00:02.00][00:7x]y\n")
        assert [t for t, _, _ in _spans(store)] == ["[2x] la", "[00:7x]y"]

    def test_text_like_a_bracket_tag_round_trips(self):
        s = MemoryStore()
        s.add(_ann(1000, 2000, "[2x] la"))
        assert _spans(adapter_module.load(adapter_module.dump(s))) == [
            ("[2x] la", 1000, 1000)
        ]

    def test_several_id_tags_on_one_line(self):
        store = adapter_module.load("[ar:A][ti:T]\n[al:B] [by:C]\n[00:01.00]la\n")
        assert _tags(store) == [("ar", "A"), ("ti", "T"), ("al", "B"), ("by", "C")]

    @pytest.mark.parametrize("stray", ["some stray text", "[Chorus]", "Chorus [x]"])
    def test_untagged_lines_are_skipped(self, stray):
        store = adapter_module.load(f"[00:01.00]la\n{stray}\n[00:02.00]di\n")
        assert _spans(store) == [("la", 1000, 2000), ("di", 2000, 2000)]


class TestKaraoke:
    # the reviewer's input: "world" is sung past the next line's tag
    KARAOKE = (
        "[00:10.00]<00:10.50>Hello <00:11.00>world<00:12.50>\n"
        "[00:12.00]<00:12.60>next<00:13.00>\n"
    )

    def test_lines_widen_to_hold_their_words(self):
        store = adapter_module.load(self.KARAOKE)
        assert _spans(store) == [("Hello world", 10000, 12500), ("next", 12000, 13000)]
        assert _spans(store, "words") == [
            ("Hello", 10500, 11000),
            ("world", 11000, 12500),
            ("next", 12600, 13000),
        ]
        assert _included_in_violations(store) == []

    def test_round_trips(self):
        original = adapter_module.load(self.KARAOKE)
        once = adapter_module.dump(original)
        assert once.decode() == self.KARAOKE  # "world" is no longer dropped
        assert _view(adapter_module.load(once)) == _view(original)

    def test_a_word_stamped_before_its_line_starts_the_line(self):
        store = adapter_module.load("[00:13.00]<00:12.00>a <00:13.50>b\n[00:20.00]c\n")
        assert _spans(store) == [("a b", 12000, 20000), ("c", 20000, 20000)]
        assert _included_in_violations(store) == []
        assert _view(adapter_module.load(adapter_module.dump(store))) == _view(store)

    @pytest.mark.parametrize(
        "src",
        [
            "[00:01.00]<00:01.00>a <00:05.00>b\n[00:03.00]c\n",
            "[00:01.00]<00:01.00>a <00:01.50>b\n",
            "[length:0:01]\n[00:02.00]<00:02.00>a <00:02.50>b\n",
            "[00:01.00][00:10.00]<00:10.00>la <00:10.50>la\n[00:05.00]x\n[00:12.00]y\n",
        ],
    )
    def test_loaded_words_always_satisfy_included_in(self, src):
        store = adapter_module.load(src)
        assert _included_in_violations(store) == []
        assert _view(adapter_module.load(adapter_module.dump(store))) == _view(store)


# --- malformed input -------------------------------------------------------


class TestMalformed:
    @pytest.mark.parametrize(
        "line, message",
        [
            ("[00:61.00]x", r"malformed LRC time tag \[00:61\.00\]"),
            ("[00:1x.00]x", "malformed LRC time tag"),
            ("[00:12.0000]x", "malformed LRC time tag"),
            ("[-00:01.00]x", "malformed LRC time tag"),
            ("[00:01.00 x", "malformed LRC time tag .no closing bracket."),
            ("[ 00:01.00 ]x", "malformed LRC time tag"),
            ("[ar:Artist] trailing", "text after the ID tag"),
            ("[00:01.00]<00:9x.00>word", r"malformed LRC word stamp <00:9x\.00>"),
            ("[offset:fast]", r"malformed LRC \[offset:\] value 'fast'"),
            ("[offset:+1.5]", r"malformed LRC \[offset:\] value"),
            ("[length:long]", r"malformed LRC \[length:\] value"),
            ("[00:02.00]<00:02.00>a <00:01.00>b", "word stamps go backwards"),
        ],
    )
    def test_names_the_line(self, line, message):
        src = f"[ti:ok]\n\n{line}\n"
        with pytest.raises(ValueError, match=rf"^line 3: .*{message}"):
            adapter_module.load(src)

    def test_a_second_offset_tag(self):
        with pytest.raises(ValueError, match=r"^line 2: a second \[offset:\] tag"):
            adapter_module.load("[offset:1]\n[OFFSET:2]\n")

    def test_length_before_the_last_line_is_ignored(self):
        store = adapter_module.load("[length:0:01]\n[00:01.00]a\n[00:05.00]x\n")
        assert _spans(store) == [("a", 1000, 5000), ("x", 5000, 5000)]

    def test_an_empty_length_is_no_length(self):
        assert _spans(adapter_module.load("[length:]\n[00:01.00]a\n")) == [
            ("a", 1000, 1000)
        ]

    def test_full_width_digits_are_not_a_time(self):
        with pytest.raises(ValueError):
            adapter_module.load("[００:01.00]hi\n")


# --- provenance ------------------------------------------------------------


def test_provenance():
    store = adapter_module.load(ENHANCED_LRC, attribution="thor")
    anns = list(store.all())
    assert {a.tier for a in anns} == {"lines", "words", "tags"}
    for ann in anns:
        assert ann.provenance.was_generated_by == "adapter:lrc@1.0.0"
        assert ann.provenance.was_attributed_to == "thor"
        assert ann.provenance.activity == "import"
        assert ann.provenance.generated_at_is_known


# --- dump ------------------------------------------------------------------


class TestDump:
    def test_plain_file_is_reproduced(self):
        assert adapter_module.dump(adapter_module.load(PLAIN_LRC)).decode() == PLAIN_LRC

    def test_enhanced_file_is_a_fixed_point(self):
        once = adapter_module.dump(adapter_module.load(ENHANCED_LRC))
        assert once.decode() == (
            "[ti:Word by word]\n"
            "[length: 0:30]\n"
            "[00:01.00]<00:01.00>Word <00:01.40>by <00:01.80>word<00:02.50>\n"
            "[00:03.00]<00:03.00>Oh <00:03.50>yeah\n"
            "[00:05.00]plain line\n"
        )
        assert adapter_module.dump(adapter_module.load(once)) == once

    def test_lines_are_sorted(self):
        s = MemoryStore()
        for start, text in [(3000, "c"), (1000, "a"), (2000, "b")]:
            s.add(_ann(start, start + 500, text))
        assert adapter_module.dump(s) == b"[00:01.00]a\n[00:02.00]b\n[00:03.00]c\n"

    def test_centiseconds_truncate_and_keep_the_order(self):
        s = MemoryStore()
        s.add(_ann(1009, 1010, "a"))  # 1.009 s -> 00:01.00, not 00:01.01
        s.add(_ann(1, 3, "thirds", rate=3))  # 0.333.. s -> 00:00.33
        s.add(_ann(59999, 60000, "edge"))  # never rounded across a minute
        assert adapter_module.dump(s).decode() == (
            "[00:00.33]thirds\n[00:01.00]a\n[00:59.99]edge\n"
        )

    def test_milliseconds(self):
        s = MemoryStore()
        s.add(_ann(1001, 2000, "a"))
        s.add(_ann(1, 3, "thirds", rate=3))
        assert adapter_module.dump(s, precision="ms").decode() == (
            "[00:00.333]thirds\n[00:01.001]a\n"
        )

    def test_bad_precision(self):
        with pytest.raises(ValueError, match="precision"):
            adapter_module.dump(MemoryStore(), precision="s")

    def test_multi_line_text_is_joined(self):
        s = MemoryStore()
        s.add(_ann(0, 1000, "one\n\ntwo"))
        assert adapter_module.dump(s) == b"[00:00.00]one two\n"

    def test_offset_round_trips(self):
        src = "[offset:-250]\n[00:12.00]a\n[00:13.05]b\n"
        assert adapter_module.dump(adapter_module.load(src)).decode() == src

    def test_negative_time_raises(self):
        s = MemoryStore()
        s.add(_ann(-1, 5, "x", rate=3000))
        with pytest.raises(ValueError, match="negative"):
            adapter_module.dump(s)

    def test_words_from_another_source(self):
        s = MemoryStore()
        s.add(_ann(1000, 3000, "Hello, big world"))
        s.add(_ann(1000, 1500, "Hello", tier="words"))
        s.add(_ann(1500, 2000, "big", tier="words"))  # gap before "world"
        s.add(_ann(2200, 2800, "world", tier="words"))  # ends before its line
        s.add(_ann(9000, 9500, "stray", tier="words"))  # in no line: dropped
        assert adapter_module.dump(s).decode() == (
            "[00:01.00]<00:01.00>Hello, <00:01.50>big <00:02.00><00:02.20>world<00:02.80>\n"
        )
        back = adapter_module.load(adapter_module.dump(s))
        assert _spans(back, "words") == [
            ("Hello,", 1000, 1500),  # text between words joins the earlier one
            ("big", 1500, 2000),
            ("world", 2200, 2800),
        ]

    def test_words_not_in_the_text_are_dropped_and_the_text_kept(self):
        s = MemoryStore()
        s.add(_ann(1000, 3000, "something else"))
        s.add(_ann(1000, 2000, "la", tier="words"))
        s.add(_ann(2000, 3000, "la", tier="words"))
        assert adapter_module.dump(s) == b"[00:01.00]something else\n"

    def test_only_the_words_the_text_contains_are_stamped(self):
        s = MemoryStore()
        s.add(_ann(1000, 3000, "one two"))
        s.add(_ann(1000, 1500, "one", tier="words"))
        s.add(_ann(1500, 2000, "zzz", tier="words"))  # not in the text
        s.add(_ann(2000, 3000, "two", tier="words"))
        assert adapter_module.dump(s) == (
            b"[00:01.00]<00:01.00>one <00:01.50><00:02.00>two<00:03.00>\n"
        )

    def test_a_point_line_does_not_hold_later_words(self):
        # the reviewer's input: the lyric "last line" was replaced by "zzz"
        s = adapter_module.load("[00:01.00]hello\n[00:04.00]last line\n")
        s.add(_ann(5000, 5500, "zzz", tier="words"))
        assert adapter_module.dump(s) == b"[00:01.00]hello\n[00:04.00]last line\n"

    def test_a_multi_line_word_cannot_break_the_line(self):
        s = MemoryStore()
        s.add(_ann(1000, 3000, "a b c"))
        s.add(_ann(1000, 2000, "a\nb", tier="words"))
        # one physical line; the text after the word is read back as part of it
        assert adapter_module.dump(s) == b"[00:01.00]<00:01.00>a b c<00:02.00>\n"

    def test_overlapping_words_are_cut_so_the_file_reloads(self):
        s = MemoryStore()
        s.add(_ann(1000, 3000, "a b"))
        s.add(_ann(1000, 2500, "a", tier="words"))  # runs past b's start
        s.add(_ann(2000, 3000, "b", tier="words"))
        back = adapter_module.load(adapter_module.dump(s))
        assert _spans(back, "words") == [("a", 1000, 2000), ("b", 2000, 3000)]

    def test_gap_words_dump_in_near_linear_time(self):
        # was quadratic: each word outside every line scanned back to line 0
        # (24.5 s for this input); measured well under 0.1 s now
        n = 4000
        s = MemoryStore()
        for i in range(n):
            s.add(_ann(i * 1000, i * 1000 + 400, f"L{i}"))
            s.add(_ann(i * 1000 + 500, i * 1000 + 600, f"gap{i}", tier="words"))
        began = time.perf_counter()
        blob = adapter_module.dump(s)
        assert time.perf_counter() - began < 2.0  # generous: no CI flakes
        assert b"<" not in blob  # every word is in a gap: all dropped

    def test_bilingual_words_go_to_the_line_that_has_them(self):
        src = "[00:01.00]<00:01.00>Hello <00:01.50>world\n[00:01.00]Bonjour monde\n[00:03.00]x\n"
        assert adapter_module.dump(adapter_module.load(src)).decode() == src

    def test_dump_defaults_to_the_lines_tier(self):
        s = MemoryStore()
        s.add(_ann(0, 1000, "alpha"))
        s.add(_ann(0, 500, "a", tier="phones"))
        assert adapter_module.dump(s) == b"[00:00.00]alpha\n"
        s2 = MemoryStore()  # no lines tier: every text tier but the words
        s2.add(_ann(0, 1000, "cue", tier="cues"))
        s2.add(_ann(0, 500, "cue", tier="words"))
        assert adapter_module.dump(s2) == b"[00:00.00]<00:00.00>cue<00:00.50>\n"

    def test_dump_filters_by_tier(self):
        s = MemoryStore()
        s.add(_ann(0, 1000, "alpha"))
        s.add(_ann(1000, 2000, "omega", tier="other"))
        blob = adapter_module.dump(s, tier="lines")
        assert b"alpha" in blob and b"omega" not in blob

    def test_dump_to_path(self, tmp_path):
        store = adapter_module.load(PLAIN_LRC)
        out = tmp_path / "x.lrc"
        assert adapter_module.dump(store, out) is None
        assert out.read_bytes() == adapter_module.dump(store)

    def test_dump_empty_store(self):
        assert adapter_module.dump(MemoryStore()) == b""


# --- round trips -----------------------------------------------------------


class TestRoundTrip:
    @pytest.mark.parametrize(
        "sample",
        [
            PLAIN_LRC,
            ENHANCED_LRC,
            "[offset:+250]\n[00:12.00][00:45.00]chorus\n[00:20.00]<00:20.00>a <00:20.50>b\n",
        ],
    )
    def test_load_dump_load(self, sample):
        original = adapter_module.load(sample)
        assert _view(adapter_module.load(adapter_module.dump(original))) == _view(
            original
        )

    def test_milliseconds_round_trip_with_precision_ms(self):
        src = "[00:01.001]a\n[00:02.999]<00:02.999>b <00:03.333>c\n"
        original = adapter_module.load(src)
        back = adapter_module.load(adapter_module.dump(original, precision="ms"))
        assert _view(back) == _view(original)

    def test_srt_to_lrc_to_srt_keeps_text_and_starts(self):
        from tests.test_adapter_srt import SAMPLE_SRT

        cues = srt.load(SAMPLE_SRT)
        via_lrc = adapter_module.load(adapter_module.dump(cues))
        back = srt.load(srt.dump(via_lrc))

        def text_and_starts(store):
            return [
                (a.body["text"].replace("\n", " "), a.interval.start)
                for a in sorted(store.all(), key=lambda a: a.interval.start)
                if "text" in a.body
            ]

        assert text_and_starts(via_lrc) == text_and_starts(cues)
        assert text_and_starts(back) == text_and_starts(cues)

    def test_srt_milliseconds_survive_with_precision_ms(self):
        from tests.test_adapter_srt import MESSY_SRT

        cues = srt.load(MESSY_SRT)
        via_lrc = adapter_module.load(adapter_module.dump(cues, precision="ms"))
        assert [a.interval.start for a in _tier(via_lrc, "lines")] == [
            a.interval.start for a in sorted(cues.all(), key=lambda a: a.interval.start)
        ]

    def test_lrc_to_srt(self):
        blob = srt.dump(adapter_module.load(PLAIN_LRC)).decode()
        assert blob.startswith(
            "1\n00:00:12,000 --> 00:00:15,300\nI came down to the river\n"
        )


# --- re-review regressions ---------------------------------------------------


def test_overlapping_lines_keep_their_words_on_a_round_trip():
    """A word of line 1 sung after line 2's tag still belongs to line 1, whose
    text contains it."""
    blob = (
        "[00:10.00]<00:10.00>one <00:13.00>two <00:14.00>\n"
        "[00:12.00]<00:12.00>three <00:15.00>four <00:16.00>\n"
    )
    first = adapter_module.load(blob)
    again = adapter_module.load(adapter_module.dump(first))

    def words(store):
        return sorted(
            (a.body["text"], a.interval.start, a.interval.end)
            for a in store.all()
            if a.tier == "words"
        )

    assert words(again) == words(first)
    assert [w[0] for w in words(first)] == ["four", "one", "three", "two"]


def test_a_file_with_no_lrc_content_is_refused():
    srt = "1\n00:00:01,000 --> 00:00:02,000\nhello\n"
    with pytest.raises(ValueError, match="not an LRC file"):
        adapter_module.load(srt)


def test_an_empty_input_is_an_empty_store():
    assert list(adapter_module.load("").all()) == []
