"""The ``was_generated_by`` grammar, its advisory check, and the activity vocabulary
(lacing#17)."""

from __future__ import annotations

import warnings
from collections import Counter

import pytest

from lacing import (
    GENERATOR_PREFIXES,
    PROVENANCE_ACTIVITIES,
    GeneratorId,
    GeneratorIdWarning,
    Provenance,
    RationalTime,
    generator_id_findings,
    parse_generator_id,
)


def _provenance(was_generated_by, **kw):
    return Provenance(
        was_generated_by=was_generated_by,
        was_attributed_to="thor",
        generated_at_time=RationalTime.now(),
        **kw,
    )


# The census of lacing#17: every writer seen in the federation, as written.
CENSUS = {
    "agent:fal@fal-ai/flux/dev": [],  # a slug in the @ slot: not detectable
    "agent:falaw-plan@fal-ai/flux/dev": [],
    "transform:caption@1.2.0": [],
    "agent:nw.graph": ["prefix 'agent' expects an @<version>"],
    "user:thor": [],
    "test:doctest": ["undocumented prefix 'test'"],
    "server:lacing": [],
    "fetch:openverse": [],
    "processor:lacing.tracks.subtitle": [],
}


@pytest.mark.parametrize("value, findings", CENSUS.items())
def test_the_census_values_get_the_expected_findings(value, findings):
    assert generator_id_findings(value) == findings


@pytest.mark.parametrize(
    "value",
    ["", "t", "thor", "agent:", ":x", "Agent:x", "agent:a b", "agent:x@", "a:b@c@d"],
)
def test_values_of_the_wrong_shape_do_not_parse(value):
    assert parse_generator_id(value) is None
    assert generator_id_findings(value) == [
        "not of the shape '<prefix>:<name>[@<version>]'"
    ]


@pytest.mark.parametrize(
    "value", ["agent:fal-ai/flux@sha256:9f2c", "adapter:textgrid", "user:a.b"]
)
def test_a_parsed_id_prints_back_verbatim(value):
    assert str(parse_generator_id(value)) == value


def test_the_parts():
    assert parse_generator_id("agent:m@1") == GeneratorId("agent", "m", "1")


def test_the_convention_is_injectable():
    assert generator_id_findings("test:doctest", prefixes={"test"}) == []
    assert generator_id_findings("user:thor", versioned={"user"}) == [
        "prefix 'user' expects an @<version>"
    ]


def test_every_versioned_prefix_is_documented():
    from lacing.generator_id import VERSIONED_PREFIXES

    assert VERSIONED_PREFIXES <= set(GENERATOR_PREFIXES)


def test_a_census_is_one_counter_over_findings():
    counts = Counter(f for v in CENSUS for f in generator_id_findings(v))
    assert counts == {
        "prefix 'agent' expects an @<version>": 1,
        "undocumented prefix 'test'": 1,
    }


# --- the advisory flag at construction ----------------------------------------


def test_a_malformed_generator_id_is_flagged_not_rejected():
    with pytest.warns(GeneratorIdWarning, match="'t'"):
        prov = _provenance("t")
    assert prov.was_generated_by == "t"  # still accepted


@pytest.mark.parametrize("value", ["agent:nw.graph", "test:doctest", "user:thor"])
def test_convention_findings_are_not_flagged_at_construction(value):
    with warnings.catch_warnings():
        warnings.simplefilter("error", GeneratorIdWarning)
        _provenance(value)


def test_the_flag_escalates_to_a_rejection_through_the_warnings_filter():
    with warnings.catch_warnings():
        warnings.simplefilter("error", GeneratorIdWarning)
        with pytest.raises(GeneratorIdWarning):
            _provenance("thor")


# --- activity ------------------------------------------------------------------


def test_cache_hit_is_a_documented_activity():
    assert "cache-hit" in PROVENANCE_ACTIVITIES
    field = Provenance.model_fields["activity"]
    assert all(f"``{name}``" in field.description for name in PROVENANCE_ACTIVITIES)
    assert _provenance("agent:m@1", activity="cache-hit").activity == "cache-hit"


def test_activity_stays_unconstrained():
    """Tightening to a Literal would reject persisted data (lacing#17)."""
    assert _provenance("user:thor", activity="something-old").activity == (
        "something-old"
    )
