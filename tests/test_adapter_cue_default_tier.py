"""The cue writers (SubRip, WebVTT) given no ``tier=``: the lines, not the words."""

from __future__ import annotations

import pytest

from lacing.adapters import lrc, srt, webvtt
from lacing.store import MemoryStore
from lacing.tier import Tier, TierStereotype

from tests.test_adapter_lrc import ENHANCED_LRC
from tests.test_adapter_srt import _ms


@pytest.fixture
def karaoke():
    return lrc.load(ENHANCED_LRC)


@pytest.mark.parametrize("writer", [srt, webvtt])
def test_a_karaoke_store_is_written_as_its_lines(writer, karaoke):
    text = writer.dump(karaoke).decode("utf-8")
    assert "plain line" in text and "Oh yeah" in text
    # no per-word cue
    assert "\nyeah\n" not in text and "\nby\n" not in text


@pytest.mark.parametrize("writer", [srt, webvtt])
def test_tier_still_overrides(writer, karaoke):
    text = writer.dump(karaoke, tier="words").decode("utf-8")
    assert "\nyeah\n" in text and "plain line" not in text


@pytest.mark.parametrize("writer", [srt, webvtt])
def test_without_a_lines_tier_every_top_level_tier_is_written(writer):
    s = MemoryStore()
    s.add_tier(Tier("a"))
    s.add_tier(Tier("b"))
    s.add_tier(Tier("sub", stereotype=TierStereotype.INCLUDED_IN, parent="a"))
    s.add(_ms(0, 1000, "alpha", tier="a"))
    s.add(_ms(1000, 2000, "beta", tier="b"))
    s.add(_ms(0, 500, "nested", tier="sub"))
    text = writer.dump(s).decode("utf-8")
    assert "alpha" in text and "beta" in text and "nested" not in text


@pytest.mark.parametrize("writer", [srt, webvtt])
def test_undeclared_tiers_are_top_level(writer):
    s = MemoryStore()
    s.add(_ms(0, 1000, "alpha", tier="x"))
    s.add(_ms(1000, 2000, "beta", tier="y"))
    text = writer.dump(s).decode("utf-8")
    assert "alpha" in text and "beta" in text
