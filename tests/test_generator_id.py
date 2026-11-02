"""The ``was_generated_by`` grammar, its advisory check, and the activity vocabulary
(lacing#17)."""

from __future__ import annotations

import warnings
from collections import Counter
from uuid import uuid4

import pytest

from lacing import (
    GENERATOR_PREFIXES,
    PROVENANCE_ACTIVITIES,
    VERSIONED_PREFIXES,
    Annotation,
    GeneratorId,
    GeneratorIdWarning,
    MediaRef,
    Provenance,
    RationalTime,
    TimeInterval,
    generator_id_findings,
    parse_generator_id,
)
from lacing.generator_id import GENERATOR_ID_SHAPE
from lacing.store import SqliteStore
from lacing.tier import Tier

WRONG_SHAPE = f"not of the shape {GENERATOR_ID_SHAPE!r}"
UNDOCUMENTED = "undocumented prefix {!r}".format


def _provenance(was_generated_by, **kw):
    return Provenance(
        was_generated_by=was_generated_by,
        was_attributed_to="thor",
        generated_at_time=RationalTime.now(),
        **kw,
    )


def _interval():
    return TimeInterval(RationalTime(0), RationalTime(10))


# The census of lacing#17: the writers seen in the federation so far, as written,
# with the findings each gets today. Not exhaustive: add a writer when one turns up.
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
    "lacing.tracks.subtitle": [WRONG_SHAPE],  # the old default, in stored rows
    "reelee.locks.create_reference_lock": [WRONG_SHAPE],
    "reelee.gotchas.record_discovered_gotcha": [WRONG_SHAPE],
    "an.render.render_project": [WRONG_SHAPE],
    "braidio:importer": [UNDOCUMENTED("braidio")],
    "muvid:align": [UNDOCUMENTED("muvid")],
    "system:edits": [UNDOCUMENTED("system")],
    "orchestrator:supervisor": [UNDOCUMENTED("orchestrator")],
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
    assert generator_id_findings(value) == [WRONG_SHAPE]


@pytest.mark.parametrize(
    "value",
    [v for v in CENSUS if parse_generator_id(v)]
    + ["agent:fal-ai/flux@sha256:9f2c", "adapter:textgrid", "user:a.b"],
)
def test_a_parsed_id_prints_back_verbatim(value):
    assert str(parse_generator_id(value)) == value


def test_the_parts():
    assert parse_generator_id("agent:m@1") == GeneratorId("agent", "m", "1")


def test_at_is_the_version_separator_under_every_prefix():
    assert parse_generator_id("user:a@b.com") == GeneratorId("user", "a", "b.com")


def test_the_convention_is_injectable():
    assert generator_id_findings("test:doctest", prefixes={"test"}) == []
    assert generator_id_findings("user:thor", versioned={"user"}) == [
        "prefix 'user' expects an @<version>"
    ]


def test_every_versioned_prefix_is_documented():
    assert VERSIONED_PREFIXES <= set(GENERATOR_PREFIXES)


def test_a_census_is_one_counter_over_findings():
    counts = Counter(f for v in CENSUS for f in generator_id_findings(v))
    assert counts == {
        "prefix 'agent' expects an @<version>": 1,
        WRONG_SHAPE: 4,
        **{
            UNDOCUMENTED(p): 1
            for p in ("test", "braidio", "muvid", "system", "orchestrator")
        },
    }


# --- the advisory flag at construction ----------------------------------------


def test_a_malformed_generator_id_is_flagged_not_rejected():
    with pytest.warns(GeneratorIdWarning, match="'t'"):
        prov = _provenance("t")
    assert prov.was_generated_by == "t"  # still accepted


@pytest.mark.parametrize(
    "construct",
    [
        lambda: _provenance("t"),
        lambda: Provenance.model_validate(
            _provenance("user:thor").model_dump(mode="json") | {"was_generated_by": "t"}
        ),
    ],
    ids=["init", "model_validate"],
)
def test_the_flag_points_at_the_caller_not_at_pydantic(construct):
    with pytest.warns(GeneratorIdWarning) as caught:
        construct()
    assert [w.filename for w in caught] == [__file__]


def test_a_store_read_of_a_legacy_row_is_flagged(tmp_path):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", GeneratorIdWarning)
        legacy = Annotation(
            id=uuid4(),
            tier="words",
            reference=MediaRef(asset_id="blake3:t", interval=_interval()),
            body={"text": "x"},
            body_schema_uri="annot://schema/word/v1",
            provenance=_provenance("lacing.tracks.subtitle"),
        )
    store = SqliteStore(tmp_path / "legacy.annot")
    try:
        store.add_tier(Tier("words"))
        store.add(legacy)
        with pytest.warns(GeneratorIdWarning, match="lacing.tracks.subtitle"):
            store[_interval()]
    finally:
        store.close()


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
