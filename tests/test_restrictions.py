"""``restriction_breach`` and the territory vocabulary (reeleehq/an#743)."""

import pytest

from lacing import (
    REVENUE_CAP,
    TERRITORY_EXCLUDED,
    Restriction,
    Rights,
    normalize_territory,
    restriction_breach,
    territory_excluded,
)

CAP = Restriction(kind=REVENUE_CAP, usd=1_000_000, terms="stability-community")
HUNYUAN = Restriction(kind=TERRITORY_EXCLUDED, codes=["EU", "GB", "KR"])


@pytest.mark.parametrize(
    "revenue, breaks", [(0, False), (999_999, False), (1_000_000, True), (None, True)]
)
def test_a_revenue_cap_allows_only_below_the_cap(revenue, breaks):
    reason = restriction_breach(CAP, revenue_usd=revenue)
    assert (reason is not None) is breaks
    if breaks:
        assert reason.startswith("stability-community: allowed only below $1,000,000")


@pytest.mark.parametrize(
    "territory, breaks",
    [
        ("US", False),
        ("jp", False),
        ("FR", True),  # in the EU
        ("AX", True),  # Åland, an EU territory with its own code
        ("uk", True),  # an alias of GB
        ("kr", True),
        (None, True),  # unstated: fail closed
        ("", True),
        ("WORLD", True),  # everywhere includes them
        ("Korea", True),  # not a code: fail closed
    ],
)
def test_an_excluded_territory_fails_closed(territory, breaks):
    assert (restriction_breach(HUNYUAN, territory=territory) is not None) is breaks


def test_a_restriction_says_what_the_use_must_state():
    assert "state the territory" in restriction_breach(HUNYUAN)
    assert "state the revenue" in restriction_breach(CAP)
    assert "WORLD" in restriction_breach(HUNYUAN, territory="world")


def test_recorded_codes_are_read_through_their_aliases():
    assert territory_excluded({"uk"}, "GB") and territory_excluded({"EL"}, "gr")


def test_an_unknown_kind_is_never_cleared_and_a_known_one_can_be_overridden():
    odd = Restriction(kind="no_broadcast", terms="station-terms")
    assert restriction_breach(odd, revenue_usd=0, territory="US") == (
        "station-terms: an unknown restriction 'no_broadcast': not cleared"
    )
    assert (
        restriction_breach(odd, checks={"no_broadcast": lambda r, rev, t: None}) is None
    )


def test_every_restriction_of_a_rights_record_is_checked():
    rights = Rights(provider="p", license="CC-BY-4.0", restrictions=[CAP, HUNYUAN])
    use = {"revenue_usd": 5_000, "territory": "DE"}
    reasons = [r for x in rights.restrictions if (r := restriction_breach(x, **use))]
    assert reasons == ["not allowed in EU, GB, KR (the use: DE)"]


def test_normalize_territory_refuses_what_it_cannot_place():
    with pytest.raises(ValueError, match="alpha-2"):
        normalize_territory("FRA")
