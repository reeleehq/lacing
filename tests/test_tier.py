"""Tests for lacing.tier — stereotypes, Tier value semantics, constraint validation."""

import pytest

from lacing.tier import Tier, TierStereotype, validate_tier_constraint
from lacing.time import RationalTime, TimeInterval


def _ti(s: int, e: int) -> TimeInterval:
    return TimeInterval(RationalTime(s, 1), RationalTime(e, 1))


def _child(stereotype, parent="p"):
    return Tier("c", stereotype=stereotype, parent=parent)


# --- Tier construction -----------------------------------------------------


@pytest.mark.parametrize("bad", ["", None, 3])
def test_name_must_be_nonempty_string(bad):
    with pytest.raises(ValueError):
        Tier(bad)


def test_stereotype_must_be_enum():
    with pytest.raises(TypeError):
        Tier("t", stereotype="NONE")


def test_parent_must_be_str():
    with pytest.raises(TypeError):
        Tier("t", stereotype=TierStereotype.INCLUDED_IN, parent=3)


def test_stereotype_requires_parent():
    with pytest.raises(ValueError, match="requires a parent"):
        Tier("t", stereotype=TierStereotype.INCLUDED_IN)


def test_none_stereotype_rejects_parent():
    with pytest.raises(ValueError, match="cannot have a parent"):
        Tier("t", parent="p")


def test_properties_and_metadata_copy():
    t = Tier("t", metadata={"a": 1})
    assert (t.name, t.stereotype, t.parent) == ("t", TierStereotype.NONE, None)
    m = t.metadata
    m["a"] = 2
    assert t.metadata == {"a": 1}


def test_wire_roundtrip():
    t = Tier("c", stereotype=TierStereotype.INCLUDED_IN, parent="p", metadata={"k": "v"})
    d = t.to_wire()
    assert d == {
        "name": "c",
        "stereotype": "INCLUDED_IN",
        "parent": "p",
        "metadata": {"k": "v"},
    }
    assert Tier.from_wire(d) == t


def test_wire_minimal():
    assert Tier("t").to_wire() == {"name": "t", "stereotype": "NONE"}
    assert Tier.from_wire({"name": "t"}) == Tier("t")


def test_equality_hash_repr():
    a, b = Tier("t"), Tier("t")
    assert a == b and hash(a) == hash(b)
    assert a != Tier("t", metadata={"x": 1})
    assert a != "t"
    assert "Tier('t'" in repr(a)


# --- validate_tier_constraint ---------------------------------------------


def test_none_stereotype():
    t = Tier("t")
    assert validate_tier_constraint(None, t, [], [_ti(0, 1)]) == []
    out = validate_tier_constraint(Tier("p"), t, [], [])
    assert "stereotype NONE" in out[0]


def test_missing_parent():
    out = validate_tier_constraint(None, _child(TierStereotype.INCLUDED_IN), [], [])
    assert "requires a parent" in out[0]


def test_wrong_parent_name():
    out = validate_tier_constraint(
        Tier("other"), _child(TierStereotype.SYMBOLIC_ASSOCIATION), [], []
    )
    assert any("declares parent" in v for v in out)


def test_included_in():
    c = _child(TierStereotype.INCLUDED_IN)
    p = Tier("p")
    assert validate_tier_constraint(p, c, [_ti(0, 10)], [_ti(1, 2), _ti(5, 9)]) == []
    out = validate_tier_constraint(p, c, [_ti(0, 10)], [_ti(5, 11)])
    assert len(out) == 1 and "not contained" in out[0]


def test_symbolic_association():
    c = _child(TierStereotype.SYMBOLIC_ASSOCIATION)
    p = Tier("p")
    assert validate_tier_constraint(p, c, [_ti(0, 1)], [_ti(0, 1)]) == []
    out = validate_tier_constraint(p, c, [_ti(0, 1)], [_ti(0, 2)])
    assert "mismatch" in out[0]
    out = validate_tier_constraint(p, c, [_ti(0, 1)], [])
    assert "expects 1 child" in out[0]


def test_time_subdivision_valid_and_invalid():
    c = _child(TierStereotype.TIME_SUBDIVISION)
    p = Tier("p")
    par = [_ti(0, 10)]
    assert validate_tier_constraint(p, c, par, [_ti(0, 4), _ti(4, 10)]) == []
    out = validate_tier_constraint(p, c, par, [])
    assert "has no children" in out[0]
    out = validate_tier_constraint(p, c, par, [_ti(1, 4), _ti(4, 9)])
    assert any("does not start" in v for v in out)
    assert any("does not end" in v for v in out)
    out = validate_tier_constraint(p, c, par, [_ti(0, 3), _ti(4, 10)])
    assert any("gap or overlap" in v for v in out)


def test_symbolic_subdivision_containment():
    c = _child(TierStereotype.SYMBOLIC_SUBDIVISION)
    p = Tier("p")
    assert validate_tier_constraint(p, c, [_ti(0, 5)], [_ti(0, 5)]) == []
    out = validate_tier_constraint(p, c, [_ti(0, 5)], [_ti(4, 6)])
    assert "not within any parent" in out[0]
