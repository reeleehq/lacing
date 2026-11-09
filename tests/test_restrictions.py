"""``restriction_breach``, the ``Use`` it reads, and the territory vocabulary (reeleehq/an#743)."""

import pytest

from lacing import (
    REVENUE_CAP,
    TERRITORY_EXCLUDED,
    Restriction,
    Rights,
    Use,
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
    reason = restriction_breach(CAP, Use(revenue_usd=revenue))
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
    ],
)
def test_an_excluded_territory_fails_closed(territory, breaks):
    reason = restriction_breach(HUNYUAN, Use(territory=territory))
    assert (reason is not None) is breaks


@pytest.mark.parametrize("territory", ["Korea", "Franc", "FRA", "EU"])
def test_a_use_refuses_a_territory_it_cannot_place(territory):
    with pytest.raises(ValueError, match="alpha-2"):
        Use(territory=territory)


@pytest.mark.parametrize("revenue", [True, 1.5, "100"])
def test_a_use_refuses_a_revenue_that_is_not_an_int(revenue):
    with pytest.raises(TypeError, match="whole number"):
        Use(revenue_usd=revenue)


def test_a_use_refuses_a_negative_revenue_and_is_frozen():
    with pytest.raises(ValueError, match="negative"):
        Use(revenue_usd=-1)
    use = Use(revenue_usd=0, territory="uk")
    assert use == Use(territory="GB", revenue_usd=0)
    with pytest.raises(AttributeError):
        use.territory = "FR"
    with pytest.raises(TypeError):
        Use(0, "US")  # keyword-only


def test_a_restriction_says_what_the_use_must_state():
    assert "state the territory" in restriction_breach(HUNYUAN)
    assert "state the revenue" in restriction_breach(CAP)
    assert "WORLD: a use everywhere includes them" in restriction_breach(
        HUNYUAN, Use(territory="world")
    )
    assert "the use: FR" in restriction_breach(HUNYUAN, Use(territory="fr"))


def test_recorded_codes_are_read_through_their_aliases():
    assert territory_excluded({"uk"}, "GB") and territory_excluded({"EL"}, "gr")
    assert not territory_excluded({"uk", "EU"}, "US")


@pytest.mark.parametrize("recorded", [{"Franc"}, {"FRA"}, {"KR", "Asia"}])
def test_an_unplaceable_recorded_code_excludes_every_use(recorded):
    assert territory_excluded(recorded, "US")
    breach = restriction_breach(
        Restriction(kind=TERRITORY_EXCLUDED, codes=sorted(recorded)),
        Use(territory="US"),
    )
    assert breach is not None


def test_a_recorded_world_excludes_every_use():
    assert territory_excluded({"WORLD"}, "US") and territory_excluded({"world"}, "JP")
    world = Restriction(kind=TERRITORY_EXCLUDED, codes=["WORLD"])
    assert restriction_breach(world, Use(territory="US")) is not None


def test_an_unknown_kind_is_never_cleared_and_a_known_one_can_be_overridden():
    odd = Restriction(kind="no_broadcast", terms="station-terms")
    assert restriction_breach(odd, Use(revenue_usd=0, territory="US")) == (
        "station-terms: an unknown restriction 'no_broadcast': not cleared"
    )
    assert restriction_breach(odd, checks={"no_broadcast": lambda r, use: None}) is None


def test_every_restriction_of_a_rights_record_is_checked():
    rights = Rights(provider="p", license="CC-BY-4.0", restrictions=[CAP, HUNYUAN])
    use = Use(revenue_usd=5_000, territory="DE")
    reasons = [r for x in rights.restrictions if (r := restriction_breach(x, use))]
    assert reasons == ["not allowed in EU, GB, KR (the use: DE)"]


def test_normalize_territory_refuses_what_it_cannot_place():
    with pytest.raises(ValueError, match="alpha-2"):
        normalize_territory("FRA")


def test_a_code_nobody_can_place_is_named_as_the_reason():
    franc = Restriction(kind=TERRITORY_EXCLUDED, codes=["KR", "Franc"])
    assert restriction_breach(franc, Use(territory="US")) == (
        "records 'Franc', which excludes every use"
    )
    world = Restriction(kind=TERRITORY_EXCLUDED, codes=["WORLD"])
    assert "records 'WORLD'" in restriction_breach(world, Use(territory="US"))
